from dataclasses import dataclass, field


@dataclass(frozen=True)
class ApplicationSummary:
    name: str
    description: str | None = None
    multi_instance: bool = False
    start_policy: str | None = None
    workspace_role: str | None = None
    source_license_state: str = "unavailable"
    source_license_reason: str = "application-source-identity-not-published"


@dataclass(frozen=True)
class ProgramSummary:
    name: str
    service_name: str
    state: str
    invocation_id: str | None = None
    command: tuple[str, ...] = ()
    main_pid: int | None = None
    control_group: str | None = None
    result: str | None = None


@dataclass(frozen=True)
class RuntimeSummary:
    runtime_id: str
    application_name: str
    instance_id: str
    state: str
    generation: str | None = None
    created_at: float | None = None
    completed_at: float | None = None
    request_id: str | None = None
    fault: str | None = None
    programs: tuple[ProgramSummary, ...] = field(default_factory=tuple)
    workspace_id: str | None = None
    cleanup_pending: bool = False

    @property
    def terminal(self) -> bool:
        return self.state in {"terminated", "failed"}
