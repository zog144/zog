import dataclasses
import ast
import hashlib
import io
import json
import subprocess
import sys
import tarfile
from pathlib import Path
import pytest
from zog.image_build import ImageBuild, ImageBuildError, load_package, read_selection
from zog.image_build.filesystem import inventory, merge
from zog.image_build.metadata import order
from zog.image_build.runner import BoxControlRunner, BuildExecutionResult
from zog.image_build.sources import stage
from zog.image_build.developer.host import detect, install_command, assemble


def recipe(directory, name, *, build=(), runtime=(), outputs=None):
    path = directory / name
    path.mkdir(parents=True)
    payload = path / "payload.txt"
    payload.write_text(name)
    definitions = {
        "sources.py": [
            {
                "url": payload.resolve().as_uri(),
                "sha256": hashlib.sha256(name.encode()).hexdigest(),
                "destination": "payload.txt",
                "archive": False,
            }
        ],
        "dependencies.py": {"build": list(build), "runtime": list(runtime)},
        "build.py": {
            "build": [["compile", name]],
            "test": [["test", name]],
            "install": [["install", name]],
        },
        "produce-manifest.py": outputs or ["usr/share/" + name],
    }
    for filename, value in definitions.items():
        (path / filename).write_text(repr(value))
    pin_path = directory / 'commit-pin.py'
    pins = ast.literal_eval(pin_path.read_text()) if pin_path.exists() else {'schema': 1, 'date': '2026-10-01', 'packages': {}}
    pins['packages'][name] = {'sources': definitions['sources.py']}
    pin_path.write_text(repr(pins))
    return load_package(path)


class RecordingRunner:
    def __init__(self):
        self.calls = []
        self.fail = None

    def run(self, root, source, output, arguments, environment, log):
        self.calls.append((arguments, tuple(r["path"] for r in inventory(root))))
        Path(log).write_text(repr(arguments))
        if self.fail == arguments[0]:
            raise ImageBuildError("injected command failure")
        if arguments[0] == "install":
            target = output / "usr/share" / arguments[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(arguments[1])


@pytest.fixture
def prepared(tmp_path):
    packages = tmp_path / "package"
    recipe(packages, "compiler-first")
    recipe(packages, "compiler-second")
    recipe(packages, "library")
    recipe(packages, "consumer", runtime=("library",))
    host = tmp_path / "host"
    host.mkdir()
    (host / "host-only").write_text("seed")
    runner = RecordingRunner()
    builder = ImageBuild(
        package_dir=packages, state_dir=tmp_path / "state", runner=runner
    )
    seed = builder.import_bootstrap(host, {"id": "amazon-linux-2023"})
    toolchain = builder.bootstrap(seed, [["compiler-first"], ["compiler-second"]])
    return builder, runner, seed, toolchain


def test_bootstrap_boundary_and_source_image(prepared):
    builder, runner, seed, toolchain = prepared
    from zog.image_build.info_index import POLICY
    assert toolchain.manifest["inputs"]["composition_policy"] == POLICY
    first = [
        paths for args, paths in runner.calls if args == ["compile", "compiler-first"]
    ][0]
    second = [
        paths for args, paths in runner.calls if args == ["compile", "compiler-second"]
    ][0]
    assert "host-only" in first
    assert "host-only" not in second and "usr/share/compiler-first" in second
    result = builder.ensure(["consumer"], toolchain=toolchain)
    assert (result.root / "usr/share/library").exists()
    assert not (result.root / "usr/share/compiler-second").exists()
    assert not (result.root / "host-only").exists()
    count = len(runner.calls)
    assert builder.ensure(["consumer"], toolchain=toolchain).reused
    assert len(runner.calls) == count


def test_unrelated_package_is_absent(prepared):
    builder, runner, _, toolchain = prepared
    builder.ensure(["library", "consumer"], toolchain=toolchain)
    library_root = [
        paths for args, paths in runner.calls if args == ["compile", "library"]
    ][0]
    assert "usr/share/consumer" not in library_root


def test_host_seed_rejected_for_ordinary_build(prepared):
    builder, _, seed, _ = prepared
    with pytest.raises(ImageBuildError, match="second-stage"):
        builder.ensure(["consumer"], toolchain=seed)


def test_failure_preserves_active_and_logs(prepared):
    builder, runner, _, toolchain = prepared
    first = builder.ensure(["library"], toolchain=toolchain)
    runner.fail = "compile"
    with pytest.raises(ImageBuildError):
        builder.ensure(["consumer"], toolchain=toolchain)
    assert (
        builder.state / "image-build/active"
    ).resolve() == first.root.parent.resolve()
    attempts = builder.state / "image-build/attempts"
    assert any(
        json.loads(p.read_text())["status"] == "failed"
        for p in attempts.glob("*/status.json")
    )
    assert list(attempts.glob("*/packages/library/build-0.log"))


def test_failed_bootstrap_not_promoted(tmp_path):
    packages = tmp_path / "package"
    recipe(packages, "first")
    recipe(packages, "second")
    host = tmp_path / "host"
    host.mkdir()
    (host / "seed").write_text("seed")
    runner = RecordingRunner()
    runner.fail = "cc"
    builder = ImageBuild(
        package_dir=packages, state_dir=tmp_path / "state", runner=runner
    )
    seed = builder.import_bootstrap(host, {})
    with pytest.raises(ImageBuildError):
        builder.bootstrap(seed, [["first"], ["second"]])
    assert not (builder.state / "image-build/toolchain-active").exists()


def test_corrupt_published_outputs_block_reuse(prepared):
    builder, _, _, toolchain = prepared
    result = builder.ensure(["consumer"], toolchain=toolchain)
    (result.root / "usr/share/consumer").write_text("changed")
    with pytest.raises(ImageBuildError, match="outputs changed"):
        builder.ensure(["consumer"], toolchain=toolchain)


def test_missing_dependency_and_cycle(tmp_path):
    a = recipe(tmp_path, "a", build=("b",))
    with pytest.raises(ImageBuildError, match="missing"):
        order({"a": a}, ["a"])
    b = recipe(tmp_path, "b", build=("a",))
    with pytest.raises(ImageBuildError, match="cycle"):
        order({"a": a, "b": b}, ["a"])


def test_metadata_not_executed(tmp_path):
    package = recipe(tmp_path, "a")
    path = tmp_path / "a/build.py"
    path.write_text("__import__('os').system('false')")
    with pytest.raises(ImageBuildError, match="literal"):
        load_package(tmp_path / "a")


def test_output_mismatch(prepared):
    builder, _, _, toolchain = prepared
    (builder.package_dir / "consumer/produce-manifest.py").write_text(repr(["wrong"]))
    with pytest.raises(ImageBuildError, match="produce-manifest"):
        builder.ensure(["consumer"], toolchain=toolchain)


def test_conflicting_outputs_and_symlink_parent(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "same").write_text("one")
    (b / "same").write_text("two")
    destination = tmp_path / "destination"
    merge(a, destination)
    with pytest.raises(ImageBuildError, match="ownership"):
        merge(b, destination)
    (b / "same").unlink()
    (b / "escape").mkdir()
    (b / "escape/payload").write_text("bad")
    (destination / "escape").symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ImageBuildError):
        merge(b, destination)
    assert not (tmp_path / "payload").exists()


def test_checksum_failure(tmp_path):
    package = recipe(tmp_path / "package", "a")
    (tmp_path / "package/a/payload.txt").write_text("changed")
    with pytest.raises(ImageBuildError, match="checksum"):
        stage(package, tmp_path / "source", tmp_path / "cache")


def test_archive_traversal_rejected(tmp_path):
    package = recipe(tmp_path / "package", "a")
    archive = tmp_path / "bad.tar"
    with tarfile.open(archive, "w") as stream:
        info = tarfile.TarInfo("../escape")
        info.size = 1
        stream.addfile(info, io.BytesIO(b"x"))
    source = {
        "url": archive.as_uri(),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "destination": "tree",
        "archive": True,
    }
    package = dataclasses.replace(package, sources=(source,))
    with pytest.raises(ImageBuildError, match="unsafe"):
        stage(package, tmp_path / "source", tmp_path / "cache")
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "system,version,manager",
    [("amzn", "2023", "dnf"), ("amzn", "2", "yum"), ("fedora", "rawhide", "dnf")],
)
def test_host_profiles(tmp_path, system, version, manager):
    path = tmp_path / "os-release"
    path.write_text(f'ID={system}\nVERSION_ID="{version}"\n')
    profile = detect(path)
    command = install_command(profile)
    assert command[:3] == [manager, "-y", "install"]
    assert "gcc" in command and not any("--installroot" in x for x in command)


def test_unknown_host_is_not_fedora(tmp_path):
    path = tmp_path / "os-release"
    path.write_text("ID=unknown\nVERSION_ID=1\n")
    with pytest.raises(ImageBuildError, match="unsupported"):
        detect(path)


def test_generation_capacity(prepared):
    builder, _, _, toolchain = prepared
    builder.maximum_generations = 3
    with pytest.raises(ImageBuildError, match="capacity"):
        builder.ensure(["consumer"], toolchain=toolchain)


def test_recipe_change_changes_generation(prepared):
    builder, _, _, toolchain = prepared
    first = builder.ensure(["consumer"], toolchain=toolchain)
    path = builder.package_dir / "consumer/integration.py"
    path.write_text("{'reviewed_note': 'initialization deferred'}")
    second = builder.ensure(["consumer"], toolchain=toolchain)
    assert first.generation != second.generation


def test_real_example_compilation_with_host_tools(tmp_path):
    """Native recipe check only: deliberately does not claim container isolation."""
    import os
    import shutil
    from examples.create_packages import create
    from zog.image_build.metadata import load_packages

    if not all(shutil.which(name) for name in ("cc", "ar")):
        pytest.skip("native C tools unavailable")
    package_dir = create(tmp_path / "package")

    class NativeRecipeRunner:
        def run(self, root, source, output, arguments, environment, log):
            arguments = [
                (
                    str(root / "usr/lib/libzog-number.a")
                    if a == "/usr/lib/libzog-number.a"
                    else (
                        "-I" + str(root / "usr/include") if a == "-I/usr/include" else a
                    )
                )
                for a in arguments
            ]
            with Path(log).open("ab") as stream:
                subprocess.run(
                    arguments,
                    cwd=source,
                    env={**os.environ, **environment, "DESTDIR": str(output.resolve())},
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=True,
                    timeout=60,
                )

    builder = ImageBuild(
        package_dir=package_dir,
        state_dir=tmp_path / "state",
        runner=NativeRecipeRunner(),
    )
    host = tmp_path / "host"
    host.mkdir()
    (host / "seed").write_text("native recipe test")
    seed = builder.import_bootstrap(host, {"test_only": True})
    packages = load_packages(package_dir)
    attempt = builder._candidate("native-recipe-test")
    built = builder._build_set(packages, ["number-print"], seed, attempt)
    builder._compose(packages, ["number-print"], built, attempt / "composed")
    binary = attempt / "composed/usr/bin/number-print"
    assert subprocess.check_output([binary], text=True).strip() == "42"
    assert not (attempt / "composed/usr/lib/libzog-number.a").exists()


def test_imported_host_symlink_target_is_inventoried(tmp_path):
    host = tmp_path / "host"
    (host / "usr/bin").mkdir(parents=True)
    (host / "usr/bin/compiler").write_text("compiler")
    (host / "bin").symlink_to("usr/bin")
    result = assemble(["/bin/compiler", "/bin"], tmp_path / "assembled", host_root=host)
    assert any(r["path"] == "usr/bin/compiler" for r in result)
    assert (tmp_path / "assembled/bin").is_symlink()


def test_manifest_stage_cannot_be_changed_without_identity(prepared):
    _, _, seed, _ = prepared
    path = seed.root.parent / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(kind="toolchain", stage=2, self_hosted=True)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ImageBuildError, match="kind mismatch"):
        read_selection(seed.root.parent)


def test_publication_failure_keeps_active(prepared, monkeypatch):
    builder, _, _, toolchain = prepared
    first = builder.ensure(["library"], toolchain=toolchain)
    import zog.image_build.engine as engine

    original = engine.os.rename

    def fail_publication(source, destination):
        if "publication" in str(source):
            raise OSError("injected publication storage fault")
        return original(source, destination)

    monkeypatch.setattr(engine.os, "rename", fail_publication)
    with pytest.raises(OSError):
        builder.ensure(["consumer"], toolchain=toolchain)
    assert (
        builder.state / "image-build/active"
    ).resolve() == first.root.parent.resolve()


def test_source_packaging_extracts_spec_without_execution(tmp_path, monkeypatch):
    from zog.image_build.developer.source_packaging import extract

    def entry(name, content):
        encoded = name.encode() + b"\0"
        fields = [1, 0o100644, 0, 0, 1, 0, len(content), 0, 0, 0, 0, len(encoded), 0]
        header = b"070701" + b"".join(f"{v:08x}".encode() for v in fields)
        return (
            header
            + encoded
            + b"\0" * ((-(len(header) + len(encoded))) % 4)
            + content
            + b"\0" * ((-len(content)) % 4)
        )

    spec = b"Name: example\n%post\ntouch /do-not-run\n"
    data = entry("example.spec", spec) + entry("TRAILER!!!", b"")

    def fake_rpm2cpio(command, stdout, **kwargs):
        stdout.write(data)

    monkeypatch.setattr(subprocess, "run", fake_rpm2cpio)
    destination = tmp_path / "packaging"
    assert extract(tmp_path / "example.src.rpm", destination) == ["example.spec"]
    assert (destination / "files/example.spec").read_bytes() == spec


def test_package_developer_tools_are_not_imported():
    result = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import zog.image_build,sys; print(any(n.startswith('zog.image_build.developer') or n in ('dnf','rpm') for n in sys.modules))",
        ],
        text=True,
        cwd=Path(__file__).resolve().parents[1],
    )
    assert result.strip() == "False"


def test_missing_box_control_adapter_fails_without_execution(tmp_path):
    with pytest.raises(ImageBuildError, match="integration is unavailable"):
        BoxControlRunner().run(
            tmp_path / "root",
            tmp_path / "source",
            tmp_path / "output",
            ["cc"],
            {},
            tmp_path / "log",
        )


def test_box_control_port_carries_isolation_and_completion(tmp_path):
    requests = []

    def execute(request):
        requests.append(request)
        return BuildExecutionResult(
            "runtime-id", "invocation-id", 0, True, "journal:invocation-id"
        )

    BoxControlRunner(execute=execute, timeout=90).run(
        tmp_path / "root",
        tmp_path / "source",
        tmp_path / "output",
        ["cc", "source.c"],
        {},
        tmp_path / "build.log",
    )
    request = requests[0]
    assert request.read_only_root and not request.network_access
    assert (
        request.timeout_seconds == 90
        and request.environment["DESTDIR"] == "/image-build/output"
    )
    assert json.loads((tmp_path / "build.execution.json").read_text())[
        "cleanup_complete"
    ]


@pytest.mark.parametrize(
    "exit_code,cleanup,error",
    [(1, True, "status 1"), (0, False, "cleanup is unresolved")],
)
def test_box_control_port_rejects_unsuccessful_completion(
    tmp_path, exit_code, cleanup, error
):
    runner = BoxControlRunner(
        execute=lambda request: BuildExecutionResult(
            "runtime", "invocation", exit_code, cleanup, "journal:invocation"
        )
    )
    with pytest.raises(ImageBuildError, match=error):
        runner.run(
            tmp_path / "root",
            tmp_path / "source",
            tmp_path / "output",
            ["cc"],
            {},
            tmp_path / "build.log",
        )


def test_interrupted_pipeline_does_not_create_a_fresh_attempt(prepared):
    builder, _, _, _ = prepared
    attempt = builder._candidate('image')
    builder._failed(attempt, KeyboardInterrupt())
    assert json.loads((attempt / 'status.json').read_text())['status'] == 'pending'
    with pytest.raises(ImageBuildError, match='unfinished attempt'):
        builder._candidate('image')


def test_pipeline_resume_keeps_snapshot_and_skips_completed_commands(prepared):
    builder, _, _, toolchain = prepared
    calls = []
    interrupted = [False]

    def execute(request):
        command, name = request.command
        if command == 'test' and not interrupted[0]:
            interrupted[0] = True
            raise KeyboardInterrupt('lost caller before this command')
        calls.append((command, name))
        if command == 'install':
            path = request.output / 'usr/share' / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        return BuildExecutionResult('runtime', 'invocation', 0, True, 'journal')

    builder.runner = BoxControlRunner(execute=execute)
    with pytest.raises(KeyboardInterrupt):
        builder.ensure(['consumer'], toolchain=toolchain)
    records = list((builder.state / 'image-build/pipelines').glob('*/pipeline.json'))
    pending = next(p for p in records if json.loads(p.read_text())['status'] == 'pending')
    with pytest.raises(ImageBuildError, match='unfinished pipeline'):
        builder.ensure(['consumer'], toolchain=toolchain)
    # A resumed pipeline must not pick up a newly edited recipe.
    (builder.package_dir / 'library/build.py').write_text("{'build': [['wrong-command']]}")
    result = builder.resume(pending.parent.name)
    assert (result.root / 'usr/share/consumer').read_text() == 'consumer'
    assert calls.count(('compile', 'library')) == 1
    assert all(c[0] != 'wrong-command' for c in calls)
    count = len(calls)
    assert builder.resume(pending.parent.name).generation == result.generation
    assert len(calls) == count


def test_pipeline_release_failure_resumes_without_rebuilding(prepared):
    builder, _, _, toolchain = prepared

    class Executor:
        def __init__(self): self.calls = []; self.fail = True
        def __call__(self, request):
            self.calls.append(request.command)
            if request.command[0] == 'install':
                p = request.output / 'usr/share/library'
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('library')
            return BuildExecutionResult('runtime', 'invocation', 0, True, 'journal')
        def release_resources(self, directory):
            assert (directory / 'result.json').exists()
            if self.fail:
                self.fail = False
                raise OSError('interrupted release')

    executor = Executor()
    builder.runner = BoxControlRunner(execute=executor)
    with pytest.raises(OSError): builder.ensure(['library'], toolchain=toolchain)
    pending = next(p for p in (builder.state / 'image-build/pipelines').glob('*/pipeline.json')
                   if json.loads(p.read_text())['status'] == 'pending')
    count = len(executor.calls)
    builder.resume(pending.parent.name)
    assert len(executor.calls) == count


def test_resume_rejects_changed_completed_package(prepared):
    builder, runner, _, toolchain = prepared
    runner.fail = 'compile'
    with pytest.raises(ImageBuildError): builder.ensure(['library'], toolchain=toolchain)
    pending = next(p for p in (builder.state / 'image-build/pipelines').glob('*/pipeline.json')
                   if json.loads(p.read_text())['status'] == 'pending')
    snapshot = pending.parent / 'package/library/build.py'
    snapshot.write_text("{'build': [['tampered']]}")
    with pytest.raises(ImageBuildError, match='snapshot changed'): builder.resume(pending.parent.name)


def test_bootstrap_resume_does_not_repeat_first_stage(tmp_path):
    packages = tmp_path / 'package'
    recipe(packages, 'first'); recipe(packages, 'second')
    host = tmp_path / 'seed'; host.mkdir(); (host / 'seed').write_text('seed')

    class InterruptingRunner(RecordingRunner):
        def run(self, root, source, output, arguments, environment, log):
            if arguments == ['compile', 'second'] and not getattr(self, 'interrupted', False):
                self.interrupted = True
                raise KeyboardInterrupt()
            super().run(root, source, output, arguments, environment, log)

    runner = InterruptingRunner()
    builder = ImageBuild(package_dir=packages, state_dir=tmp_path/'state', runner=runner)
    seed = builder.import_bootstrap(host, {'test': True})
    with pytest.raises(KeyboardInterrupt): builder.bootstrap(seed, [['first'], ['second']])
    pipeline = next((builder.state/'image-build/pipelines').iterdir()).name
    result = builder.resume(pipeline)
    assert result.manifest['stage'] == 2
    assert sum(args == ['compile', 'first'] for args, _ in runner.calls) == 1
    assert sum(args == ['cc', 'probe.c', '-o', '/image-build/output/probe'] for args, _ in runner.calls) == 2


def test_seed_check_is_not_a_promoted_toolchain(prepared):
    builder, _, seed, _ = prepared
    result = builder.verify_seed(['library'], host_bootstrap=seed)
    assert result.manifest['kind'] == 'seed-check'
    assert not (builder.state/'image-build/active').exists()
    with pytest.raises(ImageBuildError, match='second-stage'):
        builder.ensure(['consumer'], toolchain=result)


def test_completed_nonzero_command_is_not_reexecuted(tmp_path):
    calls = []
    def execute(request):
        calls.append(request)
        return BuildExecutionResult('runtime', 'invocation', 7, True, 'journal')
    runner = BoxControlRunner(execute=execute)
    for _ in range(2):
        with pytest.raises(ImageBuildError, match='status 7'):
            runner.run(tmp_path/'root', tmp_path/'source', tmp_path/'output', ['false'], {}, tmp_path/'build.log')
    assert len(calls) == 1


def test_resume_finishes_after_publication_before_pipeline_commit(prepared, monkeypatch):
    builder, runner, _, toolchain = prepared
    original = builder._activate
    once = [True]
    def interrupted(selection, name):
        if name == 'active' and once[0]:
            once[0] = False
            raise KeyboardInterrupt('published, not activated')
        original(selection, name)
    monkeypatch.setattr(builder, '_activate', interrupted)
    with pytest.raises(KeyboardInterrupt): builder.ensure(['library'], toolchain=toolchain)
    pending = next(p for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json')
                   if json.loads(p.read_text())['status'] == 'pending')
    count = len(runner.calls)
    builder.resume(pending.parent.name)
    assert len(runner.calls) == count
    assert all(json.loads(p.read_text())['status'] == 'complete'
               for p in (builder.state/'image-build/attempts').glob('*/status.json'))
    builder.ensure(['consumer'], toolchain=toolchain)


def test_configuration_rejects_nested_state_and_root_execution(tmp_path):
    from zog.image_build.configuration import configured_runner
    project = tmp_path/'project'
    raw = dict(project_root=str(project), socket_path='/run/zog/root-control.sock',
               execution_user_id=1001, execution_group_id=1001, startup_timeout_seconds=5,
               execution_timeout_seconds=30, termination_grace_seconds=3, wait_timeout_seconds=0,
               transport_timeout_seconds=10, resource_limits={'thread-count-maximum':32,'memory-maximum-bytes':100000000})
    path = tmp_path/'config.json'; path.write_text(json.dumps(raw))
    with pytest.raises(ImageBuildError, match='state-dir'):
        configured_runner(path, project/'state/image-build')
    runner = configured_runner(path, project/'state')
    assert runner.timeout == 30 and runner.execute.wait_timeout_seconds == 0
    raw['execution_user_id'] = 0; path.write_text(json.dumps(raw))
    with pytest.raises(ImageBuildError, match='nonzero'):
        configured_runner(path, project/'state')


def test_changed_output_blocks_package_reuse_after_release_error(prepared):
    builder, runner, _, toolchain = prepared
    def release(directory): raise OSError('release reply lost')
    builder._release_resources = release
    with pytest.raises(OSError): builder.ensure(['library'], toolchain=toolchain)
    pending = next(p for p in (builder.state/'image-build/pipelines').glob('*/pipeline.json')
                   if json.loads(p.read_text())['status'] == 'pending')
    attempt = json.loads(pending.read_text())['attempts']['image']
    (builder.state/'image-build/attempts'/attempt/'packages/library/output/usr/share/library').write_text('tampered')
    with pytest.raises(ImageBuildError, match='outputs changed'):
        builder.resume(pending.parent.name)


def test_toolchain_overlay_preserves_shared_directory_modes(tmp_path):
    source, root = tmp_path/'output', tmp_path/'toolchain'
    (source/'usr/lib').mkdir(parents=True)
    (root/'usr/lib').mkdir(parents=True)
    (source/'usr/lib').chmod(0o755)
    (root/'usr/lib').chmod(0o555)
    (source/'usr/lib/library.a').write_bytes(b'archive')
    with pytest.raises(ImageBuildError, match='directory mode conflict'):
        merge(source, root)
    merge(source, root, preserve_existing_directories=True)
    assert (root/'usr/lib').stat().st_mode & 0o777 == 0o555
    assert (root/'usr/lib/library.a').read_bytes() == b'archive'
    with pytest.raises(ImageBuildError, match='ownership conflict'):
        merge(source, root, preserve_existing_directories=True)


def test_interrupted_read_only_seed_preparation_can_resume(tmp_path, monkeypatch):
    import zog.image_build.engine as engine
    packages = tmp_path/'package'; recipe(packages, 'library')
    host = tmp_path/'host'; (host/'usr/lib').mkdir(parents=True)
    (host/'usr/lib/seed').write_text('seed'); (host/'usr/lib').chmod(0o555)
    builder = ImageBuild(package_dir=packages, state_dir=tmp_path/'state', runner=RecordingRunner())
    seed = builder.import_bootstrap(host, {'test':True})
    original = engine.stage
    def interrupt(*args, **kwargs): raise KeyboardInterrupt('during source staging')
    monkeypatch.setattr(engine, 'stage', interrupt)
    with pytest.raises(KeyboardInterrupt): builder.verify_seed(['library'], host_bootstrap=seed)
    pipeline = next((builder.state/'image-build/pipelines').iterdir()).name
    monkeypatch.setattr(engine, 'stage', original)
    result = builder.resume(pipeline)
    assert (result.root/'usr/share/library').read_text() == 'library'

@pytest.mark.parametrize('extra,required,error', [
    ('etc/gprofng.rc', ['etc/gprofng.rc'], None),
    ('etc/unexpected.conf', [], 'paths outside allowed locations'),
    (None, ['etc/gprofng.rc'], 'missing required paths'),
])
def test_output_policy_specific_configuration_allowance(prepared, extra, required, error):
    builder, runner, _, toolchain = prepared
    policy = {'trees': ['usr', 'etc/gprofng.rc'],
              'required': ['usr/share/consumer'] + required}
    (builder.package_dir / 'consumer/produce-manifest.py').write_text(repr(policy))
    original_run = runner.run
    def run(root, source, output, arguments, environment, log):
        original_run(root, source, output, arguments, environment, log)
        if arguments == ['install', 'consumer'] and extra:
            target = output / extra
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('configuration')
    runner.run = run
    if error:
        with pytest.raises(ImageBuildError, match=error) as caught:
            builder.ensure(['consumer'], toolchain=toolchain)
        assert (extra or 'etc/gprofng.rc') in str(caught.value)
    else:
        builder.ensure(['consumer'], toolchain=toolchain)

@pytest.mark.parametrize('drift', [False, True])
def test_dependency_replacement_requires_recorded_bootstrap_bytes(tmp_path, drift):
    from zog.image_build.metadata import identity
    host = tmp_path/'host'
    (host/'usr/share').mkdir(parents=True)
    (host/'usr/share/library').write_text('temporary')
    records = [dict(r, path='sysroot/'+r['path']) for r in inventory(host)]
    if drift:
        records[-1]['sha256'] = '0'*64
    old = {'inputs': {'fixture': 'temporary-library'}, 'outputs': records}
    old['identity'] = identity(old)
    packages = tmp_path/'package'
    recipe(packages, 'library')
    recipe(packages, 'consumer', build=('library',))
    runner = RecordingRunner()
    original = runner.run
    def run(root, source, output, arguments, environment, log):
        if arguments == ['compile', 'consumer']:
            assert (root/'usr/share/library').read_text() == 'library'
        original(root, source, output, arguments, environment, log)
    runner.run = run
    builder = ImageBuild(package_dir=packages, state_dir=tmp_path/'state', runner=runner,
                        dependency_replacements={'library': old})
    seed = builder.import_bootstrap(host, {'fixture': True})
    if drift:
        with pytest.raises(ImageBuildError, match='replacement input changed'):
            builder.verify_seed(['consumer'], host_bootstrap=seed)
        assert not any(args == ['compile', 'consumer'] for args, _ in runner.calls)
    else:
        result = builder.verify_seed(['consumer'], host_bootstrap=seed)
        assert result.manifest['inputs']['dependency_replacements'] == {'library': old['identity']}
        assert builder._policy()['dependency_replacements']['library'] == old
    assert (seed.root/'usr/share/library').read_text() == 'temporary'
