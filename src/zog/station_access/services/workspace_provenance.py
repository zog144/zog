from __future__ import annotations

from zog.station_access.archive_inventory.generation_resolution import resolve_generation
from zog.station_access.services.authorization import can_access_runtime


def workspace_provenance(workspace, gateway, user):
    selector = str(workspace.pk) if hasattr(gateway, "workspace_capabilities") else workspace.number
    values = []
    if not (hasattr(gateway, "workspace_capabilities") and not workspace.controller_schema):
        values = list(gateway.workspace_application_runtimes(selector))

    if workspace.runtime_id and not any(item.runtime_id == workspace.runtime_id for item in values):
        current = gateway.get_runtime(workspace.runtime_id)
        if current is not None:
            values.append(current)

    visible = []
    for runtime in values:
        desktop = runtime.application_name == workspace.application_name
        owns_desktop = desktop and (
            runtime.runtime_id == workspace.runtime_id
            or runtime.workspace_id == str(workspace.pk)
        )
        if not owns_desktop and not can_access_runtime(user, runtime):
            continue
        visible.append(runtime)

    visible.sort(
        key=lambda item: (
            item.created_at is not None,
            item.created_at or 0,
            item.runtime_id,
        ),
        reverse=True,
    )

    generations = {}
    runtimes = []
    for runtime in visible:
        generation = runtime.generation
        if generation not in generations:
            generations[generation] = resolve_generation(generation)
        resolution = generations[generation]
        archive = resolution["observation"] if user.is_superuser else None
        runtimes.append(
            {
                "runtime_id": runtime.runtime_id,
                "application": runtime.application_name,
                "instance_id": runtime.instance_id,
                "role": "desktop" if runtime.application_name == workspace.application_name else "application",
                "state": runtime.state,
                "generation": generation,
                "created_at": runtime.created_at,
                "completed_at": runtime.completed_at,
                "generation_resolution": resolution["state"],
                "generation_digest": resolution["digest"],
                "generation_archive": archive,
                "generation_candidate_count": resolution["candidate_count"],
            }
        )

    return {
        "schema": 1,
        "workspace": {
            "id": str(workspace.pk),
            "number": workspace.number,
            "name": workspace.name,
        },
        "basis": "immutable-runtime-history",
        "administrator_generation_details": bool(user.is_superuser),
        "runtimes": runtimes,
    }
