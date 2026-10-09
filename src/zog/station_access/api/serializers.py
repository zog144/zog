def application_json(application):
    return {
        "name": application.name,
        "description": application.description,
        "multi_instance": application.multi_instance,
        "start_policy": application.start_policy,
        "workspace_role": application.workspace_role,
        "source_license": {
            "state": application.source_license_state,
            "reason": application.source_license_reason,
        },
    }


def program_json(program):
    return {
        "name": program.name,
        "service_name": program.service_name,
        "state": program.state,
        "invocation_id": program.invocation_id,
        "command": list(program.command),
        "main_pid": program.main_pid,
        "control_group": program.control_group,
        "result": program.result,
    }


def runtime_json(runtime):
    return {
        "runtime_id": runtime.runtime_id,
        "application_name": runtime.application_name,
        "instance_id": runtime.instance_id,
        "state": runtime.state,
        "generation": runtime.generation,
        "created_at": runtime.created_at,
        "completed_at": runtime.completed_at,
        "request_id": runtime.request_id,
        "fault": runtime.fault,
        "cleanup_pending": runtime.cleanup_pending,
        "programs": [program_json(program) for program in runtime.programs],
    }


def workspace_json(workspace, runtime_state=None):
    runtime = runtime_state.runtime if runtime_state is not None else None
    status = runtime_state.status if runtime_state is not None else (
        "launch-pending" if workspace.desired_running else "stopped"
    )
    return {
        "id": str(workspace.pk),
        "number": workspace.number,
        "network": workspace.network,
        "endpoint_ready": workspace.endpoint_ready,
        "name": workspace.name,
        "application_name": workspace.application_name,
        "desired_running": workspace.desired_running,
        "runtime_id": workspace.runtime_id,
        "instance_id": workspace.instance_id,
        "status": status,
        "runtime_state": runtime.state if runtime is not None else None,
        "endpoint_bound": bool(workspace.vnc_socket or (workspace.vnc_host and workspace.vnc_port)),
        "last_error": workspace.last_error or None,
        "created_at": workspace.created_at.isoformat(),
        "updated_at": workspace.updated_at.isoformat(),
    }
