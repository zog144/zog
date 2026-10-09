import json
import os

import pytest

from zog.image_build.application_software import (
    ApplicationSoftwareStore,
    MOUNT_CONTRACT,
)
from zog.image_build.application_views import (
    ApplicationSoftwareViewStore,
    CONSUMER_CONTRACT,
    VIEW_CONTRACT,
)
from zog.image_build.errors import ImageBuildError
from zog.image_build.filesystem import inventory


def descriptor(
    *,
    architecture="x86_64",
    version="3.12.7",
    libraries=(),
):
    return {
        "schema": 1,
        "mount_contract": MOUNT_CONTRACT,
        "architecture": architecture,
        "python": {
            "implementation": "cpython",
            "version": version,
            "soabi": "cpython-312-x86_64-linux-gnu",
        },
        "libraries": list(libraries),
    }


def publish_component(
    store,
    operation,
    files,
    *,
    application="station-access",
    revision=None,
    libraries=("libssl.so.3",),
):
    revision = revision or (
        "git:" + operation[-1] * 40
    )
    prepared = store.begin(
        operation,
        application=application,
        revision=revision,
        sources=[
            {
                "name": operation,
                "url": (
                    "https://example.invalid/"
                    + operation
                    + ".tar.xz"
                ),
                "sha256": "1" * 64,
            }
        ],
        compatibility_requirements=descriptor(
            libraries=libraries
        ),
        notices=(),
        provenance={
            "component": operation,
            "build_record": "sha256:" + "1" * 64,
            "build_trace": "sha256:" + "2" * 64,
        },
    )
    for path, content in files.items():
        target = prepared.root / path
        target.parent.mkdir(
            parents=True, exist_ok=True
        )
        if (
            isinstance(content, tuple)
            and content[0] == "symlink"
        ):
            target.symlink_to(content[1])
        else:
            target.write_text(content)
    return store.finalize(operation)


def station_components(state):
    artifacts = ApplicationSoftwareStore(state)
    backend = publish_component(
        artifacts,
        "backend-a",
        {
            "bin/station-access": (
                "#!/usr/bin/python3\n"
            ),
            (
                "lib/python3.12/site-packages/"
                "django/__init__.py"
            ): "__version__='fixture'\n",
            (
                "lib/python3.12/site-packages/"
                "station_access/__init__.py"
            ): "__version__='fixture'\n",
        },
        revision="git:" + "a" * 40,
    )
    frontend = publish_component(
        artifacts,
        "frontend-b",
        {
            (
                "share/station-access/static/"
                "app.js"
            ): "console.log('fixture');\n",
            (
                "share/station-access/static/"
                "index.html"
            ): "<div id='root'></div>\n",
        },
        revision="git:" + "b" * 40,
    )
    return artifacts, backend, frontend


def test_station_access_view_composes_python_and_frontend_runtime(
    tmp_path,
):
    state = tmp_path / "state"
    artifacts, backend, frontend = (
        station_components(state)
    )
    views = ApplicationSoftwareViewStore(state)
    before = {
        backend.artifact: inventory(backend.root),
        frontend.artifact: inventory(frontend.root),
    }
    published = views.publish(
        "station-view-a",
        application="station-access",
        artifacts=[
            frontend.artifact,
            backend.artifact,
        ],
    )
    assert published.view.startswith("sha256:")
    assert (
        published.manifest["contract"]
        == VIEW_CONTRACT
    )
    assert published.manifest["artifacts"] == sorted(
        [backend.artifact, frontend.artifact]
    )
    assert (
        published.root
        / "bin/station-access"
    ).is_symlink()
    assert (
        published.root
        / (
            "lib/python3.12/site-packages/"
            "django/__init__.py"
        )
    ).is_symlink()
    assert (
        published.root
        / "share/station-access/static/app.js"
    ).is_symlink()
    target = os.readlink(
        published.root / "bin/station-access"
    )
    assert (
        ".store/" + backend.artifact[7:]
    ) in target

    assert (
        inventory(
            artifacts.resolve(
                backend.artifact
            ).root
        )
        == before[backend.artifact]
    )
    assert (
        inventory(
            artifacts.resolve(
                frontend.artifact
            ).root
        )
        == before[frontend.artifact]
    )


def test_view_identity_is_deterministic_and_order_independent(
    tmp_path,
):
    state = tmp_path / "state"
    _, backend, frontend = station_components(
        state
    )
    views = ApplicationSoftwareViewStore(state)
    first = views.publish(
        "order-a",
        application="station-access",
        artifacts=[
            backend.artifact,
            frontend.artifact,
        ],
    )
    second = views.publish(
        "order-b",
        application="station-access",
        artifacts=[
            frontend.artifact,
            backend.artifact,
        ],
    )
    assert second.view == first.view
    assert second.reused


def test_view_rejects_file_collision_without_priority_overwrite(
    tmp_path,
):
    state = tmp_path / "state"
    artifacts = ApplicationSoftwareStore(state)
    first = publish_component(
        artifacts,
        "collision-a",
        {"bin/tool": "one\n"},
    )
    second = publish_component(
        artifacts,
        "collision-b",
        {"bin/tool": "two\n"},
    )
    views = ApplicationSoftwareViewStore(state)
    with pytest.raises(
        ImageBuildError, match="path collision"
    ):
        views.publish(
            "collision-view",
            application="station-access",
            artifacts=[
                first.artifact,
                second.artifact,
            ],
        )


def test_unsafe_artifact_symlink_never_enters_view(
    tmp_path,
):
    state = tmp_path / "state"
    artifacts = ApplicationSoftwareStore(state)
    prepared = artifacts.begin(
        "unsafe-a",
        application="station-access",
        revision="git:" + "a" * 40,
        compatibility_requirements=descriptor(),
        notices=(),
        provenance={},
    )
    (prepared.root / "lib").mkdir()
    os.symlink(
        "../../outside",
        prepared.root / "lib/escape",
    )
    with pytest.raises(
        ImageBuildError, match="symlink escapes"
    ):
        artifacts.finalize(prepared.operation)


def test_interrupted_view_publication_recovers_exact_frozen_view(
    tmp_path, monkeypatch
):
    import zog.image_build.application_views as module

    state = tmp_path / "state"
    _, backend, frontend = station_components(
        state
    )
    views = ApplicationSoftwareViewStore(state)
    original = module._publish_candidate
    published = []

    def lose(candidate, target):
        original(candidate, target)
        published.append(target.name)
        raise OSError(
            "lost view publication response"
        )

    monkeypatch.setattr(
        module, "_publish_candidate", lose
    )
    with pytest.raises(
        OSError,
        match="lost view publication response",
    ):
        views.publish(
            "interrupted-view",
            application="station-access",
            artifacts=[
                backend.artifact,
                frontend.artifact,
            ],
        )
    operation = (
        views.root
        / "view-operations/interrupted-view"
    )
    frozen = json.loads(
        (operation / "frozen.json").read_text()
    )
    assert (
        frozen["manifest"]["view"][7:]
        == published[0]
    )
    assert not (
        operation / "result.json"
    ).exists()

    monkeypatch.setattr(
        module, "_publish_candidate", original
    )
    recovered = views.publish(
        "interrupted-view",
        application="station-access",
        artifacts=[
            backend.artifact,
            frontend.artifact,
        ],
    )
    assert (
        recovered.view
        == frozen["manifest"]["view"]
    )
    assert (
        views.resolve(recovered.view).manifest
        == frozen["manifest"]
    )


def test_new_view_never_mutates_previous_view(
    tmp_path,
):
    state = tmp_path / "state"
    artifacts, backend, frontend = (
        station_components(state)
    )
    views = ApplicationSoftwareViewStore(state)
    first = views.publish(
        "station-view-v1",
        application="station-access",
        artifacts=[
            backend.artifact,
            frontend.artifact,
        ],
    )
    first_manifest = json.loads(
        json.dumps(first.manifest)
    )
    first_outputs = inventory(first.root)

    frontend_v2 = publish_component(
        artifacts,
        "frontend-c",
        {
            (
                "share/station-access/static/"
                "app.js"
            ): "console.log('v2');\n"
        },
        revision="git:" + "c" * 40,
    )
    second = views.publish(
        "station-view-v2",
        application="station-access",
        artifacts=[
            backend.artifact,
            frontend_v2.artifact,
        ],
    )
    assert second.view != first.view
    retained = views.resolve(first.view)
    assert retained.manifest == first_manifest
    assert (
        inventory(retained.root)
        == first_outputs
    )


def test_consumer_manifest_verifies_compatibility_and_required_objects(
    tmp_path,
):
    state = tmp_path / "state"
    _, backend, frontend = station_components(
        state
    )
    views = ApplicationSoftwareViewStore(state)
    published = views.publish(
        "station-binding",
        application="station-access",
        artifacts=[
            backend.artifact,
            frontend.artifact,
        ],
    )
    binding = views.consumer_manifest(
        published.view,
        descriptor(
            libraries=(
                "libssl.so.3",
                "libc.so.6",
            )
        ),
    )
    assert (
        binding["contract"]
        == CONSUMER_CONTRACT
    )
    assert binding["view"] == published.view
    assert (
        binding["mount_point"]
        == "/applications/station-access"
    )
    assert binding["manifest"].endswith("/manifest.json")
    assert binding["binding_digest"].startswith("sha256:")
    assert binding["rootfs_compatibility"] == descriptor(
        libraries=("libc.so.6", "libssl.so.3")
    )
    assert {
        item["artifact"]
        for item in binding["objects"]
    } == {
        backend.artifact,
        frontend.artifact,
    }
    assert all(
        item["mount_point"].startswith(
            "/applications/.store/"
        )
        for item in binding["objects"]
    )
    assert all(
        item["manifest"].endswith("/manifest.json")
        and item["compatibility"]["mount_contract"] == MOUNT_CONTRACT
        for item in binding["objects"]
    )
    assert binding[
        "reclamation_protection"
    ] == {
        "view": published.view,
        "artifacts": sorted(
            [
                backend.artifact,
                frontend.artifact,
            ]
        ),
    }
    assert (
        views.referenced_artifacts(
            published.view
        )
        == tuple(
            sorted(
                [
                    backend.artifact,
                    frontend.artifact,
                ]
            )
        )
    )

    with pytest.raises(
        ImageBuildError, match="incompatible"
    ):
        views.consumer_manifest(
            published.view,
            descriptor(
                architecture="aarch64",
                libraries=("libssl.so.3",),
            ),
        )


def test_everything_profile_is_independently_addressable(
    tmp_path,
):
    state = tmp_path / "state"
    artifacts = ApplicationSoftwareStore(state)
    editor = publish_component(
        artifacts,
        "editor-a",
        {
            "bin/kate": "#!/bin/sh\n",
            "lib/libQt6Core.so.6": "fixture\n",
        },
        application="everything",
        revision="git:" + "d" * 40,
        libraries=("libc.so.6",),
    )
    terminal = publish_component(
        artifacts,
        "terminal-b",
        {"bin/xterm": "#!/bin/sh\n"},
        application="everything",
        revision="git:" + "e" * 40,
        libraries=("libc.so.6",),
    )
    views = ApplicationSoftwareViewStore(state)
    everything = views.publish(
        "everything-v1",
        application="everything",
        profile="everything",
        artifacts=[
            editor.artifact,
            terminal.artifact,
        ],
    )
    assert (
        everything.manifest["profile"]
        == "everything"
    )
    assert (
        everything.root / "bin/kate"
    ).is_symlink()
    assert (
        everything.root / "bin/xterm"
    ).is_symlink()


def test_view_tamper_is_detected(tmp_path):
    state = tmp_path / "state"
    _, backend, frontend = station_components(
        state
    )
    views = ApplicationSoftwareViewStore(state)
    published = views.publish(
        "tamper-view",
        application="station-access",
        artifacts=[
            backend.artifact,
            frontend.artifact,
        ],
    )
    link = (
        published.root / "bin/station-access"
    )
    link.unlink()
    link.symlink_to(
        "../../.store/"
        + frontend.artifact[7:]
        + "/bin/station-access"
    )
    with pytest.raises(
        ImageBuildError,
        match="view links changed",
    ):
        views.resolve(published.view)
