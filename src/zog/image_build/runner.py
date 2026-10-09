"""Image-build's execution port. Production execution must be supplied by box-control.

The configured adapter submits durable finite jobs to box-control. There is no
subprocess, systemd, Docker, Podman, or native execution fallback here.
"""

from dataclasses import dataclass, asdict
import json
from pathlib import Path
from typing import Callable, Optional
from .errors import ImageBuildError
from .filesystem import write_json


@dataclass(frozen=True)
class BuildExecutionRequest:
    root: Path
    source: Path
    output: Path
    command: tuple
    environment: dict
    working_directory: str
    timeout_seconds: float
    read_only_root: bool = True
    network_access: bool = False


@dataclass(frozen=True)
class BuildExecutionResult:
    runtime_id: str
    invocation_id: str
    exit_code: int
    cleanup_complete: bool
    journal_reference: str


class BoxControlRunner:
    """Caller-side port for the box-control-owned finite executor.

    An integrator supplies the configured controller adapter. Its contract includes bounded execution, cgroup cleanup, and durable
    launch/result ownership. A missing adapter fails closed before any execution.
    """

    def __init__(self, execute: Optional[Callable] = None, timeout=3600):
        self.execute = execute
        self.timeout = timeout

    def run(self, root, source, output, arguments, environment, log):
        if self.execute is None:
            raise ImageBuildError(
                "box-control build-job integration is unavailable; provide its execution "
                "adapter or use --controller-config. No alternate runtime is used."
            )
        request = BuildExecutionRequest(
            root=Path(root).resolve(),
            source=Path(source).resolve(),
            output=Path(output).resolve(),
            command=tuple(arguments),
            environment={
                "PATH": "/usr/bin:/bin:/usr/sbin:/sbin",
                "LANG": "C",
                "LC_ALL": "C",
                **environment,
                "HOME": "/tmp",
                "DESTDIR": "/image-build/output",
                "IMAGE_BUILD_SOURCE": "/image-build/source",
                "IMAGE_BUILD_OUTPUT": "/image-build/output",
            },
            working_directory="/image-build/source",
            timeout_seconds=self.timeout,
        )
        completion = Path(log).with_suffix(".execution.json")
        binding = json.loads(json.dumps(asdict(request), default=str))
        policy = self.execute.configuration() if hasattr(self.execute, "configuration") else None
        from .trace_records import capture_request
        capture_request(log, request, policy)
        if completion.exists():
            saved = json.loads(completion.read_text())
            if saved.get("request") != binding or saved.get("policy") != policy:
                raise ImageBuildError("completed command intent changed")
            result = BuildExecutionResult(**{k: saved[k] for k in BuildExecutionResult.__dataclass_fields__})
        elif hasattr(self.execute, "execute_for_attempt"):
            result = self.execute.execute_for_attempt(request, Path(log).with_suffix(".controller.json"))
        else:
            result = self.execute(request)
        if not isinstance(result, BuildExecutionResult):
            raise ImageBuildError(
                "box-control adapter returned no typed build completion evidence"
            )
        if (
            not result.runtime_id
            or not result.invocation_id
            or not result.journal_reference
        ):
            raise ImageBuildError(
                "box-control completion evidence is missing runtime, invocation, or journal identity"
            )
        write_json(completion, {"request": binding, "policy": policy, **asdict(result)})
        if not result.cleanup_complete:
            raise ImageBuildError(
                "box-control build cleanup is unresolved; preserve this attempt and its inputs"
            )
        if result.exit_code != 0:
            raise ImageBuildError(
                f"build exited with status {result.exit_code}; inspect {result.journal_reference}"
            )
