"""Versioned disconnected-control adapter for image-build.

This module is transport-neutral.  It knows nothing about GitHub, SQS, AWS, or
ChatGPT.  A trusted caller supplies the repository identity/revision actually
deployed on the host and a versioned request.  Mutable execution always flows
through ImageBuild and its configured box-control/root-control adapter.
"""
from __future__ import annotations

from dataclasses import asdict
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil

from .build_views import read_build_commands
from .errors import ImageBuildError
from .filesystem import ensure_directory, inventory, write_json
from .metadata import identity, load_package, load_packages, names, order
from .runner import BuildExecutionRequest

REQUEST_SCHEMA = "image-build-remote-operation-v1"
RESULT_SCHEMA = "image-build-remote-result-v1"
DIAGNOSTIC_SCHEMA = "image-build-diagnostic-v1"
_OPERATION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_REVISION = re.compile(r"[0-9a-f]{40,64}")
_DIAGNOSTIC = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")
_GENERATION = re.compile(r"[0-9a-f]{64}")
MAX_COMMANDS = 24
MAX_MISSING = 24
MAX_INVENTORY_ITEMS = 128


def _json(value, label):
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ImageBuildError(label + " must be JSON data") from error


def _relative(value, label):
    if not isinstance(value, str) or not value or "\0" in value:
        raise ImageBuildError("invalid " + label)
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ImageBuildError("unsafe " + label)
    return path.as_posix()


def _sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


class RemoteOperations:
    def __init__(
        self,
        builder,
        *,
        repository_root,
        source_repository,
        source_revision,
    ):
        self.builder = builder
        self.repository_root = Path(repository_root).resolve()
        self.source_repository = source_repository
        self.source_revision = source_revision
        if (
            not isinstance(source_repository, str)
            or not source_repository
            or len(source_repository) > 512
            or any(ord(c) < 32 for c in source_repository)
        ):
            raise ImageBuildError("invalid deployed source repository identity")
        if not isinstance(source_revision, str) or not _REVISION.fullmatch(source_revision):
            raise ImageBuildError("deployed source revision must be an immutable commit identity")
        try:
            Path(builder.package_dir).resolve().relative_to(self.repository_root)
        except ValueError as error:
            raise ImageBuildError(
                "package directory must be inside the deployed repository"
            ) from error
        self.root = Path(builder.state) / "image-build" / "remote-operations"
        ensure_directory(self.root)

    def _directory(self, operation_id):
        if not isinstance(operation_id, str) or not _OPERATION_ID.fullmatch(operation_id):
            raise ImageBuildError("invalid remote operation identity")
        return self.root / operation_id

    def _owner(self, request):
        value = {
            "contract": REQUEST_SCHEMA,
            "operation_id": request["operation_id"],
            "source_repository": request["source"]["repository"],
            "source_revision": request["source"]["revision"],
        }
        if request.get("predecessor") is not None:
            value["predecessor"] = request["predecessor"]
        return value

    def _validate_request(self, request):
        request = _json(request, "remote request")
        required = {"schema", "operation_id", "operation", "source", "arguments"}
        if set(request) not in (required, required | {"predecessor"}):
            raise ImageBuildError("remote request has missing or unsupported fields")
        if request["schema"] != REQUEST_SCHEMA:
            raise ImageBuildError("unsupported remote request schema")
        self._directory(request["operation_id"])
        if request["operation"] not in {
            "recipe.validate",
            "package.inspect",
            "dependencies.resolve",
            "pipeline.submit",
            "pipeline.inspect",
            "pipeline.resume",
            "pipeline.cancel",
            "pipeline.retry",
            "generation.inspect",
            "diagnostic.submit",
            "diagnostic.inspect",
        }:
            raise ImageBuildError("unsupported remote operation")
        source = request["source"]
        if not isinstance(source, dict) or set(source) != {"repository", "revision"}:
            raise ImageBuildError("remote source binding requires repository and revision")
        if (
            source["repository"] != self.source_repository
            or source["revision"] != self.source_revision
        ):
            raise ImageBuildError("remote request source differs from deployed source")
        if not isinstance(request["arguments"], dict):
            raise ImageBuildError("remote operation arguments must be an object")
        predecessor = request.get("predecessor")
        if predecessor is not None:
            self._directory(predecessor)
            if predecessor == request["operation_id"]:
                raise ImageBuildError("remote operation cannot precede itself")
        return request

    def _save_request(self, request):
        directory = self._directory(request["operation_id"])
        ensure_directory(directory)
        path = directory / "request.json"
        if path.exists():
            try:
                existing = json.loads(path.read_text())
            except (OSError, ValueError, TypeError) as error:
                raise ImageBuildError("invalid retained remote request") from error
            if existing != request:
                raise ImageBuildError("remote operation identity belongs to different input")
        else:
            write_json(path, request)
        return directory

    def _binding(self, directory):
        path = directory / "binding.json"
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError, TypeError) as error:
            raise ImageBuildError("invalid retained remote operation binding") from error
        if not isinstance(value, dict):
            raise ImageBuildError("invalid retained remote operation binding")
        return value

    def _write_binding(self, directory, value):
        value = _json(value, "remote operation binding")
        path = directory / "binding.json"
        if path.exists():
            existing = self._binding(directory)
            if existing != value:
                raise ImageBuildError("remote operation binding changed")
        else:
            write_json(path, value)
        return value

    def _write_result(self, directory, result):
        result = _json(result, "remote result")
        encoded = json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        if len(encoded) > 128 * 1024:
            raise ImageBuildError("remote result exceeds bounded summary limit")
        write_json(directory / "result.json", result)
        return result

    def _generation(self, generation):
        if not isinstance(generation, str) or not _GENERATION.fullmatch(generation):
            raise ImageBuildError("invalid generation identity")
        from .engine import read_selection
        return read_selection(
            Path(self.builder.state)
            / "image-build"
            / "generations"
            / generation
        )

    def _recipe(self, package):
        names([package])
        path = Path(self.builder.package_dir) / package
        if not path.is_dir():
            raise ImageBuildError("unknown package: " + package)
        return load_package(path)

    def _pipeline_owner(self, record):
        owner = record.get("owner")
        return owner if isinstance(owner, dict) else None

    def _find_owned_pipeline(self, request):
        matches = []
        pipelines = Path(self.builder.state) / "image-build" / "pipelines"
        if not pipelines.exists():
            return None
        for path in pipelines.glob("*/pipeline.json"):
            try:
                record = json.loads(path.read_text())
            except (OSError, ValueError, TypeError):
                continue
            owner = self._pipeline_owner(record)
            if (
                owner
                and owner.get("contract") == REQUEST_SCHEMA
                and owner.get("operation_id") == request["operation_id"]
            ):
                matches.append(record)
        if len(matches) > 1:
            raise ImageBuildError("remote operation owns multiple pipelines")
        return matches[0] if matches else None

    def _pipeline_arguments(self, request):
        arguments = request["arguments"]
        if set(arguments) - {"mode", "selection", "targets", "stages"}:
            raise ImageBuildError("unsupported pipeline submission argument")
        mode = arguments.get("mode")
        if mode not in {"image", "bootstrap", "seed-check", "native-check"}:
            raise ImageBuildError("invalid remote pipeline mode")
        selection = self._generation(arguments.get("selection"))
        if mode == "bootstrap":
            if set(arguments) != {"mode", "selection", "stages"}:
                raise ImageBuildError("bootstrap requires selection and stages")
            stages = arguments["stages"]
            if (
                not isinstance(stages, list)
                or not stages
                or any(not isinstance(stage, list) or not stage for stage in stages)
            ):
                raise ImageBuildError("bootstrap stages must be nonempty package lists")
            stages = [list(names(stage)) for stage in stages]
            return mode, selection, {"stages": stages}
        if set(arguments) != {"mode", "selection", "targets"}:
            raise ImageBuildError("image/native pipeline requires selection and targets")
        targets = list(names(arguments["targets"]))
        return mode, selection, {"targets": targets}

    def _prepare_pipeline(self, request, directory):
        binding = self._binding(directory)
        if binding and binding.get("pipeline_id"):
            return binding["pipeline_id"]
        recovered = self._find_owned_pipeline(request)
        if recovered is not None:
            self._write_binding(directory, {"pipeline_id": recovered["pipeline_id"]})
            return recovered["pipeline_id"]
        mode, selection, arguments = self._pipeline_arguments(request)
        record = self.builder.prepare_pipeline(
            mode,
            selection,
            owner=self._owner(request),
            **arguments,
        )
        self._write_binding(directory, {"pipeline_id": record["pipeline_id"]})
        return record["pipeline_id"]

    def _attempt_paths(self, record):
        root = Path(self.builder.state) / "image-build" / "attempts"
        return [root / name for name in record.get("attempts", {}).values()]

    def _log_excerpt(self, job_id):
        execute = getattr(self.builder.runner, "execute", None)
        control = getattr(execute, "control", None)
        if control is None or not job_id:
            return None
        try:
            page = control.build_job_logs(job_id, limit=12)
        except Exception:
            return None
        entries = page.get("entries", []) if isinstance(page, dict) else []
        from .trace_records import sanitize
        messages = []
        total = 0
        for entry in entries[:12]:
            message = sanitize(str(entry.get("message", "")))
            encoded = message.encode("utf-8", "replace")
            if len(encoded) > 2048:
                message = encoded[:2048].decode("utf-8", "ignore") + "…"
                encoded = message.encode("utf-8")
            if total + len(encoded) > 8192:
                break
            total += len(encoded)
            messages.append(message)
        return {
            "messages": messages,
            "has_more": bool(page.get("has_more")),
        }

    def _evidence(self, record):
        commands = []
        failures = []
        missing = []
        observations = {}
        for attempt in self._attempt_paths(record):
            if not attempt.exists():
                missing.append(
                    {
                        "kind": "attempt-directory",
                        "locator": str(attempt.relative_to(Path(self.builder.state))),
                    }
                )
                continue
            try:
                page = read_build_commands(attempt, limit=MAX_COMMANDS)
                commands.extend(page["commands"])
            except Exception:
                missing.append(
                    {
                        "kind": "command-view",
                        "locator": str(attempt.relative_to(Path(self.builder.state))),
                    }
                )
            for path in sorted(attempt.rglob("*.execution.json")):
                try:
                    value = json.loads(path.read_text())
                except (OSError, ValueError, TypeError):
                    continue
                if (
                    value.get("cleanup_complete") is True
                    and type(value.get("exit_code")) is int
                    and value["exit_code"] != 0
                ):
                    failures.append(
                        {
                            "kind": "command-exit",
                            "exit_code": value["exit_code"],
                            "journal_reference": value.get("journal_reference"),
                            "process_cleanup_complete": value.get(
                                "process_cleanup_complete"
                            ),
                            "locator": str(path.relative_to(Path(self.builder.state))),
                        }
                    )
            for path in sorted(attempt.rglob("*.observation.json")):
                try:
                    value = json.loads(path.read_text())
                except (OSError, ValueError, TypeError):
                    continue
                if value.get("job_id"):
                    observations[value["job_id"]] = {
                        key: value.get(key)
                        for key in (
                            "state",
                            "outcome",
                            "exit_code",
                            "signal",
                            "journal_reference",
                            "process_cleanup_complete",
                        )
                        if key in value
                    }
                if value.get("outcome") in {
                    "nonzero-exit",
                    "signal",
                    "timeout",
                    "fault",
                    "cancelled",
                    "unknown",
                }:
                    failures.append(
                        {
                            "kind": "controller-outcome",
                            "outcome": value.get("outcome"),
                            "job_id": value.get("job_id"),
                            "journal_reference": value.get("journal_reference"),
                            "process_cleanup_complete": value.get(
                                "process_cleanup_complete"
                            ),
                            "locator": str(path.relative_to(Path(self.builder.state))),
                        }
                    )
        commands = commands[:MAX_COMMANDS]
        missing = missing[:MAX_MISSING]
        jobs = []
        for command in commands:
            if command.get("job_id"):
                job = {
                    "job_id": command["job_id"],
                    "request_id": command.get("request_id"),
                    "attempt_id": command.get("attempt_id"),
                    "package": command.get("package"),
                    "stage": command.get("stage_id"),
                    "phase": command.get("phase"),
                    "command_index": command.get("command_index"),
                    "command_key": command.get("command_key"),
                    "command": command.get("command"),
                }
                job.update(observations.get(command["job_id"], {}))
                excerpt = self._log_excerpt(command["job_id"])
                if excerpt is not None:
                    job["log_excerpt"] = excerpt
                jobs.append(job)
        return commands, jobs, failures, missing

    def _pipeline_summary(self, request, pipeline_id, *, raised=None):
        try:
            record = self.builder.inspect_pipeline(pipeline_id)
        except Exception as error:
            return self._base_result(
                request,
                status="pending",
                terminal_outcome=None,
                uncertainty=True,
                failure={"type": type(error).__name__, "reason": str(error)},
                missing_evidence=[{"kind": "pipeline-record", "locator": pipeline_id}],
                allowed_next_operations=["pipeline.inspect"],
                pipeline_id=pipeline_id,
            )
        commands, jobs, failures, missing = self._evidence(record)
        status = record.get("status")
        uncertainty = False
        outcome = None
        allowed = []
        failure = None
        if status == "complete":
            remote_status = "completed"
            outcome = "success"
        elif status == "released":
            remote_status = "released"
            outcome = "released"
            allowed = ["pipeline.inspect"]
        else:
            unknown = any(item.get("outcome") == "unknown" for item in failures)
            terminal = [
                item
                for item in failures
                if item.get("kind") == "command-exit"
                or (
                    item.get("outcome") not in (None, "unknown")
                    and item.get("process_cleanup_complete") is not False
                )
            ]
            if terminal:
                remote_status = "failed"
                outcome = terminal[-1].get("outcome") or "nonzero-exit"
                failure = terminal[-1]
                allowed = ["pipeline.retry", "pipeline.inspect"]
            else:
                remote_status = "pending"
                uncertainty = unknown or "unknown" in str(record.get("error", "")).lower()
                failure = (
                    {"type": type(raised).__name__, "reason": str(raised)}
                    if raised is not None
                    else (
                        {"type": "pending", "reason": record.get("error")}
                        if record.get("error")
                        else None
                    )
                )
                allowed = ["pipeline.resume", "pipeline.inspect", "pipeline.cancel"]
        if status == "complete":
            allowed = ["pipeline.inspect"]
        result = self._base_result(
            request,
            status=remote_status,
            terminal_outcome=outcome,
            uncertainty=uncertainty,
            failure=failure,
            missing_evidence=missing,
            allowed_next_operations=allowed,
            pipeline_id=pipeline_id,
        )
        result["attempt_ids"] = sorted(record.get("attempts", {}).values())
        result["controller_jobs"] = jobs[:MAX_COMMANDS]
        result["log_locators"] = [
            {
                "job_id": item.get("job_id"),
                "journal_reference": item.get("journal_reference"),
                "locator": item.get("locator"),
            }
            for item in failures
            if item.get("journal_reference") or item.get("locator")
        ][:MAX_COMMANDS]
        result["package"] = jobs[-1].get("package") if jobs else None
        result["stage"] = jobs[-1].get("stage") if jobs else None
        result["phase"] = jobs[-1].get("phase") if jobs else None
        if record.get("generation"):
            result["selected_generation"] = record["generation"]
            try:
                selection = self._generation(record["generation"])
                result["artifacts"] = {
                    "generation_manifest": str(
                        selection.root.parent.relative_to(Path(self.builder.state))
                        / "manifest.json"
                    ),
                    "generation_inventory_digest": "sha256:"
                    + identity(selection.manifest["outputs"]),
                }
                result["provenance"] = {
                    key: selection.manifest[key]
                    for key in ("build_record", "verification_execution")
                    if key in selection.manifest
                }
                if record.get("observation_snapshot"):
                    result["provenance"]["observation_snapshot"] = record[
                        "observation_snapshot"
                    ]
                    result["provenance"]["build_trace"] = {
                        "snapshot": record["observation_snapshot"]
                    }
            except Exception:
                result["missing_evidence"].append(
                    {"kind": "generation", "locator": record["generation"]}
                )
        return result

    def _base_result(
        self,
        request,
        *,
        status,
        terminal_outcome,
        uncertainty=False,
        failure=None,
        missing_evidence=None,
        allowed_next_operations=None,
        pipeline_id=None,
    ):
        return {
            "schema": RESULT_SCHEMA,
            "operation_id": request["operation_id"],
            "operation_type": request["operation"],
            "source_repository": request["source"]["repository"],
            "source_revision": request["source"]["revision"],
            "recipe_identity": None,
            "pipeline_id": pipeline_id,
            "attempt_ids": [],
            "selected_generation": None,
            "package": None,
            "stage": None,
            "phase": None,
            "status": status,
            "terminal_outcome": terminal_outcome,
            "failure": failure,
            "controller_jobs": [],
            "log_locators": [],
            "artifacts": {},
            "provenance": {},
            "uncertainty": bool(uncertainty),
            "missing_evidence": list(missing_evidence or [])[:MAX_MISSING],
            "allowed_next_operations": list(allowed_next_operations or []),
            "predecessor": request.get("predecessor"),
        }

    def _recipe_validate(self, request):
        from .pins import validate
        packages = load_packages(self.builder.package_dir)
        pin = validate(self.builder.package_dir, packages)
        package = request["arguments"].get("package")
        if set(request["arguments"]) - {"package"}:
            raise ImageBuildError("recipe validation accepts only package")
        if package is not None:
            value = self._recipe(package)
            packages = {package: value}
        result = self._base_result(
            request,
            status="completed",
            terminal_outcome="success",
            allowed_next_operations=[],
        )
        result["artifacts"] = {
            "pin_identity": "sha256:" + identity(pin),
            "packages": {
                name: {"recipe_identity": value.fingerprint}
                for name, value in sorted(packages.items())
            },
        }
        return result

    def _package_inspect(self, request):
        if set(request["arguments"]) != {"package"}:
            raise ImageBuildError("package inspection requires package")
        package = self._recipe(request["arguments"]["package"])
        result = self._base_result(
            request,
            status="completed",
            terminal_outcome="success",
        )
        result["package"] = package.name
        result["recipe_identity"] = package.fingerprint
        result["artifacts"] = {
            "sources": list(package.sources),
            "build_dependencies": list(package.build_dependencies),
            "runtime_dependencies": list(package.runtime_dependencies),
            "test_dependencies": list(package.test_dependencies),
            "outputs": list(package.outputs),
            "output_trees": list(package.output_trees),
            "licensing": package.licensing,
            "source_provenance": package.source_provenance,
        }
        return result

    def _dependencies(self, request):
        arguments = request["arguments"]
        if set(arguments) not in ({"targets"}, {"targets", "runtime_only"}):
            raise ImageBuildError("dependency resolution requires targets")
        packages = load_packages(self.builder.package_dir)
        targets = list(names(arguments["targets"]))
        resolved = order(
            packages,
            targets,
            runtime_only=arguments.get("runtime_only", False) is True,
        )
        result = self._base_result(
            request,
            status="completed",
            terminal_outcome="success",
        )
        result["artifacts"] = {"targets": targets, "dependency_order": list(resolved)}
        return result

    def _pipeline_submit(self, request, directory):
        pipeline_id = self._prepare_pipeline(request, directory)
        try:
            self.builder.resume(pipeline_id)
            raised = None
        except BaseException as error:
            raised = error
        return self._pipeline_summary(request, pipeline_id, raised=raised)

    def _pipeline_inspect(self, request):
        if set(request["arguments"]) != {"pipeline_id"}:
            raise ImageBuildError("pipeline inspection requires pipeline_id")
        return self._pipeline_summary(request, request["arguments"]["pipeline_id"])

    def _owned_pipeline(self, pipeline_id, action):
        record = self.builder.inspect_pipeline(pipeline_id)
        owner = self._pipeline_owner(record)
        if (
            owner is None
            or owner.get("contract") != REQUEST_SCHEMA
            or owner.get("source_revision") != self.source_revision
            or owner.get("source_repository") != self.source_repository
        ):
            raise ImageBuildError(
                "remote " + action
                + " requires the originally bound deployed source revision"
            )
        return record

    def _pipeline_resume(self, request):
        if set(request["arguments"]) != {"pipeline_id"}:
            raise ImageBuildError("pipeline resume requires pipeline_id")
        pipeline_id = request["arguments"]["pipeline_id"]
        self._owned_pipeline(pipeline_id, "resume")
        try:
            self.builder.resume(pipeline_id)
            raised = None
        except BaseException as error:
            raised = error
        return self._pipeline_summary(request, pipeline_id, raised=raised)

    def _cancel_pipeline_jobs(self, record):
        checkpoints = []
        for attempt in self._attempt_paths(record):
            if attempt.exists():
                checkpoints.extend(sorted(attempt.rglob("*.controller.json")))
        if not checkpoints:
            return
        execute = getattr(self.builder.runner, "execute", None)
        control = getattr(execute, "control", None)
        if control is None:
            raise ImageBuildError(
                "pipeline cancellation requires configured box-control execution"
            )
        from .box_control_adapter import BuildExecutionPending
        from .trace_records import capture_observation

        for checkpoint in checkpoints:
            try:
                saved = json.loads(checkpoint.read_text())
                job_id = saved["job_id"]
            except (OSError, KeyError, ValueError, TypeError) as error:
                raise ImageBuildError(
                    "invalid retained controller checkpoint during cancellation"
                ) from error
            observed = control.refresh_build_job(job_id)
            capture_observation(checkpoint, observed)
            if not observed.get("process_cleanup_complete"):
                observed = control.cancel_build_job(job_id)
                capture_observation(checkpoint, observed)
            if not observed.get("process_cleanup_complete"):
                raise BuildExecutionPending(observed)

    def _pipeline_cancel(self, request, directory):
        if set(request["arguments"]) != {"pipeline_id"}:
            raise ImageBuildError("pipeline cancellation requires pipeline_id")
        pipeline_id = request["arguments"]["pipeline_id"]
        record = self._owned_pipeline(pipeline_id, "cancellation")
        summary = self._pipeline_summary(request, pipeline_id)
        if summary["status"] in {"completed", "released"}:
            return summary
        if summary["status"] == "failed" and not summary["uncertainty"]:
            raise ImageBuildError(
                "terminal failed pipeline requires retry or inspection, not cancellation"
            )

        binding = self._binding(directory)
        if binding is None:
            binding = self._write_binding(
                directory,
                {"pipeline_id": pipeline_id, "phase": "cancel-jobs"},
            )
        elif binding.get("pipeline_id") != pipeline_id:
            raise ImageBuildError("remote cancellation pipeline identity changed")

        if binding.get("phase") == "cancel-jobs":
            self._cancel_pipeline_jobs(record)
            binding = {"pipeline_id": pipeline_id, "phase": "release"}
            write_json(directory / "binding.json", binding)
        if binding.get("phase") == "release":
            self.builder.release_pipeline(pipeline_id)
            binding = {"pipeline_id": pipeline_id, "phase": "complete"}
            write_json(directory / "binding.json", binding)
        if binding.get("phase") != "complete":
            raise ImageBuildError("invalid retained pipeline cancellation phase")
        return self._pipeline_summary(request, pipeline_id)

    def _predecessor_pipeline(self, request):
        predecessor = request.get("predecessor")
        if predecessor is None:
            raise ImageBuildError("retry requires predecessor remote operation")
        directory = self._directory(predecessor)
        binding = self._binding(directory)
        if not binding or not binding.get("pipeline_id"):
            raise ImageBuildError("predecessor has no retained pipeline identity")
        prior_request = json.loads((directory / "request.json").read_text())
        summary = self._pipeline_summary(
            prior_request,
            binding["pipeline_id"],
        )
        return binding["pipeline_id"], summary

    def _pipeline_retry(self, request, directory):
        binding = self._binding(directory)
        if binding is None:
            predecessor_pipeline, summary = self._predecessor_pipeline(request)
            if summary["status"] != "failed" or summary["uncertainty"]:
                raise ImageBuildError(
                    "retry requires a terminal failed predecessor with resolved outcome"
                )
            binding = self._write_binding(
                directory,
                {
                    "predecessor_pipeline_id": predecessor_pipeline,
                    "phase": "release-predecessor",
                },
            )
        predecessor_pipeline = binding["predecessor_pipeline_id"]
        if binding["phase"] == "release-predecessor":
            self.builder.release_pipeline(predecessor_pipeline)
            binding = {
                "predecessor_pipeline_id": predecessor_pipeline,
                "phase": "prepare-retry",
            }
            write_json(directory / "binding.json", binding)
        if binding["phase"] == "prepare-retry":
            recovered = self._find_owned_pipeline(request)
            if recovered is None:
                mode, selection, arguments = self._pipeline_arguments(request)
                record = self.builder.prepare_pipeline(
                    mode,
                    selection,
                    owner=self._owner(request),
                    **arguments,
                )
                pipeline_id = record["pipeline_id"]
            else:
                pipeline_id = recovered["pipeline_id"]
            binding = {
                "predecessor_pipeline_id": predecessor_pipeline,
                "phase": "run-retry",
                "pipeline_id": pipeline_id,
            }
            write_json(directory / "binding.json", binding)
        pipeline_id = binding["pipeline_id"]
        try:
            self.builder.resume(pipeline_id)
            raised = None
        except BaseException as error:
            raised = error
        return self._pipeline_summary(request, pipeline_id, raised=raised)

    def _generation_inspect(self, request):
        if set(request["arguments"]) != {"generation"}:
            raise ImageBuildError("generation inspection requires generation")
        selection = self._generation(request["arguments"]["generation"])
        result = self._base_result(
            request,
            status="completed",
            terminal_outcome="success",
        )
        result["selected_generation"] = selection.generation
        generation_inventory = selection.manifest["outputs"]
        result["artifacts"] = {
            "kind": selection.manifest["kind"],
            "generation_manifest": str(
                selection.root.parent.relative_to(Path(self.builder.state))
                / "manifest.json"
            ),
            "inventory": generation_inventory[:MAX_INVENTORY_ITEMS],
            "inventory_count": len(generation_inventory),
            "inventory_truncated": len(generation_inventory) > MAX_INVENTORY_ITEMS,
            "inventory_digest": "sha256:" + identity(generation_inventory),
        }
        result["provenance"] = {
            key: selection.manifest[key]
            for key in (
                "build_record",
                "verification_execution",
                "source_built",
                "self_hosted",
            )
            if key in selection.manifest
        }
        if (
            self.builder.provenance is not None
            and self.builder.provenance.generation_contract
        ):
            try:
                snapshot = self.builder.selected_observation_snapshot(
                    selection.generation
                )
            except Exception:
                result["missing_evidence"].append(
                    {
                        "kind": "observation-snapshot",
                        "locator": selection.generation,
                    }
                )
            else:
                if snapshot is None:
                    result["missing_evidence"].append(
                        {
                            "kind": "observation-snapshot",
                            "locator": selection.generation,
                        }
                    )
                else:
                    result["provenance"]["observation_snapshot"] = snapshot
                    result["provenance"]["build_trace"] = {
                        "snapshot": snapshot["snapshot"]
                    }
        return result

    def _diagnostic_definition(self, name):
        if not isinstance(name, str) or not _DIAGNOSTIC.fullmatch(name):
            raise ImageBuildError("invalid diagnostic identity")
        root = self.repository_root / "project" / "diagnostic" / name
        declaration = root / "diagnostic.json"
        if root.is_symlink() or declaration.is_symlink():
            raise ImageBuildError("diagnostic definition must not be a symlink")
        try:
            value = json.loads(declaration.read_text())
        except (OSError, ValueError, TypeError) as error:
            raise ImageBuildError("invalid diagnostic declaration") from error
        required = {
            "schema",
            "script",
            "interpreter",
            "timeout_seconds",
            "memory_maximum_bytes",
            "thread_count_maximum",
            "cpu_weight",
            "output_limit_bytes",
            "outputs",
        }
        if not isinstance(value, dict) or set(value) != required or value["schema"] != 1:
            raise ImageBuildError("unsupported diagnostic declaration")
        script = _relative(value["script"], "diagnostic script")
        if not script.endswith(".py"):
            raise ImageBuildError("diagnostic script must be Python source")
        source = root / script
        if source.is_symlink() or not source.is_file() or source.stat().st_size > 256 * 1024:
            raise ImageBuildError("diagnostic script is missing, unsafe, or too large")
        interpreter = value["interpreter"]
        if (
            not isinstance(interpreter, str)
            or not interpreter.startswith("/")
            or ".." in PurePosixPath(interpreter).parts
            or "\0" in interpreter
        ):
            raise ImageBuildError("diagnostic interpreter must be an absolute guest path")
        for key, maximum in (
            ("timeout_seconds", 3600),
            ("memory_maximum_bytes", 2**63 - 1),
            ("thread_count_maximum", 2**31 - 1),
            ("output_limit_bytes", 1024**3),
        ):
            if type(value[key]) is not int or not 1 <= value[key] <= maximum:
                raise ImageBuildError("invalid diagnostic " + key)
        if type(value["cpu_weight"]) is not int or not 1 <= value["cpu_weight"] <= 10000:
            raise ImageBuildError("diagnostic cpu_weight must be 1..10000")
        if (
            not isinstance(value["outputs"], list)
            or len(value["outputs"]) > 32
            or len(set(value["outputs"])) != len(value["outputs"])
        ):
            raise ImageBuildError("invalid diagnostic outputs")
        outputs = [_relative(item, "diagnostic output") for item in value["outputs"]]
        return root, dict(value, script=script, outputs=outputs), source

    def _diagnostic_binding(self, request, directory):
        binding = self._binding(directory)
        if binding is not None:
            return binding
        arguments = request["arguments"]
        if set(arguments) != {"diagnostic", "generation", "argv"}:
            raise ImageBuildError(
                "diagnostic submission requires diagnostic, generation, and argv"
            )
        argv = arguments["argv"]
        if (
            not isinstance(argv, list)
            or len(argv) > 64
            or any(
                not isinstance(value, str)
                or "\0" in value
                or len(value) > 4096
                for value in argv
            )
        ):
            raise ImageBuildError("invalid diagnostic argument vector")
        selection = self._generation(arguments["generation"])
        definition_root, definition, script = self._diagnostic_definition(
            arguments["diagnostic"]
        )
        attempt = (
            Path(self.builder.state)
            / "image-build"
            / "attempts"
            / ("diagnostic-" + request["operation_id"])
        )
        ensure_directory(attempt)
        root = attempt / "root"
        source = attempt / "source"
        output = attempt / "output"
        if not (attempt / "diagnostic-binding.json").exists():
            if root.exists() or source.exists() or output.exists():
                raise ImageBuildError("partial diagnostic staging exists without binding")
            shutil.copytree(selection.root, root, symlinks=True)
            source.mkdir()
            output.mkdir()
            target = source / definition["script"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(script, target)
            prepared = {
                "root": inventory(root),
                "binding": {
                    "contract": DIAGNOSTIC_SCHEMA,
                    "source_revision": self.source_revision,
                    "generation": selection.generation,
                    "diagnostic": arguments["diagnostic"],
                    "script_sha256": _sha256(script),
                },
            }
            write_json(attempt / "prepared.json", prepared)
            diagnostic_binding = {
                "schema": 1,
                "attempt_id": attempt.name,
                "generation": selection.generation,
                "diagnostic": arguments["diagnostic"],
                "script": definition["script"],
                "script_sha256": _sha256(script),
                "argv": argv,
                "definition": definition,
            }
            write_json(attempt / "diagnostic-binding.json", diagnostic_binding)
            write_json(
                attempt / "status.json",
                {
                    "status": "running",
                    "kind": "diagnostic",
                    "remote_operation_id": request["operation_id"],
                },
            )
        diagnostic_binding = json.loads(
            (attempt / "diagnostic-binding.json").read_text()
        )
        binding = {
            "attempt_id": attempt.name,
            "diagnostic": diagnostic_binding,
        }
        self._write_binding(directory, binding)
        return binding

    def _diagnostic_result(self, request, binding, *, refresh):
        attempt = (
            Path(self.builder.state)
            / "image-build"
            / "attempts"
            / binding["attempt_id"]
        )
        diagnostic = binding["diagnostic"]
        definition = diagnostic["definition"]
        checkpoint = attempt / "diagnostic.controller.json"
        raised = None
        result = None
        if refresh:
            execute = getattr(self.builder.runner, "execute", None)
            if execute is None or not hasattr(execute, "execute_for_attempt"):
                raise ImageBuildError(
                    "diagnostics require configured box-control execution"
                )
            from .box_control_adapter import BoxControlExecutionAdapter
            from .configuration import input_manifest

            limits = {
                "thread-count-maximum": definition["thread_count_maximum"],
                "memory-maximum-bytes": definition["memory_maximum_bytes"],
                "cpu-weight": definition["cpu_weight"],
            }
            adapter = BoxControlExecutionAdapter(
                execute.control,
                execution_user_id=execute.execution_user_id,
                execution_group_id=execute.execution_group_id,
                startup_timeout_seconds=execute.startup_timeout_seconds,
                termination_grace_seconds=execute.termination_grace_seconds,
                wait_timeout_seconds=execute.wait_timeout_seconds,
                resource_limits=limits,
                input_manifest_id=input_manifest,
            )
            request_value = BuildExecutionRequest(
                root=attempt / "root",
                source=attempt / "source",
                output=attempt / "output",
                command=(
                    definition["interpreter"],
                    "/image-build/source/" + definition["script"],
                    *diagnostic["argv"],
                ),
                environment={
                    "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "HOME": "/tmp",
                    "IMAGE_BUILD_SOURCE": "/image-build/source",
                    "IMAGE_BUILD_OUTPUT": "/image-build/output",
                },
                working_directory="/image-build/source",
                timeout_seconds=definition["timeout_seconds"],
                read_only_root=True,
                network_access=False,
            )
            try:
                result = adapter.execute_for_attempt(request_value, checkpoint)
            except BaseException as error:
                raised = error
        observation = checkpoint.with_name("diagnostic.observation.json")
        record = None
        if observation.exists():
            try:
                record = json.loads(observation.read_text())
            except (OSError, ValueError, TypeError):
                record = None
        status = "pending"
        terminal = None
        uncertainty = False
        failure = None
        if result is not None:
            status = "completed" if result.exit_code == 0 else "failed"
            terminal = "success" if result.exit_code == 0 else "nonzero-exit"
        elif record and record.get("outcome") in {
            "nonzero-exit",
            "signal",
            "timeout",
            "fault",
            "cancelled",
        }:
            status = "failed"
            terminal = record["outcome"]
            failure = {
                "type": "controller-outcome",
                "reason": record.get("error"),
                "job_id": record.get("job_id"),
            }
        elif record and record.get("outcome") == "unknown":
            uncertainty = True
            failure = {"type": "unknown-controller-outcome", "reason": record.get("error")}
        elif raised is not None:
            failure = {"type": type(raised).__name__, "reason": str(raised)}
            uncertainty = "unknown" in str(raised).lower()
        outputs = []
        total = 0
        for relative in definition["outputs"]:
            path = attempt / "output" / relative
            if path.is_symlink():
                failure = {"type": "unsafe-output", "reason": relative}
                status = "failed"
                terminal = "invalid-output"
                break
            if path.is_file():
                size = path.stat().st_size
                total += size
                outputs.append(
                    {
                        "path": relative,
                        "bytes": size,
                        "sha256": _sha256(path),
                    }
                )
        if total > definition["output_limit_bytes"]:
            status = "failed"
            terminal = "output-limit"
            failure = {
                "type": "output-limit",
                "reason": f"{total} bytes exceeds {definition['output_limit_bytes']}",
            }
        if status in {"completed", "failed"}:
            write_json(
                attempt / "status.json",
                {
                    "status": "complete" if status == "completed" else "failed",
                    "kind": "diagnostic",
                    "remote_operation_id": request["operation_id"],
                },
            )
        result_value = self._base_result(
            request,
            status=status,
            terminal_outcome=terminal,
            uncertainty=uncertainty,
            failure=failure,
            allowed_next_operations=(
                ["diagnostic.inspect"]
                if status == "completed"
                else (
                    ["diagnostic.inspect", "diagnostic.submit"]
                    if status == "failed"
                    else ["diagnostic.submit", "diagnostic.inspect"]
                )
            ),
        )
        result_value["attempt_ids"] = [attempt.name]
        result_value["selected_generation"] = diagnostic["generation"]
        result_value["stage"] = "diagnostic"
        result_value["phase"] = diagnostic["diagnostic"]
        result_value["artifacts"] = {
            "script_sha256": diagnostic["script_sha256"],
            "outputs": outputs,
            "output_directory": str(
                (attempt / "output").relative_to(Path(self.builder.state))
            ),
        }
        if checkpoint.exists():
            try:
                saved = json.loads(checkpoint.read_text())
                result_value["controller_jobs"] = [
                    {
                        "job_id": saved.get("job_id"),
                        "request_id": saved.get("request_id"),
                        "attempt_id": attempt.name,
                        "package": "diagnostic",
                        "stage": "diagnostic",
                        "phase": diagnostic["diagnostic"],
                        "command_index": 0,
                        "command_key": "diagnostic",
                    }
                ]
            except Exception:
                result_value["missing_evidence"].append(
                    {"kind": "diagnostic-checkpoint", "locator": str(checkpoint)}
                )
        return result_value

    def _diagnostic_submit(self, request, directory):
        binding = self._diagnostic_binding(request, directory)
        return self._diagnostic_result(request, binding, refresh=True)

    def _diagnostic_inspect(self, request):
        if set(request["arguments"]) != {"operation_id"}:
            raise ImageBuildError("diagnostic inspection requires operation_id")
        target = self._directory(request["arguments"]["operation_id"])
        binding = self._binding(target)
        if not binding or not binding.get("attempt_id"):
            raise ImageBuildError("diagnostic operation has no retained attempt")
        return self._diagnostic_result(request, binding, refresh=False)

    def execute(self, raw):
        request = self._validate_request(raw)
        directory = self._directory(request["operation_id"])
        ensure_directory(directory)
        # Duplicate callers for one durable operation identity serialize before
        # request/binding creation. Different operation identities may inspect in
        # parallel; image-build's state-local lock still serializes pipeline mutation.
        with (directory / "operation.lock").open("a+") as operation_lock:
            fcntl.flock(operation_lock, fcntl.LOCK_EX)
            directory = self._save_request(request)
            operation = request["operation"]
            try:
                if operation == "recipe.validate":
                    result = self._recipe_validate(request)
                elif operation == "package.inspect":
                    result = self._package_inspect(request)
                elif operation == "dependencies.resolve":
                    result = self._dependencies(request)
                elif operation == "pipeline.submit":
                    result = self._pipeline_submit(request, directory)
                elif operation == "pipeline.inspect":
                    result = self._pipeline_inspect(request)
                elif operation == "pipeline.resume":
                    result = self._pipeline_resume(request)
                elif operation == "pipeline.cancel":
                    result = self._pipeline_cancel(request, directory)
                elif operation == "pipeline.retry":
                    result = self._pipeline_retry(request, directory)
                elif operation == "generation.inspect":
                    result = self._generation_inspect(request)
                elif operation == "diagnostic.submit":
                    result = self._diagnostic_submit(request, directory)
                else:
                    result = self._diagnostic_inspect(request)
            except BaseException as error:
                if isinstance(error, (KeyboardInterrupt, SystemExit)):
                    raise
                result = self._base_result(
                    request,
                    status="failed",
                    terminal_outcome="request-error",
                    failure={"type": type(error).__name__, "reason": str(error)},
                    allowed_next_operations=[],
                )
            return self._write_result(directory, result)


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--package-dir", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--controller-config", type=Path)
    parser.add_argument("--source-mirror-config", type=Path)
    parser.add_argument("--provenance-host-id")
    parser.add_argument("--provenance-project-id")
    parser.add_argument("--expected-pin-digest")
    parser.add_argument("request", type=Path)
    args = parser.parse_args()

    runner = None
    if args.controller_config is not None:
        from .configuration import configured_runner

        runner = configured_runner(args.controller_config, args.state_dir)
    source_mirror = None
    if args.source_mirror_config is not None:
        from .archive_mirror import configured_source_mirror

        source_mirror = configured_source_mirror(args.source_mirror_config)
    provenance = None
    if (args.provenance_host_id is None) != (args.provenance_project_id is None):
        raise SystemExit("provenance host/project identities must be supplied together")
    if args.expected_pin_digest is not None and args.provenance_host_id is None:
        raise SystemExit("expected pin digest requires provenance capture")
    if args.provenance_host_id is not None:
        from .provenance import Provenance
        pin_path = args.package_dir / "commit-pin.py"
        try:
            repository_path = pin_path.resolve().relative_to(
                args.repository_root.resolve()
            ).as_posix()
        except ValueError as error:
            raise SystemExit("monthly pin must be inside the deployed repository") from error
        pin = Provenance.capture_pin(
            args.state_dir,
            pin_path,
            repository=args.source_repository,
            revision=args.source_revision,
            repository_path=repository_path,
        )
        if args.expected_pin_digest is not None and pin["digest"] != args.expected_pin_digest:
            raise SystemExit("deployed monthly pin digest differs from lane binding")
        provenance = Provenance(
            args.state_dir,
            host_id=args.provenance_host_id,
            project_id=args.provenance_project_id,
            pin=pin,
        )
    from .engine import ImageBuild

    builder = ImageBuild(
        package_dir=args.package_dir,
        state_dir=args.state_dir,
        runner=runner,
        source_mirror=source_mirror,
        provenance=provenance,
    )
    adapter = RemoteOperations(
        builder,
        repository_root=args.repository_root,
        source_repository=args.source_repository,
        source_revision=args.source_revision,
    )
    result = adapter.execute(json.loads(args.request.read_text()))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
