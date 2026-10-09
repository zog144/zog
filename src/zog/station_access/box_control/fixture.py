from dataclasses import replace

from .types import ApplicationSummary, ProgramSummary, RuntimeSummary


class FixtureGateway:
    """Small in-memory gateway used by tests and frontend development."""

    def __init__(self):
        self.applications = {
            "browser": ApplicationSummary("browser", "Example browser", False, "externally-controlled"),
            "editor": ApplicationSummary("editor", "Example editor", False, "externally-controlled"),
            "vnc-workspace": ApplicationSummary("vnc-workspace", "Example VNC workspace", True, "externally-controlled"),
        }
        self.runtimes: dict[str, RuntimeSummary] = {}
        self.counter = 0
        self.parameters = {}
        self.cancelled = set()

    def workspace_application_runtimes(self, number):
        return tuple(runtime for runtime in self.runtimes.values()
                     if self.parameters.get(runtime.request_id, {}).get("workspace-number") == number)

    def workspace_dependencies(self, number, *, excluding_runtime=None):
        return [runtime.runtime_id for runtime in self.runtimes.values()
                if runtime.runtime_id != excluding_runtime and not runtime.terminal
                and self.parameters.get(runtime.request_id, {}).get("workspace-number") == number]

    def list_applications(self):
        return tuple(self.applications.values())

    def list_runtimes(self):
        return tuple(self.runtimes.values())

    def get_runtime(self, runtime_id: str):
        return self.runtimes.get(runtime_id)

    def issue_application_request_id(self):
        self.counter += 1
        return f"fixture-request-{self.counter}"

    def find_application_launch(self, application_name, *, request_id, parameters):
        runtime = self.runtimes.get(f"fixture-runtime-{request_id}")
        if runtime and (runtime.application_name != application_name or self.parameters[request_id] != parameters):
            raise RuntimeError("conflicting launch binding")
        return runtime

    def launch_application(self, application_name: str, *, request_id: str, parameters: dict | None = None):
        if request_id in self.cancelled:
            raise RuntimeError("launch was cancelled")
        if request_id in self.parameters and self.parameters[request_id] != (parameters or {}):
            raise RuntimeError("conflicting parameters")
        self.parameters[request_id] = parameters or {}
        runtime_id = f"fixture-runtime-{request_id}"
        existing = self.runtimes.get(runtime_id)
        if existing is not None:
            return existing
        runtime = RuntimeSummary(
            runtime_id=runtime_id,
            application_name=application_name,
            instance_id=f"{application_name}-{request_id[-6:]}",
            state="running",
            generation="fixture",
            request_id=request_id,
            programs=(ProgramSummary("vnc", f"zog-{runtime_id}-vnc.service", "active/running"),),
        )
        self.runtimes[runtime_id] = runtime
        return runtime

    def read_logs(self, runtime_id, *, program=None, cursor=None, limit=200):
        import hashlib
        from .logs import LogPage, LogEntry, LogCursorExpired
        runtime = self.runtimes[runtime_id]
        scope = hashlib.sha256(f"{runtime_id}:{program or ''}".encode()).hexdigest()[:16]
        offset = 0
        if cursor:
            try:
                prefix, value = cursor.split(":")
                offset = int(value)
                if prefix != scope or not 0 <= offset <= 6:
                    raise ValueError()
            except ValueError as exc:
                raise LogCursorExpired("The log position is no longer available; reload recent entries.") from exc
        messages = [(6, "Service process started"), (6, "Configuration loaded"),
            (6, "Ready to accept work"), (4, "Example retry: dependency temporarily unavailable"),
            (3, "Example task failed\nTraceback (most recent call last):\n  RuntimeError: demonstration failure"),
            (6, "Worker continues processing other tasks")]
        names = [p for p in runtime.programs if program is None or p.name == program]
        if not names:
            return LogPage((), cursor, source='fixture')
        end = min(len(messages), offset + limit)
        entries = tuple(LogEntry(f"{scope}:{i + 1}", f"2026-09-16T14:03:{i:02d}Z",
            names[i % len(names)].name, messages[i][0], messages[i][1], names[i % len(names)].invocation_id)
            for i in range(offset, end))
        return LogPage(entries, f"{scope}:{end}", end < len(messages), 'fixture')

    def assert_endpoint_available(self, host, port):
        pass

    def workspace_ready(self, host, port):
        return True

    def cancel_application_launch(self, application_name, *, request_id, parameters=None):
        runtime = self.runtimes.get(f"fixture-runtime-{request_id}")
        if runtime is None:
            self.cancelled.add(request_id)
        return runtime

    def terminate_application_runtime(self, runtime_id: str):
        runtime = self.runtimes[runtime_id]
        stopped = replace(runtime, state="terminated")
        self.runtimes[runtime_id] = stopped
        return stopped


_GATEWAY = FixtureGateway()


def create_gateway():
    return _GATEWAY
