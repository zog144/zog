"""Required canonical generation producer. Caller holds the image-build owner lock.

Only local, repeatable composition is performed here; command recovery remains with
image-build/box-control. The canonical schema and graph/export logic are build-record's.
"""
import json
from pathlib import Path
import tempfile

from .errors import ImageBuildError
from .filesystem import ensure_directory, inventory, write_json
from .info_index import POLICY
from .metadata import identity, order
from .provenance import _now

ASSEMBLY_PACKAGE = '@rootfs-assembly'
FORMAT = 'image-build-rootfs-ustar-all-root-v1'


def _read(path):
    if path.is_symlink():
        raise ImageBuildError('provenance owner pointer must not be a symlink')
    return json.loads(path.read_bytes())


def _intent(p, path, kind, data, *, clock=None):
    """Replay a fixed record/timestamp after an uncertain store or pointer write."""
    if path.exists():
        record = _read(path)
        p.library.validate(record)
        saved = dict(record['data'])
        if clock:
            saved.pop(clock)
        if record['kind'] != kind or saved != data or record['gaps']:
            raise ImageBuildError('generation provenance intent changed')
    else:
        record = p.library.make_record(kind, dict(data, **({clock: _now()} if clock else {})))
        write_json(path, record)
    return p.store.put(record)


def _same_pointer(path, value):
    if path.exists():
        if _read(path) != value:
            raise ImageBuildError('immutable generation provenance pointer differs')
    # Also replay directory fsync when a previous pointer write was uncertain.
    write_json(path, value)


def prepare(p, attempt, packages, targets, built, owner_inputs, *, composition_materials=(), composition_actions=()):
    """Bind exact installed outputs and assembler before composition starts."""
    selected = order(packages, targets, runtime_only=True)
    bindings = []
    for name in selected:
        result = built[name]
        reference = result.get('provenance')
        if reference is None:
            raise ImageBuildError('generation package has no provenance binding')
        if inventory(result['root']) != result['outputs']:
            raise ImageBuildError('generation package output changed')
        p.verify_output(reference, name, result)
        bindings.append(reference)
    directory = attempt/'assembly'
    if ((attempt/'composed').exists() or (attempt/'composed.composition.json').exists()) and not (directory/'preparing.json').exists():
        raise ImageBuildError('existing assembly has no frozen provenance; legacy assembly cannot be retrofitted')
    ensure_directory(directory)
    generation = identity(owner_inputs)
    files = [p._file('image_build/'+file.name, file)
             for file in sorted(Path(__file__).parent.glob('*.py'))]
    recipe = p._bytes('assembly-recipe.json', dict(schema=1, format=FORMAT,
        owner_inputs=owner_inputs, package_order=selected, packages=bindings,
        composition_policy=POLICY, files=files,
        actions=['merge selected runtime outputs in package_order',
                 'compose usr/share/info/dir using composition_policy',
                 *(['omit only security.selinux host labels during copying; bind omission evidence; reject all other xattrs'] if composition_materials else []),
                 *composition_actions,
                 'normalize archive uid/gid and mtime to zero; preserve file modes and symlink targets']))
    inputs = p._record('build-inputs', dict(package=ASSEMBLY_PACKAGE, step='assemble',
        purpose='assembly', sources=[], recipe=recipe, patches=[],
        target=owner_inputs['architecture'], options={'owner_generation':generation, 'artifact_format':FORMAT},
        environment={}, materials=files + list(composition_materials), dependencies=bindings))
    owner_id = json.dumps([p.host_id, p.project_id, attempt.name, ASSEMBLY_PACKAGE], separators=(',', ':'))
    prepared = _intent(p, directory/'preparing.json', 'attempt-start',
        dict(attempt_id=owner_id, inputs=inputs, retry_of=None), clock='prepared_at')
    expected = dict(schema=1, host_id=p.host_id, project_id=p.project_id,
                    generation=generation, build_id='attempt:'+attempt.name,
                    prepared=prepared, inputs=inputs)
    path = directory/'prepared.json'
    if path.exists() and _read(path) != expected:
        raise ImageBuildError('frozen assembly binding changed')
    p._verify([prepared])
    _same_pointer(path, expected)
    return expected


def finish(p, attempt, binding, root, *, verification=()):
    """Build and verify an actual archive, then fix the assembly result and root."""
    from .host_export import _payload
    directory = attempt/'assembly'
    if _read(directory/'prepared.json') != binding:
        raise ImageBuildError('assembly prepared pointer differs')
    bundle = p._verify([binding['prepared']])
    start = bundle['records'][binding['prepared']]
    if start['kind'] != 'attempt-start' or start['data']['inputs'] != binding['inputs']:
        raise ImageBuildError('assembly prepared record differs')
    inputs = bundle['records'][binding['inputs']]['data']
    recipe = _read(p.root/'artifacts'/inputs['recipe']['digest'][7:])
    from .installed_verification import validate as validate_reports
    verification = list(verification)
    validate_reports(p, binding, root, recipe['owner_inputs'], verification)
    if verification or (directory/'verification.json').exists():
        _same_pointer(directory/'verification.json', verification)
    # Host export's existing strict USTAR serializer supplies normalized ownership,
    # xattr/hardlink refusal and before/after/decoded archive inventory checks.
    with tempfile.TemporaryDirectory(prefix='.payload-', dir=directory) as scratch:
        archive = Path(scratch)/'rootfs.tar'
        payload = _payload(root, archive)
        artifact = p._file('rootfs.tar', archive, 'sha256:'+payload['sha256'])
    validate_reports(p, binding, root, recipe['owner_inputs'], verification)
    content = p._bytes('rootfs-content.json', dict(schema=1, format=FORMAT, entries=payload['entries']))
    output = p._record('package-output', dict(package=ASSEMBLY_PACKAGE, attempt=binding['prepared'],
                                            artifacts=[artifact, content]))
    result = _intent(p, directory/'finalizing.json', 'attempt-result',
        dict(attempt=binding['prepared'], outcome='succeeded', outputs=[output], jobs=[],
             traces=[dict(host_id=p.host_id, build_id=binding['build_id'])],
             summary='image-build verified local rootfs assembly and normalized archive'), clock='finished_at')
    record = p._record('generation', dict(
        generation_id=json.dumps([p.host_id,p.project_id,binding['generation']], separators=(',', ':')),
        assembly_result=result, packages=inputs['dependencies'], artifact=artifact,
        content_manifest=content, verification=verification))
    pointer = dict(binding, record=record, result=result, output=output)
    p._verify([record])  # Includes prior attempts and transitive dependency materials.
    _same_pointer(directory/'generation.json', pointer)
    return pointer


def verify(p, selection):
    """Validate the owner pointer, canonical closure and current directory contents."""
    pointer = selection.manifest.get('build_record')
    if not isinstance(pointer, dict):
        raise ImageBuildError('generation has no canonical provenance; explicit legacy use requires an unconfigured owner')
    expected_keys = {'schema','host_id','project_id','generation','build_id','prepared','inputs','record','result','output'}
    if (set(pointer) != expected_keys or type(pointer['schema']) is not int or pointer['schema'] != 1
            or pointer['host_id'] != p.host_id or pointer['project_id'] != p.project_id
            or pointer['generation'] != selection.generation):
        raise ImageBuildError('generation provenance pointer scope differs')
    bundle = p._verify([pointer['record']])
    p.verify_scope(bundle)
    records = bundle['records']
    root = records[pointer['record']]
    if (root['kind'] != 'generation' or root['data']['generation_id'] !=
            json.dumps([p.host_id,p.project_id,selection.generation], separators=(',', ':'))
            or root['data']['assembly_result'] != pointer['result']):
        raise ImageBuildError('generation canonical root differs')
    result = records.get(pointer['result'], {})
    start = records.get(pointer['prepared'], {})
    inputs = records.get(pointer['inputs'], {})
    if (result.get('kind') != 'attempt-result' or start.get('kind') != 'attempt-start'
            or inputs.get('kind') != 'build-inputs'
            or result['data']['attempt'] != pointer['prepared']
            or result['data']['outputs'] != [pointer['output']]
            or start['data']['inputs'] != pointer['inputs']
            or inputs['data']['options'].get('owner_generation') != selection.generation):
        raise ImageBuildError('generation assembly pointer differs')
    owner = json.loads(start['data']['attempt_id'])
    if owner[3] != ASSEMBLY_PACKAGE or pointer['build_id'] != 'attempt:'+owner[2]:
        raise ImageBuildError('generation assembly identity differs')
    recipe = _read(p.root/'artifacts'/inputs['data']['recipe']['digest'][7:])
    if recipe.get('owner_inputs') != selection.manifest['inputs'] or recipe.get('format') != FORMAT:
        raise ImageBuildError('generation owner inputs differ from frozen assembly')
    from .installed_verification import validate as validate_reports
    validate_reports(p, pointer, selection.root, recipe['owner_inputs'],
                     root['data']['verification'], execution=selection.manifest.get('verification_execution'))
    packages = selection.manifest.get('packages', {})
    ordered = recipe['package_order']
    if set(ordered) != set(packages) or len(ordered) != len(packages):
        raise ImageBuildError('generation installed package set differs')
    bindings = []
    for name in ordered:
        reference = packages[name].get('provenance')
        p.verify_output(reference, name, packages[name])
        bindings.append(reference)
    if root['data']['packages'] != bindings or recipe['packages'] != bindings:
        raise ImageBuildError('generation package bindings differ from assembly')
    content = _read(p.root/'artifacts'/root['data']['content_manifest']['digest'][7:])
    from .host_export import records as root_records
    if (content != dict(schema=1, format=FORMAT, entries=root_records(selection.root))
            or selection.manifest['outputs'] != inventory(selection.root)):
        raise ImageBuildError('generation contents differ from canonical inventory')
    return bundle


def _members(bundle):
    """Indexes describe reachability; installed membership is explicitly distinct."""
    root = bundle['records'][bundle['roots'][0]]['data']
    installed = {item['output'] for item in root['packages']}
    result = bundle['records'][root['assembly_result']]['data']
    assembly = set(result['outputs']) | {result['attempt']}
    installed_starts = {bundle['records'][key]['data']['attempt'] for key in installed}
    for key, record in bundle['records'].items():
        if record['kind'] not in ('package-output', 'attempt-start'):
            continue
        relation = ('assembly' if key in assembly else 'installed' if key in installed | installed_starts
                    else 'dependency-or-history')
        yield ('outputs' if record['kind']=='package-output' else 'attempts'), key, relation


def index(p, selection, bundle=None):
    """Replayable owner discovery pointers; canonical records remain authoritative."""
    bundle = verify(p, selection) if bundle is None else bundle
    pointer = selection.manifest['build_record']
    for kind, key, relation in _members(bundle):
        path = p.root/'generation-members'/kind/key[7:]/(pointer['record'][7:]+'.json')
        value = dict(schema=1, host_id=p.host_id, project_id=p.project_id,
                     generation=selection.generation, record=pointer['record'],
                     member=key, relation=relation)
        _same_pointer(path, value)


def generation_roots(p, *, output=None, attempt=None, limit=100):
    from zog.build_record.model import digest
    from .engine import read_selection
    if (output is None) == (attempt is None) or type(limit) is not int or not 1 <= limit <= 1000:
        raise ImageBuildError('select one output/attempt record and a limit from 1 to 1000')
    key = output if output is not None else attempt
    digest(key)
    kind = 'outputs' if output is not None else 'attempts'
    directory = p.root/'generation-members'/kind/key[7:]
    paths = []
    for path in directory.glob('*.json'):
        paths.append(path)
        if len(paths) > limit:
            raise ImageBuildError('generation membership limit exceeded')
    found = []
    for path in sorted(paths):
        value = _read(path)
        generation = value.get('generation')
        if not isinstance(generation, str) or len(generation)!=64 or any(c not in '0123456789abcdef' for c in generation):
            raise ImageBuildError('invalid generation membership locator')
        selection = read_selection(p.state/'image-build/generations'/generation)
        bundle = verify(p, selection)
        actual = next((relation for k, member, relation in _members(bundle) if k==kind and member==key), None)
        expected = dict(schema=1, host_id=p.host_id, project_id=p.project_id,
                        generation=generation, record=selection.manifest['build_record']['record'],
                        member=key, relation=actual)
        if actual is None or value != expected or path.name != expected['record'][7:]+'.json':
            raise ImageBuildError('generation membership differs from canonical graph')
        found.append(value)
    return found
