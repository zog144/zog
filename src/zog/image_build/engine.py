import logging
"""Source builds and staged toolchain promotion. No RPM imports or host installation."""

import fcntl
import json
import os
import platform
import shutil
import uuid
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from .errors import ImageBuildError
from .filesystem import inventory, merge, sync_directory, sync_tree, write_json, ensure_directory, discard_staging
from .metadata import identity, load_packages, order
from .runner import BoxControlRunner
from .sources import stage
from .pipeline import PipelineMixin
from .artifacts import restore as restore_artifact
from .info_index import POLICY as INFO_INDEX_POLICY

SCHEMA = 2


@dataclass(frozen=True)
class ImageSelection:
    generation: str
    root: Path
    manifest: dict
    reused: bool = False


def read_selection(directory):
    directory = Path(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text())
        if manifest["schema"] != SCHEMA or manifest["generation"] != directory.name:
            raise ImageBuildError("unsupported or mismatched generation manifest")
        if manifest["kind"] != manifest["inputs"]["kind"]:
            raise ImageBuildError("generation kind mismatch")
        if manifest["kind"] == "toolchain" and (
            manifest.get("stage") != manifest["inputs"]["stage"]
            or manifest.get("self_hosted") != (manifest["inputs"]["stage"] == 2)
        ):
            raise ImageBuildError("toolchain stage mismatch")
        if identity(manifest["inputs"]) != manifest["generation"]:
            raise ImageBuildError("generation input identity mismatch")
        if inventory(directory / "root") != manifest["outputs"]:
            raise ImageBuildError(f"generation outputs changed: {directory}")
        return ImageSelection(directory.name, directory / "root", manifest, True)
    except (OSError, KeyError, ValueError, TypeError) as error:
        raise ImageBuildError(f"invalid generation {directory}: {error}") from error


class ImageBuild(PipelineMixin):
    def __init__(self, *, package_dir, state_dir, runner=None, maximum_generations=10, dependency_replacements=None, provenance=None, source_mirror=None):
        self.package_dir, self.state = Path(package_dir), Path(state_dir)
        self.runner = runner or BoxControlRunner()
        self.provenance = provenance
        if source_mirror is None:
            from .archive_mirror import source_mirror_from_environment
            source_mirror = source_mirror_from_environment()
        self.source_mirror = source_mirror
        self.maximum_generations = maximum_generations
        self.dependency_replacements = json.loads(json.dumps(dependency_replacements or {}))
        from .metadata import names
        names(list(self.dependency_replacements))
        for record in self.dependency_replacements.values():
            if (record['identity'] != identity({'inputs': record['inputs'], 'outputs': record['outputs']})
                    or not record['outputs'] or any(r['path'] != 'sysroot' and not r['path'].startswith('sysroot/')
                                                   for r in record['outputs'])):
                raise ImageBuildError('invalid bootstrap dependency replacement ownership')
        ensure_directory(self.state)

    @contextmanager
    def locked(self):
        with (self.state / "image-build.lock").open("a+") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _candidate(self, kind):
        if getattr(self, "_pipeline_path", None) is not None:
            return self._pipeline_candidate(kind)
        # A lost caller must not silently create another command attempt. The
        # adapter resumes the recorded command; whole-pipeline continuation is explicit.
        for status_path in (self.state / "image-build" / "attempts").glob("*/status.json"):
            prior = json.loads(status_path.read_text())
            if prior.get("status") in {"running", "pending"}:
                raise ImageBuildError(f"unfinished attempt {status_path.parent}; resume its recorded controller checkpoint before starting another")
        path = self.state / "image-build" / "attempts" / (kind + "-" + uuid.uuid4().hex)
        path.mkdir(parents=True)
        write_json(path / "status.json", {"status": "running", "kind": kind})
        return path

    def _verify_generation(self, selection, *, repair_indexes=True):
        if self.provenance and self.provenance.generation_contract:
            from .generation_provenance import verify, index
            bundle = verify(self.provenance, selection)
            if repair_indexes:
                # Replay the namespace durability barriers after a lost rename response.
                sync_directory(selection.root.parent)
                sync_directory(selection.root.parent.parent)
                publication = self.state / 'image-build/publication'
                if publication.exists():
                    sync_directory(publication)
                index(self.provenance, selection, bundle)
        return selection

    def _publish_observation_snapshot(self, selection, *, refresh=False, readelf="readelf"):
        if not (self.provenance and self.provenance.generation_contract):
            return None
        from .observation_snapshots import publish
        return publish(
            self.provenance, selection, refresh=refresh, readelf=readelf
        )

    def publish_observation_snapshot(self, selection, *, readelf="readelf"):
        """Explicitly publish/select the current retained observation set."""
        if not (self.provenance and self.provenance.generation_contract):
            raise ImageBuildError(
                "observation snapshots require canonical generation provenance"
            )
        with self.locked():
            if not isinstance(selection, ImageSelection):
                selection = read_selection(selection)
            self._verify_generation(selection)
            return self._publish_observation_snapshot(
                selection, refresh=True, readelf=readelf
            )

    def selected_observation_snapshot(self, generation):
        """Return the exact owner-selected canonical snapshot for a generation."""
        if not (self.provenance and self.provenance.generation_contract):
            raise ImageBuildError(
                "observation snapshots require canonical generation provenance"
            )
        from .observation_snapshots import selected
        with self.locked():
            return selected(self.provenance, generation)

    def observation_snapshots(self, generation=None, *, limit=100):
        """List owner-published snapshots without scanning the canonical store."""
        if not (self.provenance and self.provenance.generation_contract):
            raise ImageBuildError(
                "observation snapshots require canonical generation provenance"
            )
        from .observation_snapshots import publications
        with self.locked():
            return publications(self.provenance, generation, limit=limit)

    def _publish(self, root, inputs, kind, details):
        # Reject a producer contract mismatch before publishing unreadable state.
        if inputs.get('kind') != kind:
            raise ImageBuildError('generation publication kind mismatch')
        if kind == 'toolchain' and (
            type(inputs.get('stage')) is not int
            or details.get('stage') != inputs['stage']
            or details.get('self_hosted') != (inputs['stage'] == 2)
        ):
            raise ImageBuildError('generation publication stage mismatch')
        fingerprint = identity(inputs)
        store = self.state / "image-build" / "generations"
        ensure_directory(store)
        target = store / fingerprint
        if self.provenance and self.provenance.generation_contract and kind != 'host-bootstrap' and 'build_record' not in details:
            raise ImageBuildError('canonical generation producer is required for this publication')
        if target.exists():
            existing = read_selection(target)
            if self.provenance and self.provenance.generation_contract and kind != 'host-bootstrap':
                self._verify_generation(existing)
                if existing.manifest['build_record'] != details['build_record']:
                    raise ImageBuildError('existing generation has a different producing graph')
                self._publish_observation_snapshot(existing)
            return existing
        if sum(p.is_dir() for p in store.iterdir()) >= self.maximum_generations:
            raise ImageBuildError(
                "generation capacity reached; box-control must reclaim unused generations"
            )
        pending = store.parent / "publication" / uuid.uuid4().hex
        ensure_directory(pending)
        shutil.copytree(root, pending / "root", symlinks=True)
        manifest = {
            "schema": SCHEMA,
            "generation": fingerprint,
            "kind": kind,
            "inputs": inputs,
            "outputs": inventory(pending / "root"),
            **details,
        }
        if self.provenance and self.provenance.generation_contract and kind != 'host-bootstrap':
            self._verify_generation(ImageSelection(fingerprint, pending / 'root', manifest), repair_indexes=False)
        write_json(pending / "manifest.json", manifest)
        sync_tree(pending)
        os.rename(pending, target)
        sync_directory(store)
        sync_directory(pending.parent)
        selection = ImageSelection(fingerprint, target / "root", manifest)
        if self.provenance and self.provenance.generation_contract and kind != 'host-bootstrap':
            self._verify_generation(selection)
            self._publish_observation_snapshot(selection)
        return selection

    def _activate(self, selection, name):
        self._verify_generation(selection)
        directory = self.state / "image-build"
        temporary = directory / (name + ".pending")
        temporary.unlink(missing_ok=True)
        temporary.symlink_to(Path("generations") / selection.generation)
        os.replace(temporary, directory / name)
        sync_directory(directory)

    def import_bootstrap(self, root, host):
        """Host assembly remains developer tooling; import snapshots its explicit inventory."""
        with self.locked():
            root = Path(root)
            outputs = inventory(root)
            if not outputs:
                raise ImageBuildError("empty host bootstrap")
            inputs = {
                "schema": SCHEMA,
                "kind": "host-bootstrap",
                "host": host,
                "files": outputs,
                "architecture": platform.machine(),
            }
            selection = self._publish(root, inputs, "host-bootstrap", {"host": host})
            if selection.manifest["outputs"] != outputs:
                raise ImageBuildError("host bootstrap changed while being imported")
            return selection

    def _build_set(self, packages, targets, toolchain, attempt):
        from .cleanup import package_workspace
        built = {}
        for name in order(packages, targets):
            package = packages[name]
            dependencies = order(
                packages,
                list(dict.fromkeys(package.build_dependencies + package.runtime_dependencies + package.test_dependencies)),
                runtime_only=True,
            )
            inputs = {
                "schema": SCHEMA,
                "package": package.fingerprint,
                "toolchain": toolchain.generation,
                "dependencies": {n: built[n]["identity"] for n in dependencies},
                "architecture": platform.machine(),
            }
            replacements = {n: self.dependency_replacements[n]['identity'] for n in dependencies if n in self.dependency_replacements}
            if replacements:
                inputs['dependency_replacements'] = replacements
            if package.licensing is not None:
                inputs['license_identity'] = identity(package.licensing)
            if dependencies:
                inputs['composition_policy'] = INFO_INDEX_POLICY
            package_dir = attempt / "packages" / name
            output = package_dir / "output"
            result_path = package_dir / "result.json"
            if not result_path.exists() and not (package_dir / "prepared.json").exists():
                restore_artifact(self, inputs, package_dir)
            if result_path.exists():
                result = json.loads(result_path.read_text())
                if result["inputs"] != inputs or result["outputs"] != inventory(output):
                    raise ImageBuildError(f"recorded package outputs changed: {name}")
                if self.provenance and (package_dir/'provenance.json').exists():
                    provenance_binding=self.provenance.finish(package_dir,result=result)
                    result=dict(result,provenance={'output':provenance_binding['output'],'result':provenance_binding['result']})
                elif self.provenance:
                    if 'provenance' not in result:
                        if any((package_dir / f'provenance-{phase}.json').exists() for phase in ('preparing', 'finalizing')):
                            raise ImageBuildError('known package provenance pointer is missing')
                        result=dict(result,provenance=self.provenance.legacy_output(name,result))
                if self.provenance:
                    self.provenance.verify_output(result['provenance'], name, result)
                self._release_resources(package_dir)
                from .test_fixtures import release as release_test_fixtures
                release_test_fixtures(self,package_dir)
                package_workspace(package_dir)
                built[name] = {**result, "root": output}
                continue
            prepared = package_dir / "prepared.json"
            if not prepared.exists():
                if (package_dir / "controller-resources.json").exists():
                    raise ImageBuildError("unrecorded preparation with controller resources")
                if package_dir.exists():
                    discard_staging(package_dir)
                ensure_directory(package_dir)
                environment = package_dir / "root"
                shutil.copytree(toolchain.root, environment, symlinks=True)
                for dependency in dependencies:
                    if dependency in self.dependency_replacements:
                        from .native import remove_owned
                        remove_owned(environment, self.dependency_replacements[dependency]['outputs'])
                    merge(built[dependency]["root"], environment, preserve_existing_directories=True, compose_info=True)
                # Reserved mounts are created only in the disposable root.
                for reserved in (
                    "image-build",
                    "image-build/source",
                    "image-build/output",
                    "tmp",
                    "run",
                ):
                    location = environment / reserved
                    if location.is_symlink() or (
                        location.exists() and not location.is_dir()
                    ):
                        raise ImageBuildError(f"reserved build path conflict: {reserved}")
                    location.mkdir(exist_ok=True)
                source, output = package_dir / "source", package_dir / "output"
                acquisitions = stage(
                    package,
                    source,
                    self.state / "image-build" / "sources",
                    source_mirror=self.source_mirror,
                )
                write_json(
                    package_dir / "source-acquisition.json",
                    {"schema": 1, "sources": acquisitions},
                )
                from .licensing import prepare_readability
                write_json(package_dir / "license-readability.json", {
                    "schema": 1, "policy": "declared-notice-read-bits-v1",
                    "changes": prepare_readability(package, source)})
                output.mkdir()
                sync_tree(package_dir)
                write_json(prepared, {"inputs": inputs, "root": inventory(environment)})
            else:
                recorded = json.loads(prepared.read_text())
                if recorded["inputs"] != inputs or recorded["root"] != inventory(package_dir / "root"):
                    raise ImageBuildError("prepared package inputs changed")
                environment, source = package_dir / "root", package_dir / "source"
            if self.provenance:
                provenance_binding=self.provenance.prepare(self,package,package_dir,attempt,inputs,toolchain,built,dependencies)
            command_directory=package_dir
            for phase, commands in package.steps.items():
                if phase=='test' and package.integration.get('test_fixtures'):
                    from .test_fixtures import prepare as prepare_test_fixtures
                    environment,command_directory=prepare_test_fixtures(self,package,package_dir)
                if commands:
                    logging.info("Package %s: %s", name, phase)
                for command_index, command in enumerate(commands):
                    write_json(command_directory / (phase + '-' + str(command_index) + '.view.json'), {
                        'schema': 1, 'attempt_id': attempt.name,
                        'pipeline_id': getattr(self, '_pipeline_record', {}).get('pipeline_id') if getattr(self, '_pipeline_record', None) else None,
                        'stage_id': package.integration.get('stage_id', 'package-build'),
                        'package': package.integration.get('project', name),
                        'phase': phase, 'command_index': command_index,
                        'command': list(command), 'checkpoint': phase + '-' + str(command_index) + '.controller.json',
                    })
                    from .trace_records import safe_capture_identity
                    log = command_directory / (phase + '-' + str(command_index) + '.log')
                    safe_capture_identity(log, attempt_id=attempt.name,
                        command_id=str(log.relative_to(attempt).with_suffix('')),
                        package=package.integration.get('project', name),
                        stage_id=package.integration.get('stage_id', 'package-build'),
                        phase=phase, command_index=command_index,
                        pipeline_id=(getattr(self, '_pipeline_record', None) or {}).get('pipeline_id'),
                        provenance={'recipe_identity': package.fingerprint,
                                    'pin_set_identity': (getattr(self, '_pipeline_record', None) or {}).get('source_pins'),
                                    'inputs': inputs, 'sources': list(package.sources),
                                    **({'build_record':{'prepared':provenance_binding['prepared'],
                                        'inputs':provenance_binding['inputs'],
                                        'owner_binding':str((package_dir/'provenance.json').relative_to(self.state/'image-build'))}} if self.provenance else {})})
                    try:
                        self.runner.run(
                            environment,
                            source,
                            output,
                            command,
                            package.environment,
                            command_directory / (phase + "-" + str(command_index) + ".log"),
                        )
                    except Exception as error:
                        if self.provenance:
                            self.provenance.command_failed(package_dir, log, error)
                        raise
            # All commands have completed. Controller release confirms process
            # cleanup and returns directory ownership to the orchestrator before
            # it creates notices. Regular files keep the build UID; new source
            # preparation makes declared notices readable across this handoff. Never chmod/chown a live build workspace here.
            if package.licensing is not None:
                from .licensing import prepare_finalization
                prepare_finalization(package, output, package_dir / "finalization.json", inputs)
                from .test_fixtures import release as release_test_fixtures
                release_test_fixtures(self, package_dir)
                self._release_resources(package_dir)
            # Preserve licensing evidence before successful workspace cleanup.
            from .licensing import preserve as preserve_licenses
            licensing = preserve_licenses(package, source, output, self.state)
            outputs = inventory(output)
            license_paths = set()
            if licensing:
                parent = str(Path(licensing['receipt']).parent)
                license_paths = {r['path'] for r in outputs if r['path'].startswith(parent + '/')}
            actual = tuple(r["path"] for r in outputs if r["kind"] != "directory" and r["path"] not in license_paths)
            missing = sorted(set(package.outputs) - set(actual))
            if package.output_trees:
                unexpected = sorted(path for path in actual if not any(
                    path == tree or path.startswith(tree + '/')
                    for tree in package.output_trees
                ))
            else:
                unexpected = sorted(set(actual) - set(package.outputs))
            if missing or unexpected:
                if self.provenance:
                    self.provenance.finish(package_dir,outcome='failed',summary='Package output inventory failed acceptance.')
                raise ImageBuildError(
                    f"{name}: produced files differ from produce-manifest; "
                    f"missing required paths: {missing}; "
                    f"paths outside allowed locations: {unexpected}; "
                    f"allowed trees/paths: {package.output_trees or package.outputs}"
                )
            logging.info("Package %s: complete", name)
            result = {
                "identity": identity({"inputs": inputs, "outputs": outputs}),
                "inputs": inputs,
                "outputs": outputs,
                "integration": package.integration,
            }
            if licensing: result["licensing"] = licensing
            sync_tree(output)
            write_json(package_dir / "result.json", result)
            if self.provenance:
                provenance_binding=self.provenance.finish(package_dir,result=result)
                result=dict(result,provenance={'output':provenance_binding['output'],'result':provenance_binding['result']})
            self._release_resources(package_dir)
            from .test_fixtures import release as release_test_fixtures
            release_test_fixtures(self,package_dir)
            package_workspace(package_dir)
            built[name] = {**result, "root": output}
        return built

    def _compose(self, packages, targets, built, root):
        composition = root.with_suffix(".composition.json")
        selected = order(packages, targets, runtime_only=True)
        binding = {"packages": {name: built[name]["identity"] for name in selected}, "composition_policy": INFO_INDEX_POLICY}
        if composition.exists():
            saved = json.loads(composition.read_text())
            if saved["inputs"] != binding or saved["outputs"] != inventory(root):
                raise ImageBuildError("recorded composition changed")
            return {name: {k: v for k, v in built[name].items() if k != "root"} for name in selected}
        if root.exists():
            discard_staging(root)
        root.mkdir()
        for name in selected:
            merge(built[name]["root"], root, compose_info=True)
        sync_tree(root)
        write_json(composition, {"inputs": binding, "outputs": inventory(root)})
        return {
            name: {k: v for k, v in built[name].items() if k != "root"}
            for name in selected
        }

    def _bootstrap(self, host_bootstrap, stages):
        """stages: reviewed targets for first toolchain, then its self-hosted rebuild.

        Each stage can use different explicitly staged package recipes to break
        compiler/libc bootstrap cycles. Stage two never receives stage-zero files.
        """
        if self.provenance and self.provenance.generation_contract:
            raise ImageBuildError('canonical bootstrap assembly requires a dedicated adapter')
        if len(stages) != 2 or not all(stages):
            raise ImageBuildError(
                "bootstrap requires exactly two nonempty source-build stages"
            )
        packages = load_packages(self.package_dir)
        current = read_selection(Path(host_bootstrap.root).parent)
        if current.manifest["kind"] != "host-bootstrap":
            raise ImageBuildError("bootstrap requires a recorded host bootstrap")
        if current.manifest["inputs"]["architecture"] != platform.machine():
            raise ImageBuildError("bootstrap architecture differs from this host")
        host_identity = current.generation
        for index, targets in enumerate(stages, 1):
            attempt = self._candidate("toolchain-stage-" + str(index))
            try:
                built = self._build_set(packages, targets, current, attempt)
                records = self._compose(
                    packages, targets, built, attempt / "composed"
                )
                # A smoke test is required before a source-built stage can be promoted.
                source, output = attempt / "probe-source", attempt / "probe-output"
                probe_ready = attempt / "probe-prepared.json"
                probe_done = attempt / "probe-complete.json"
                if not probe_ready.exists():
                    if (attempt / "controller-resources.json").exists():
                        raise ImageBuildError("unrecorded probe preparation")
                    for directory in (source, output, attempt / "probe-root"):
                        if directory.exists(): discard_staging(directory)
                    source.mkdir()
                    output.mkdir()
                    (source / "probe.c").write_text("int main(void) { return 0; }\n")
                    probe = attempt / "probe-root"
                    shutil.copytree(attempt / "composed", probe, symlinks=True)
                    for path in (
                        "image-build",
                        "image-build/source",
                        "image-build/output",
                        "tmp",
                        "run",
                    ):
                        if (probe / path).is_symlink():
                            raise ImageBuildError("reserved probe path is a symlink")
                        (probe / path).mkdir(exist_ok=True)
                    sync_tree(source)
                    sync_tree(output)
                    sync_tree(probe)
                    write_json(probe_ready, {"root": inventory(probe)})
                probe = attempt / "probe-root"
                if json.loads(probe_ready.read_text())["root"] != inventory(probe):
                    raise ImageBuildError("prepared probe root changed")
                if not probe_done.exists():
                    for command_index, command in enumerate((
                        ["cc", "probe.c", "-o", "/image-build/output/probe"],
                        ["/image-build/output/probe"],
                    )):
                        self.runner.run(
                            probe, source, output, command, {}, attempt / ("probe-" + str(command_index) + ".log")
                        )
                    sync_tree(output)
                    write_json(probe_done, {"outputs": inventory(output)})
                elif json.loads(probe_done.read_text())["outputs"] != inventory(output):
                    raise ImageBuildError("probe outputs changed")
                self._release_resources(attempt)
                inputs = {
                    "schema": SCHEMA,
                    "kind": "toolchain",
                    "composition_policy": INFO_INDEX_POLICY,
                    "stage": index,
                    "parent": current.generation,
                    "host_bootstrap": host_identity,
                    "targets": list(targets),
                    "architecture": platform.machine(),
                    "packages": {n: v["identity"] for n, v in built.items()},
                }
                current = self._publish(
                    attempt / "composed",
                    inputs,
                    "toolchain",
                    {
                        "stage": index,
                        "self_hosted": index == 2,
                        "packages": records,
                    },
                )
                write_json(
                    attempt / "status.json",
                    {"status": "complete", "generation": current.generation},
                )
            except BaseException as error:
                self._failed(attempt, error)
                raise
        self._activate(current, "toolchain-active")
        return current

    def _failed(self, attempt, error):
        from .box_control_adapter import BuildExecutionPending
        pending = isinstance(error, (BuildExecutionPending, KeyboardInterrupt, SystemExit))
        try:
            from zog.box_control.errors import PersistenceError
            pending = pending or isinstance(error, PersistenceError)
        except ImportError:
            pass

        # Never remove evidence or attempt automatic rollback after storage failures.
        try:
            write_json(
                attempt / "status.json",
                {
                    "status": "pending" if pending else "failed",
                    "error": str(error),
                    "traceback": "".join(
                        traceback.format_exception(
                            type(error), error, error.__traceback__
                        )
                    ),
                },
            )
        except OSError:
            pass

    def _ensure(self, targets, *, toolchain, seed_check=False, native_check=False):
        toolchain = read_selection(Path(toolchain.root).parent)
        if native_check:
            kind = toolchain.manifest["kind"]
            if kind not in {"native-temporary-toolchain", "native-final-libc", "native-compiler-candidate"}:
                raise ImageBuildError("native verification requires a recorded native build environment")
            if kind in {"native-final-libc", "native-compiler-candidate"}:
                execution = toolchain.manifest.get("verification_execution", {})
                if (toolchain.manifest.get("source_built") is not True
                    or toolchain.manifest.get("build_environment_complete") is not True
                    or execution.get("exit_code") != 0
                    or execution.get("cleanup_complete") is not True
                    or not toolchain.manifest["inputs"].get("verification")):
                    raise ImageBuildError("native environment lacks successful acceptance evidence")
        validation_only = seed_check or native_check
        if seed_check and toolchain.manifest["kind"] != "host-bootstrap":
            raise ImageBuildError("seed verification requires a recorded host bootstrap")
        if not validation_only and (
            toolchain.manifest["kind"] != "toolchain"
            or toolchain.manifest.get("stage") != 2
            or not toolchain.manifest.get("self_hosted")
        ):
            raise ImageBuildError(
                "ordinary builds require a promoted second-stage toolchain"
            )
        if toolchain.manifest["inputs"].get("architecture") != platform.machine():
            raise ImageBuildError("toolchain architecture differs from this host")
        packages = load_packages(self.package_dir)
        selected = order(packages, targets)
        inputs = {
            "schema": SCHEMA,
            "kind": "native-check" if native_check else ("seed-check" if seed_check else "image"),
            "composition_policy": INFO_INDEX_POLICY,
            "toolchain": toolchain.generation,
            "targets": list(targets),
            "recipes": {n: packages[n].fingerprint for n in selected},
            "architecture": platform.machine(),
        }
        if self.dependency_replacements:
            if not set(self.dependency_replacements).issubset(packages):
                raise ImageBuildError('replacement names absent from recipe graph')
            inputs['dependency_replacements'] = {n: r['identity'] for n, r in self.dependency_replacements.items()}
        existing = self.state / "image-build" / "generations" / identity(inputs)
        if existing.exists():
            result = self._verify_generation(read_selection(existing))
            self._publish_observation_snapshot(result)
            if not validation_only:
                self._activate(result, "active")
            return result
        attempt = self._candidate("image")
        try:
            built = self._build_set(packages, targets, toolchain, attempt)
            if self.provenance and self.provenance.generation_contract:
                from .generation_provenance import prepare, finish
                assembly = prepare(self.provenance, attempt, packages, targets, built, inputs)
            records = self._compose(packages, targets, built, attempt / "composed")
            details = {"packages": records}
            if self.provenance and self.provenance.generation_contract:
                details['build_record'] = finish(self.provenance, attempt, assembly, attempt / 'composed')
            result = self._publish(attempt / "composed", inputs, inputs["kind"], details)
            if not validation_only:
                self._activate(result, "active")
            write_json(
                attempt / "status.json",
                {"status": "complete", "generation": result.generation},
            )
            return result
        except BaseException as error:
            self._failed(attempt, error)
            raise
