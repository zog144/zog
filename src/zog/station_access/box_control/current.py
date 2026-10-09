"""Adapter for the current Zog box-control public Python facade.

All knowledge of box-control concrete types lives here. Django/API code consumes only the
small gateway protocol in ``port.py``.
"""

from pathlib import Path

from django.conf import settings

from .port import BoxControlUnavailable
from .types import ApplicationSummary, ProgramSummary, RuntimeSummary


def _enum_value(value) -> str:
    return str(getattr(value, "value", value))


def _program_state(reference) -> str:
    active = reference.active_state
    sub = reference.sub_state
    if active and sub:
        return f"{active}/{sub}"
    return active or sub or "unknown"


def _runtime_summary(reference) -> RuntimeSummary:
    return RuntimeSummary(
        runtime_id=reference.runtime_id,
        application_name=reference.application,
        instance_id=reference.instance_id,
        state=_enum_value(reference.state),
        generation=reference.generation,
        created_at=reference.created_at,
        completed_at=reference.completed_at,
        request_id=reference.request_id,
        fault=reference.error or reference.cleanup_error,
        workspace_id=(getattr(reference, "workspace_binding", None) or {}).get("workspace_id"),
        cleanup_pending=getattr(reference, "cleanup_pending", False),
        programs=tuple(
            ProgramSummary(
                name=program.program,
                service_name=program.unit_name,
                state=_program_state(program),
                invocation_id=program.invocation_id,
                command=tuple(program.command),
                main_pid=program.main_pid,
                control_group=program.control_group,
                result=program.result,
            )
            for program in reference.programs
        ),
    )


class CurrentBoxControlGateway:
    def __init__(self):
        try:
            from zog.box_control.api import BoxControl
            from zog.box_control.project import Project
            from zog.box_control.specification import discover_applications
        except ImportError as exc:
            raise BoxControlUnavailable(f"box-control is not importable: {exc}") from exc

        from zog.box_control.errors import BoxControlError
        try:
            configured = settings.STATION_ACCESS_ZOG_PROJECT_DIRECTORY
            self._control = BoxControl(Project(Path(configured))) if configured else BoxControl.discover()
        except (BoxControlError, OSError) as exc:
            raise BoxControlUnavailable(f"Zog project is not ready: {exc}") from exc
        self._discover_applications = discover_applications

    def list_applications(self) -> tuple[ApplicationSummary, ...]:
        specifications = self._discover_applications(self._control.project.application_dir)
        return tuple(
            ApplicationSummary(
                name=spec.name,
                description=spec.description,
                multi_instance=spec.multiple_instances,
                start_policy=_enum_value(spec.start_policy),
                workspace_role=getattr(spec, "workspace_role", None),
            )
            for spec in specifications.values()
        )

    def list_runtimes(self) -> tuple[RuntimeSummary, ...]:
        references = self._control.application_runtimes()
        ordered = sorted(
            references.values(),
            key=lambda item: (item.created_at, item.runtime_id),
            reverse=True,
        )
        return tuple(_runtime_summary(reference) for reference in ordered)

    def get_runtime(self, runtime_id: str) -> RuntimeSummary | None:
        reference = self._control.application_runtime(runtime_id)
        return _runtime_summary(reference) if reference is not None else None

    def issue_application_request_id(self) -> str:
        return self._control.issue_application_request_id()

    def workspace_capabilities(self):
        method = getattr(self._control, "workspace_capabilities", None)
        return method() if method else {"schema": None, "supported": False}

    def register_workspace(self, workspace):
        self.require_workspace_contract()
        return self._control.register_workspace(str(workspace.pk), workspace.number, network="host-shared")

    def require_workspace_contract(self):
        value = self.workspace_capabilities()
        if value.get("schema") != "zog-workspace-v1" or not value.get("supported") or value.get("desktop_transport") != "unix" or value.get("cancellation_response") != "structured-outcome-v1":
            raise BoxControlUnavailable("Compatible zog-workspace-v1 controller required")
        return value

    def workspace_membership(self, workspace_id):
        self.require_workspace_contract()
        # Pages are independent snapshots. Controller mutations remain the final
        # authority; this bounded aggregation is for presentation, never admission.
        items, after, seen = [], None, set()
        for _ in range(32):
            page = self._control.workspace_membership(str(workspace_id), after=after, limit=100)
            if page.get("schema") != "zog-workspace-v1" or page.get("workspace_id") != str(workspace_id) or page.get("complete") is not True:
                raise BoxControlUnavailable("Incomplete controller membership")
            for item in page["items"]:
                if item["key"] not in seen:
                    items.append(item); seen.add(item["key"])
            following = page.get("next")
            if following is None:
                return items
            if after is not None and following <= after:
                break
            after = following
        raise BoxControlUnavailable("Workspace membership exceeds bounded inspection")

    def workspace_catalogue(self):
        self.require_workspace_contract()
        items, after = [], None
        for _ in range(6):
            page = self._control.workspace_application_catalogue(after=after, limit=100)
            if page.get("schema") != "zog-workspace-v1":
                raise BoxControlUnavailable("Unsupported catalogue schema")
            items.extend(page["items"])
            following = page.get("next")
            if following is None:
                return items
            if after is not None and following <= after:
                break
            after = following
        raise BoxControlUnavailable("Workspace catalogue exceeds bounded inspection")

    def workspace_desktop_access(self, workspace_id):
        self.require_workspace_contract()
        return self._control.workspace_desktop_access(str(workspace_id))

    def delete_registered_workspace(self, workspace_id):
        return self._control.delete_workspace(str(workspace_id))

    def preflight_workspace_application(self, name, workspace_id):
        return self._control.preflight_application_launch(name, workspace_id=str(workspace_id))

    def find_application_launch(self, application_name, *, request_id, workspace_id=None, parameters=None):
        result = self._control.application_request_result(request_id)
        if result is None:
            return None  # Retry the SAME request: controller checks prepared intent.
        if result.application != application_name or getattr(result, "workspace_id", None) != str(workspace_id):
            raise BoxControlUnavailable("Recorded launch intent disagrees with workspace")
        if not result.runtime_id:
            raise BoxControlUnavailable("Recorded request has no accepted runtime; inspect its outcome before retrying")
        runtime = self.get_current_runtime(result.runtime_id)
        if runtime is None or runtime.workspace_id != str(workspace_id) or runtime.application_name != application_name or runtime.request_id != request_id:
            raise BoxControlUnavailable("Recorded runtime binding is unavailable or inconsistent")
        return runtime

    def launch_application(self, application_name, *, request_id, workspace_id=None, parameters=None):
        return _runtime_summary(self._control.launch_application(application_name, request_id=request_id,
            workspace_id=str(workspace_id) if workspace_id is not None else None, parameters=parameters))

    def get_current_runtime(self, runtime_id):
        from dataclasses import replace
        reference = self._control.application_runtime(runtime_id)
        if reference is None:
            return None
        snapshot = self._control.observe_application_runtime(runtime_id)
        if snapshot['status'] != 'observed':
            raise BoxControlUnavailable("Current runtime observation is unavailable or has an integrity fault")
        if any(p['status'] not in ('observed', 'absent', 'previous-boot') for p in snapshot['programs']):
            raise BoxControlUnavailable("Runtime identity cannot be verified")
        observations = [p['observation'] for p in snapshot['programs'] if p['status'] == 'observed']
        active = any(p.get('active_state') in ('active', 'activating', 'deactivating', 'reloading') for p in observations)
        failed = any(p.get('active_state') == 'failed' or p.get('result') not in (None, '', 'success') for p in observations)
        summary = _runtime_summary(reference)
        return replace(summary, state=('running' if active else 'failed' if failed else 'terminated'))

    def read_logs(self, runtime_id, *, program=None, cursor=None, limit=50):
        from .port import _import_factory
        return _import_factory(settings.STATION_ACCESS_LOG_READER_FACTORY)(self._control).read_logs(
            runtime_id, program=program, cursor=cursor, limit=limit)

    def workspace_application_runtimes(self, workspace_id):
        values = []
        for member in self.workspace_membership(workspace_id):
            if member["kind"] == "runtime":
                runtime = self.get_runtime(member["runtime_id"])
                if runtime is None or runtime.workspace_id != str(workspace_id):
                    raise BoxControlUnavailable("Workspace member runtime evidence missing")
                values.append(runtime)
        seen = {runtime.runtime_id for runtime in values}
        # Retained terminal references are history, not resource ownership claims.
        history = sorted(self._control.application_runtimes().values(),
            key=lambda reference: (reference.created_at, reference.runtime_id), reverse=True)
        for reference in history:
            if (getattr(reference, "workspace_binding", None) or {}).get("workspace_id") == str(workspace_id) and reference.runtime_id not in seen:
                runtime = _runtime_summary(reference)
                if runtime.terminal:
                    values.append(runtime)
                    if len(values) >= len(seen) + 25:
                        break
        return tuple(values)

    def workspace_dependencies(self, workspace_id, *, excluding_runtime=None):
        return [member["key"] for member in self.workspace_membership(workspace_id)
                if member["kind"] != "runtime" or member["runtime_id"] != excluding_runtime]

    def list_build_jobs(self, *, after=None, limit=50):
        return self._control.list_build_jobs(after=after, limit=limit)

    def get_build_job(self, job_id):
        return self._control.inspect_build_job(job_id)

    def read_build_logs(self, job_id, *, cursor=None, limit=50):
        from .journal import JournalReader
        return JournalReader(self._control).read_build_logs(job_id, cursor=cursor, limit=limit)

    def cancel_application_launch(self, application_name, *, request_id, workspace_id=None, parameters=None):
        result = self._control.cancel_application_launch(application_name, request_id=request_id,
            workspace_id=str(workspace_id) if workspace_id is not None else None, parameters=parameters)
        if not isinstance(result, dict) or result.get("request_id") != request_id or result.get("application") != application_name or result.get("status") not in {"cancelled", "accepted", "pending", "uncertain", "failed", "abandoned"}:
            raise BoxControlUnavailable("Invalid controller cancellation outcome")
        return result

    def terminate_application_runtime(self, runtime_id: str) -> RuntimeSummary:
        return _runtime_summary(self._control.terminate_application_runtime(runtime_id))


def create_gateway():
    return CurrentBoxControlGateway()
