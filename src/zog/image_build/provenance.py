"""Opt-in package provenance. Required owner bindings, separate from optional trace.

Caller holds the image-build lock. Store/artifacts are local owner-controlled state.
This adapter never decides execution recovery or reconstructs legacy inputs.
"""
import ast
from datetime import datetime, timezone
import hashlib
import json
import os
import stat
from pathlib import Path
import tempfile

from .errors import ImageBuildError
from .filesystem import ensure_directory, sync_directory, write_json
from .metadata import identity


def _library():
    try:
        import zog.build_record as build_record
        return build_record
    except ImportError:
        raise ImageBuildError('provenance capture requires build-record') from None


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')


class Provenance:
    """Configure with a captured pin descriptor, explicit host/project and retry IDs."""
    def __init__(self, state_dir, *, host_id, project_id, pin, retry_of=None, generation_contract="rootfs-v1"):
        self.state = Path(state_dir).resolve()
        self.root = self.state / 'image-build/build-record'
        self.host_id, self.project_id = host_id, project_id
        if not all(isinstance(v, str) and v and len(v) <= 256 for v in (host_id, project_id)):
            raise ImageBuildError('provenance requires explicit host/project identities')
        if generation_contract not in (None, 'rootfs-v1'):
            raise ImageBuildError('unsupported generation provenance contract')
        self.generation_contract = generation_contract
        self.pin = json.loads(json.dumps(pin))
        self.retry_of = dict(retry_of or {})
        self.library = _library()
        self.library.make_record('source-selection',dict(package='validation',pin=self.pin,
            upstream=[{'repository':'unknown','revision':None}],
            archives=[dict(name='validation',digest=self.pin.get('digest'),size=0)]),gaps=['validation only'])
        from zog.build_record.model import digest
        for key,value in self.retry_of.items():
            if not isinstance(key,str) or not key: raise ImageBuildError('invalid retry package')
            digest(value)
        self.store = self.library.Store(self.root / 'records')
        ensure_directory(self.root / 'records')
        ensure_directory(self.root / 'artifacts')

    def configuration(self):
        result = dict(schema=1, host_id=self.host_id, project_id=self.project_id,
                      pin=self.pin, retry_of=self.retry_of)
        if self.generation_contract is not None:
            result.update(schema=2, generation_contract=self.generation_contract)
        return result

    @classmethod
    def from_configuration(cls, state_dir, config):
        base = {'schema','host_id','project_id','pin','retry_of'}
        if type(config.get('schema')) is not int:
            raise ImageBuildError('unsupported provenance configuration')
        if set(config) == base and config['schema'] == 1:
            return cls(state_dir, generation_contract=None,
                       **{k:v for k,v in config.items() if k != 'schema'})
        if (set(config) == base | {'generation_contract'} and config['schema'] == 2
                and config['generation_contract'] == 'rootfs-v1'):
            return cls(state_dir, **{k:v for k,v in config.items() if k != 'schema'})
        raise ImageBuildError('unsupported provenance configuration')

    @staticmethod
    def capture_pin(state_dir, path, *, repository, revision, repository_path):
        """Retain exact original pin bytes before configuring a new pipeline."""
        root = Path(state_dir).resolve() / 'image-build/build-record'
        ensure_directory(root / 'artifacts')
        with Path(path).open('rb') as stream:
            raw = stream.read(1024*1024+1)
        if len(raw) > 1024 * 1024:
            raise ImageBuildError('original monthly pin exceeds 1 MiB')
        parsed = ast.literal_eval(raw.decode())
        pin = dict(month=parsed['date'], repository=repository, revision=revision,
                   path=repository_path, digest='sha256:'+hashlib.sha256(raw).hexdigest())
        # Validate descriptor using the canonical schema, without storing a fake source.
        lib = _library()
        lib.make_record('source-selection', dict(package='validation',pin=pin,
            upstream=[{'repository':'unknown','revision':None}],
            archives=[dict(name='pin-validation',digest=pin['digest'],size=len(raw))]), gaps=['validation only'])
        _publish_artifact(root, raw=raw, expected=pin['digest'])
        return pin

    def _bytes(self, name, value):
        raw = json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()
        return _publish_artifact(self.root, raw=raw, name=name)

    def _file(self, name, path, expected=None):
        return _publish_artifact(self.root, source=Path(path), expected=expected, name=name)

    def _record(self, kind, data, gaps=None):
        return self.store.put(self.library.make_record(kind, data, gaps=gaps))

    def _binding(self, path):
        raw = json.loads(Path(path).read_text())
        if raw.get('schema') != 1 or raw.get('host_id') != self.host_id or raw.get('project_id') != self.project_id:
            raise ImageBuildError('provenance binding scope differs')
        return raw

    def _verify(self, roots):
        bundle = self.store.bundle(roots)
        from zog.build_record.model import artifact_references
        paths = {a['digest']: self.root/'artifacts'/a['digest'][7:]
                 for r in bundle['records'].values() for a in artifact_references(r)}
        if any(path.is_symlink() for path in paths.values()):
            raise ImageBuildError('retained provenance artifact symlink is unsupported')
        report = self.library.verify_artifacts(bundle, paths)
        if any(a['status'] != 'verified' for a in report['artifact_verification']):
            raise ImageBuildError('required provenance artifact unavailable or changed')
        return bundle

    def verify_output(self, binding, package, result):
        """Validate a retained output/result against the actual owner inventory."""
        if not isinstance(binding, dict) or set(binding) != {'output', 'result'}:
            raise ImageBuildError('invalid package provenance reference')
        roots = [binding['output']] + ([binding['result']] if binding['result'] else [])
        bundle = self._verify(roots)
        output = bundle['records'][binding['output']]
        if output['kind'] != 'package-output' or output['data']['package'] != package:
            raise ImageBuildError('package provenance output differs')
        data = output['data']
        if binding['result']:
            final = bundle['records'][binding['result']]
            if (final['kind'] != 'attempt-result' or final['data']['outcome'] != 'succeeded'
                    or final['data']['outputs'] != [binding['output']]
                    or final['data']['attempt'] != data['attempt']):
                raise ImageBuildError('package provenance result differs')
            start = bundle['records'][data['attempt']]['data']
            captured = bundle['records'][start['inputs']]['data']
            if captured['options'].get('owner_inputs') != identity(result['inputs']):
                raise ImageBuildError('package provenance inputs differ')
            name = 'package-output-inventory.json'
        else:
            if data['attempt'] is not None:
                raise ImageBuildError('known package provenance lost its result')
            name = 'legacy-output-inventory.json'
        raw = json.dumps(result['outputs'], sort_keys=True, separators=(',', ':'),
                         ensure_ascii=True, allow_nan=False).encode()
        expected = dict(name=name, digest='sha256:'+hashlib.sha256(raw).hexdigest(), size=len(raw))
        if data['artifacts'] != [expected]:
            raise ImageBuildError('package provenance inventory differs')
        self.verify_scope(bundle)
        return binding

    def verify_scope(self, bundle):
        for record in bundle['records'].values():
            if record['kind'] == 'attempt-start':
                try:
                    owner = json.loads(record['data']['attempt_id'])
                except (ValueError, TypeError):
                    raise ImageBuildError('provenance attempt scope is invalid') from None
                if (not isinstance(owner, list) or len(owner) != 4
                        or owner[:2] != [self.host_id, self.project_id]):
                    raise ImageBuildError('provenance attempt scope differs')

    def generation_roots(self, *, output=None, attempt=None, limit=100):
        """Read bounded owner indexes; verify every entry against its generation."""
        from .generation_provenance import generation_roots
        return generation_roots(self, output=output, attempt=attempt, limit=limit)

    def _verify_staged_patches(self, package_dir, patches):
        from .licensing import safe_path
        root = package_dir / 'source'
        for patch in patches:
            path = root / safe_path(patch['name'])
            if any(part.is_symlink() for part in (path, *path.parents)):
                raise ImageBuildError('staged patch must not traverse a symlink')
            self._file(patch['name'], path, patch['digest'])

    def prepare(self, builder, package, package_dir, attempt, inputs, toolchain, built, dependencies):
        path = package_dir/'provenance.json'
        if builder.dependency_replacements:
            raise ImageBuildError('provenance for dependency replacements requires an explicit replacement adapter')
        if builder.state.resolve() != self.state:
            raise ImageBuildError('provenance state scope differs')
        owner_id = json.dumps([self.host_id,self.project_id,attempt.name,package.name],separators=(',',':'))
        # Credentials are not provenance materials. Reject rather than mutate build facts.
        from .trace_records import sanitize
        execution_policy=dict(builder._policy() or {})
        execution_policy.pop('provenance',None)
        resolved = dict(steps=package.steps,environment=package.environment,policy=execution_policy,
                        runner={'class':type(builder.runner).__module__+'.'+type(builder.runner).__qualname__,
                                'timeout_seconds':getattr(builder.runner,'timeout',None)})
        if (sanitize(resolved) != json.loads(json.dumps(resolved))
                or sanitize(package.source_provenance) != package.source_provenance):
            raise ImageBuildError('sensitive values cannot be persisted as provenance')
        if path.exists():
            binding = self._binding(path)
            if binding['attempt_id'] != owner_id or binding['owner_inputs'] != identity(inputs):
                raise ImageBuildError('prepared provenance binding changed')
            bundle=self._verify([binding.get('result') or binding['prepared']])
            captured=bundle['records'][binding['inputs']]['data']
            recipe=json.loads((self.root/'artifacts'/captured['recipe']['digest'][7:]).read_bytes())
            if recipe['resolved']!=json.loads(json.dumps(resolved)):
                raise ImageBuildError('resolved provenance execution settings changed')
            for asset in recipe['files']:
                name=asset['name']
                if name.startswith('package/'):
                    source_path=builder.package_dir/package.name/name.removeprefix('package/')
                elif name.startswith('image_build/'):
                    source_path=Path(__file__).parent/name.removeprefix('image_build/')
                else:
                    source_path=builder.package_dir/'commit-pin.py'
                self._file(name,source_path,asset['digest'])
            self._verify_staged_patches(package_dir, captured['patches'])
            if binding.get('result'):
                final = self.store.get(binding['result'])['data']
                if final['outcome'] != 'succeeded':
                    raise ImageBuildError('final failed provenance requires a new explicit retry attempt')
            return binding
        # Never retrofit a prepared/accepted legacy command with current provenance.
        if list(package_dir.rglob('*.controller.json')) or list(package_dir.rglob('*.execution.json')):
            raise ImageBuildError('existing execution has no prepared provenance; keep it legacy')
        pin_path = self.root/'artifacts'/self.pin['digest'][7:]
        with pin_path.open('rb') as stream:
            pin_raw=stream.read(1024*1024+1)
        if len(pin_raw)>1024*1024: raise ImageBuildError('retained monthly pin exceeds limit')
        if 'sha256:'+hashlib.sha256(pin_raw).hexdigest() != self.pin['digest']:
            raise ImageBuildError('original monthly pin bytes changed')
        original = ast.literal_eval(pin_raw.decode())
        selected = ast.literal_eval((builder.package_dir/'commit-pin.py').read_text())
        if selected.get('monthly_identity') != identity(original) or selected.get('date') != self.pin['month']:
            raise ImageBuildError('materialized monthly pins differ from original provenance pin')
        entry = selected['packages'][package.name]
        if entry['sources'] != list(package.sources) or original['packages'][entry['project']]['recipes'][entry['recipe']] != entry['sources']:
            raise ImageBuildError('package sources differ from original monthly selection')
        archives = [self._file(source['destination'], self.state/'image-build/sources'/source['sha256'],
                    'sha256:'+source['sha256']) for source in package.sources]
        from .source_provenance import upstream_for, patch_sources
        declared_patches, patch_gaps = patch_sources(package, self.state)
        patches = [self._file(patch['source']['destination'],
                   self.state/'image-build/sources'/patch['source']['sha256'],
                   'sha256:'+patch['source']['sha256']) for patch in declared_patches]
        self._verify_staged_patches(package_dir, patches)
        if package.source_provenance is None:
            gaps = ['Upstream commit revisions are not captured by this adapter; archive bytes are pinned.']
            sources = [self._record('source-selection', dict(package=package.name,pin=self.pin,
                upstream=[dict(repository='not-captured',revision=None)],archives=archives), gaps)]
        else:
            sources = []
            for spec, archive in zip(package.sources, archives):
                upstream, gaps = upstream_for(package.source_provenance, spec)
                sources.append(self._record('source-selection', dict(package=package.name,
                    pin=self.pin, upstream=upstream, archives=[archive]), gaps))
        # Capture a complete package recipe plus builder implementation bytes. The
        # manifest is a retained artifact; constituent file bytes are retained too.
        recipe_files = []
        for directory, prefix in ((builder.package_dir/package.name,'package'), (Path(__file__).parent,'image_build')):
            for file in sorted(directory.rglob('*')):
                if file.is_symlink(): raise ImageBuildError('recipe/implementation symlinks are not supported for provenance')
                if file.is_file() and '__pycache__' not in file.parts and file.suffix != '.pyc':
                    recipe_files.append(self._file(prefix+'/'+file.relative_to(directory).as_posix(), file))
        recipe_files.append(self._file('materialized-commit-pin.py',builder.package_dir/'commit-pin.py'))
        recipe = self._bytes('resolved-recipe.json',dict(files=recipe_files,resolved=resolved))
        materials = recipe_files + [self._file('prepared-root.json',package_dir/'prepared.json'),
                                   self._bytes('toolchain-manifest.json',toolchain.manifest)]
        bindings = []
        for name in dependencies:
            dep = built[name].get('provenance')
            if not dep:
                dep = self.legacy_output(name,built[name])
            bindings.append(dict(output=dep['output'],result=dep.get('result')))
        from zog.build_record.model import ENVIRONMENT
        environment = {'PATH':'/usr/bin:/bin:/usr/sbin:/sbin','LANG':'C','LC_ALL':'C',**package.environment}
        excluded = sorted(set(environment)-ENVIRONMENT)
        input_gaps = ['Package output is represented by a verified inventory artifact; output file bytes are retained by image-build, not this artifact store.',
                      'Controller/runtime implementation bytes, custom execution callbacks and host kernel are not captured.',
                      *patch_gaps]
        if excluded: input_gaps.append('Environment outside the canonical allowlist: '+', '.join(excluded))
        if package.integration.get('test_fixtures'):
            raise ImageBuildError('provenance for dynamic test fixtures requires a fixture-material adapter')
        build_inputs = self._record('build-inputs',dict(package=package.name,
            step=package.integration.get('stage_id','package-build'),purpose='package',sources=sources,recipe=recipe,
            patches=patches, target=inputs['architecture'], options={'recipe_identity':package.fingerprint,'owner_inputs':identity(inputs),
                     'toolchain_generation':toolchain.generation,
                     'dependency_identities':json.dumps(inputs['dependencies'],sort_keys=True,separators=(',',':'))},
            environment={k:v for k,v in environment.items() if k in ENVIRONMENT},materials=materials,dependencies=bindings),input_gaps)
        previous = self.retry_of.get(package.name)
        if previous:
            prior=self.store.get(previous)
            if prior['kind'] != 'attempt-result' or prior['data']['outcome'] not in ('failed','cancelled'):
                raise ImageBuildError('retry must name a final failed/cancelled result')
            prior_start=self.store.get(prior['data']['attempt'])
            prior_inputs=self.store.get(prior_start['data']['inputs'])
            if prior_inputs['data']['package'] != package.name:
                raise ImageBuildError('retry package differs')
        start_data=dict(attempt_id=owner_id,inputs=build_inputs,retry_of=previous)
        preparing=package_dir/'provenance-preparing.json'
        if preparing.exists():
            start_record=json.loads(preparing.read_text())
            if {k:v for k,v in start_record['data'].items() if k!='prepared_at'} != start_data:
                raise ImageBuildError('provenance preparation intent changed')
        else:
            start_record=self.library.make_record('attempt-start',dict(start_data,prepared_at=_now()))
            write_json(preparing,start_record)
        prepared=self.store.put(start_record)
        self._verify([prepared])
        binding=dict(schema=1,host_id=self.host_id,project_id=self.project_id,attempt_id=owner_id,
            build_id='attempt:'+attempt.name,package=package.name,owner_inputs=identity(inputs),
            prepared=prepared,inputs=build_inputs,result=None,output=None)
        write_json(path,binding)  # Required durable pointer before any runner call.
        return binding

    def legacy_output(self, name, result):
        output=self._record('package-output',dict(package=name,attempt=None,
            artifacts=[self._bytes('legacy-output-inventory.json',result['outputs'])]),
            ['Legacy output: no captured producing attempt; no current pins/recipes substituted.'])
        return dict(output=output,result=None)

    def finish(self, package_dir, *, result=None, outcome=None, summary=None):
        path=package_dir/'provenance.json'
        binding=self._binding(path)
        expected=json.dumps([self.host_id,self.project_id,package_dir.parent.parent.name,package_dir.name],separators=(',',':'))
        if (binding.get('attempt_id') != expected or binding.get('package') != package_dir.name
                or binding.get('build_id') != 'attempt:'+package_dir.parent.parent.name):
            raise ImageBuildError('package producing identity differs from owner')
        if binding.get('result'):
            bundle=self._verify([binding['result']])
            final=bundle['records'][binding['result']]
            if (final['kind']!='attempt-result' or final['data']['attempt']!=binding['prepared']
                    or final['data']['outputs']!=([binding['output']] if binding.get('output') else [])):
                raise ImageBuildError('final provenance binding differs')
            if result is not None and final['data']['outcome']!='succeeded':
                raise ImageBuildError('failed attempt cannot accept outputs')
            return binding
        output=None
        if result is not None:
            outcome='succeeded'
            output=self._record('package-output',dict(package=binding['package'],attempt=binding['prepared'],
                artifacts=[self._bytes('package-output-inventory.json',result['outputs'])]))
        if outcome not in ('succeeded','failed','cancelled'):
            raise ImageBuildError('unresolved execution cannot finalize provenance')
        jobs=[]
        for file in sorted(package_dir.rglob('*.controller.json')):
            raw=json.loads(file.read_text())
            job=raw['job_id']
            if hashlib.sha256(raw['request_id'].encode()).hexdigest()[:32] != job:
                raise ImageBuildError('controller identity differs while finalizing provenance')
            jobs.append(dict(host_id=self.host_id,job_id=job))
        # Stage deterministic finalization intent first, including its timestamp.
        # A lost response can replay the same record, never a new final result.
        intent=package_dir/'provenance-finalizing.json'
        data=dict(attempt=binding['prepared'],outcome=outcome,outputs=[output] if output else [],
            jobs=jobs,traces=[dict(host_id=self.host_id,build_id=binding['build_id'])],
            summary=summary or 'image-build verified package outputs')
        if intent.exists():
            saved=json.loads(intent.read_text())
            if {k:v for k,v in saved['data'].items() if k != 'finished_at'} != data:
                raise ImageBuildError('provenance finalization intent changed')
            record=saved
        else:
            record=self.library.make_record('attempt-result',dict(data,finished_at=_now()),
                gaps=[] if jobs else ['No controller job identity captured by the configured runner.'])
            write_json(intent,record)
        final=self.store.put(record)
        self._verify([final])
        binding.update(result=final,output=output)
        write_json(path,binding)
        return binding

    def command_failed(self, package_dir, log, error):
        completion=Path(log).with_suffix('.execution.json')
        if completion.exists():
            record=json.loads(completion.read_text())
            if type(record.get('exit_code')) is int and record['exit_code'] != 0:
                self.finish(package_dir,outcome='failed',summary='Package command exited nonzero; inspect retained trace.')
                return
        record=getattr(error,'record',{})
        outcome=record.get('outcome')
        if record.get('state') == 'completed' and outcome in ('nonzero-exit','signal','timeout','fault','cancelled'):
            self.finish(package_dir,outcome='cancelled' if outcome=='cancelled' else 'failed',
                        summary='Controller reported terminal package command failure; inspect retained trace.')
        # A lost response, controller unknown, or storage error leaves preparation
        # unresolved. It must not become a second/final uncertain result on resume.


def _publish_artifact(root, *, raw=None, source=None, expected=None, name='artifact'):
    directory=Path(root)/'artifacts'
    ensure_directory(directory)
    fd, temporary=tempfile.mkstemp(prefix='.prepared-',dir=directory)
    digest=hashlib.sha256(); size=0
    try:
        with os.fdopen(fd,'wb') as out:
            if source is not None:
                if source.is_symlink(): raise ImageBuildError('artifact symlink is unsupported')
                with source.open('rb') as stream:
                    before=os.fstat(stream.fileno())
                    if not stat.S_ISREG(before.st_mode):
                        raise ImageBuildError('artifact must be a regular file')
                    while chunk:=stream.read(1024*1024):
                        digest.update(chunk); size+=len(chunk); out.write(chunk)
                    after = os.fstat(stream.fileno())
                    if _content_stat(after) != _content_stat(before):
                        raise ImageBuildError('artifact changed during capture')
            else:
                digest.update(raw);size=len(raw);out.write(raw)
            out.flush();os.fsync(out.fileno())
        key='sha256:'+digest.hexdigest()
        if expected is not None and key != expected: raise ImageBuildError('artifact digest differs from pinned input')
        target=directory/key[7:]
        try: os.link(temporary,target)
        except FileExistsError:
            if target.is_symlink(): raise ImageBuildError('artifact store symlink is unsupported')
            check=hashlib.sha256()
            with target.open('rb') as stream:
                while chunk:=stream.read(1024*1024):check.update(chunk)
            if check.hexdigest()!=key[7:] or target.stat().st_size!=size:
                raise ImageBuildError('existing retained artifact differs')
        sync_directory(directory)
        return dict(name=name,digest=key,size=size)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _content_stat(info):
    """Reads can change atime; identity/content changes must still fail closed."""
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
