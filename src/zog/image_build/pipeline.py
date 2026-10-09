"""Caller-owned pipeline intent and continuation; controller owns command execution."""
import json
import shutil
import uuid
from pathlib import Path

from .errors import ImageBuildError
from .filesystem import inventory, sync_tree, write_json, ensure_directory
from .metadata import identity, load_packages


class PipelineMixin:
    def bootstrap(self, host_bootstrap, stages):
        return self._new_pipeline('bootstrap', host_bootstrap, stages=stages)

    def ensure(self, targets, *, toolchain):
        return self._new_pipeline('image', toolchain, targets=list(targets))

    def verify_seed(self, targets, *, host_bootstrap):
        """Integration check only; never promotes a seed to a self-hosted toolchain."""
        return self._new_pipeline('seed-check', host_bootstrap, targets=list(targets))

    def verify_native(self, targets, *, toolchain):
        """Validation only; a temporary native compiler is not a promoted toolchain."""
        return self._new_pipeline('native-check', toolchain, targets=list(targets))

    def _policy(self):
        execute = getattr(self.runner, 'execute', None)
        policy = {"controller": execute.configuration(), "execution_timeout_seconds": self.runner.timeout} if hasattr(execute, "configuration") else None
        if self.dependency_replacements:
            policy = dict(policy or {}, dependency_replacements=self.dependency_replacements)
        if self.provenance is not None:
            policy=dict(policy or {},provenance=self.provenance.configuration())
        if self.source_mirror is not None:
            policy=dict(policy or {},source_mirror=self.source_mirror.configuration())
        return policy

    def prepare_pipeline(self, operation, selection, *, owner=None, **arguments):
        """Durably allocate and bind a pipeline without executing its first command.

        Remote/disconnected callers use this to persist the returned pipeline_id
        before any controller submission. Existing synchronous entry points still
        prepare and continue while holding the same image-build lock.
        """
        with self.locked():
            return self._prepare_pipeline(operation, selection, owner=owner, **arguments)

    def _prepare_pipeline(self, operation, selection, *, owner=None, **arguments):
        if operation not in {'bootstrap', 'image', 'seed-check', 'native-check'}:
            raise ImageBuildError('unknown pipeline operation')
        if owner is not None:
            try:
                owner = json.loads(json.dumps(owner, allow_nan=False))
            except (TypeError, ValueError) as error:
                raise ImageBuildError('pipeline owner metadata must be JSON data') from error
            if not isinstance(owner, dict):
                raise ImageBuildError('pipeline owner metadata must be an object')
        from .pins import validate
        pins = validate(self.package_dir, load_packages(self.package_dir))
        pipelines = self.state / 'image-build' / 'pipelines'
        ensure_directory(pipelines)
        for path in pipelines.glob('*/pipeline.json'):
            if json.loads(path.read_text())['status'] in ('prepared', 'running', 'pending'):
                raise ImageBuildError(f'unfinished pipeline {path.parent.name}; use resume')
        for path in (self.state / 'image-build' / 'attempts').glob('*/status.json'):
            if json.loads(path.read_text())['status'] in ('running', 'pending'):
                raise ImageBuildError(f'unfinished attempt {path.parent}; use its pipeline resume identity')
        pipeline_id = uuid.uuid4().hex
        directory = pipelines / pipeline_id
        ensure_directory(directory)
        # Snapshot definitions, including optional integration metadata. Sources
        # remain checksum-verified by the source cache, not implicitly copied.
        shutil.copytree(self.package_dir, directory / 'package', symlinks=False)
        if validate(directory / 'package', load_packages(directory / 'package')) != pins:
            raise ImageBuildError('source pins changed while snapshotting')
        sync_tree(directory)
        record = dict(schema=1, pipeline_id=pipeline_id, operation=operation,
                      selection=str(Path(selection.root).resolve().parent),
                      arguments=arguments, recipes=inventory(directory / 'package'),
                      policy=self._policy(), source_pins=identity(pins), attempts={}, status='prepared')
        if owner is not None:
            record['owner'] = owner
        write_json(directory / 'pipeline.json', record)
        return json.loads(json.dumps(record))

    def _new_pipeline(self, operation, selection, **arguments):
        with self.locked():
            record = self._prepare_pipeline(operation, selection, **arguments)
            return self._continue_pipeline(self._pipeline_directory(record['pipeline_id']), record)

    def _pipeline_directory(self, pipeline_id):
        if not isinstance(pipeline_id, str) or len(pipeline_id) != 32 or any(c not in '0123456789abcdef' for c in pipeline_id):
            raise ImageBuildError('invalid pipeline identity')
        return self.state / 'image-build' / 'pipelines' / pipeline_id

    def inspect_pipeline(self, pipeline_id):
        return json.loads((self._pipeline_directory(pipeline_id) / 'pipeline.json').read_text())

    def resume(self, pipeline_id):
        with self.locked():
            directory = self._pipeline_directory(pipeline_id)
            record = self.inspect_pipeline(pipeline_id)
            if record.get('released'):
                raise ImageBuildError('pipeline resources explicitly released; cannot resume')
            return self._continue_pipeline(directory, record)

    def _continue_pipeline(self, directory, record):
        from .engine import read_selection
        if record['schema'] != 1 or record['pipeline_id'] != directory.name:
            raise ImageBuildError('invalid pipeline record')
        if record['recipes'] != inventory(directory / 'package'):
            raise ImageBuildError('pipeline recipe snapshot changed')
        if 'source_pins' in record:
            from .pins import validate
            if identity(validate(directory/'package', load_packages(directory/'package'))) != record['source_pins']:
                raise ImageBuildError('pipeline monthly pin identity changed')
        if record['policy'] != self._policy():
            raise ImageBuildError('pipeline execution policy changed')
        if record['status'] == 'complete':
            return self._verify_generation(read_selection(self.state / 'image-build' / 'generations' / record['generation']))
        old_packages = self.package_dir
        self.package_dir = directory / 'package'
        self._pipeline_path, self._pipeline_record = directory, record
        try:
            record['status'] = 'running'
            write_json(directory / 'pipeline.json', record)
            selection = read_selection(record['selection'])
            if record['operation'] == 'bootstrap':
                result = self._bootstrap(selection, record['arguments']['stages'])
            elif record['operation'] in ('image', 'seed-check', 'native-check'):
                result = self._ensure(record['arguments']['targets'], toolchain=selection,
                                      seed_check=record['operation'] == 'seed-check',
                                      native_check=record['operation'] == 'native-check')
            else:
                raise ImageBuildError('unknown pipeline operation')
            snapshot = self._publish_observation_snapshot(result)
            for name in record['attempts'].values():
                status_path = self.state / 'image-build' / 'attempts' / name / 'status.json'
                status = json.loads(status_path.read_text())
                if status['status'] != 'complete':
                    write_json(status_path, {'status': 'complete', 'generation': result.generation})
            record.update(status='complete', generation=result.generation)
            if snapshot is not None:
                record['observation_snapshot'] = snapshot['snapshot']
            record.pop('error', None)
            write_json(directory / 'pipeline.json', record)
            return result
        except BaseException as error:
            # Never turn an uncertain execution/storage failure into permission
            # for a fresh pipeline. Explicit resume preserves all command IDs.
            record.update(status='pending', error=str(error))
            try:
                write_json(directory / 'pipeline.json', record)
            except OSError:
                pass
            if hasattr(error, 'add_note'):
                error.add_note(f'image-build pipeline {directory.name}; resume this identity')
            raise
        finally:
            self.package_dir = old_packages
            self._pipeline_path = self._pipeline_record = None

    def _pipeline_candidate(self, kind):
        record = self._pipeline_record
        if kind not in record['attempts']:
            record['attempts'][kind] = kind + '-' + uuid.uuid4().hex
            write_json(self._pipeline_path / 'pipeline.json', record)
        directory = self.state / 'image-build' / 'attempts' / record['attempts'][kind]
        ensure_directory(directory)
        if not (directory / 'status.json').exists():
            write_json(directory / 'status.json', dict(status='running', kind=kind,
                       pipeline_id=record['pipeline_id']))
        return directory

    def _release_resources(self, directory):
        execute = getattr(self.runner, 'execute', None)
        if hasattr(execute, 'release_resources'):
            execute.release_resources(directory)

    def release_pipeline(self, pipeline_id):
        """Explicitly abandon continuation, retaining caller files and diagnostics.

        Controller release refuses any command without proven process cleanup.
        Interrupted release resumes through the same resource identities.
        """
        with self.locked():
            directory = self._pipeline_directory(pipeline_id)
            record = self.inspect_pipeline(pipeline_id)
            if record['policy'] != self._policy():
                raise ImageBuildError('pipeline execution policy changed')
            if record.get('released') and record.get('status') == 'released':
                return record
            record['released'] = True
            write_json(directory / 'pipeline.json', record)
            for name in record['attempts'].values():
                attempt = self.state / 'image-build' / 'attempts' / name
                for registration in attempt.rglob('controller-resources.json'):
                    owner = registration.parent
                    resource = json.loads(registration.read_text())
                    output = Path(resource['registration']['output_directory'])
                    sync_tree(output)
                    write_json(owner / 'retained-output.json', {'outputs': inventory(output)})
                    self._release_resources(owner)
                write_json(attempt / 'status.json', {'status': 'released'})
            record['status'] = 'released'
            write_json(directory / 'pipeline.json', record)
            return record
