"""Trusted local CLI; project and host scope must come from the caller."""
import argparse
import json
import sys
from .observations import BuildTrace, ObservationFileProvider
from .model import TraceError
from .source import BoxControlReader, InspectionLimits
from .model import redact


def main(argv=None):
    parser = argparse.ArgumentParser(prog='build-trace')
    parser.add_argument('--project-root', required=True)
    parser.add_argument('--host-id', required=True, help='explicit host identity scope; no auto-enrollment')
    parser.add_argument('--controller', action='store_true', help='use installed box-control read-only inspection and journal API')
    parser.add_argument('--socket-path', help='root-control socket, used only with --controller')
    parser.add_argument('--source-limit-mib', type=int, default=256, help='deep inspection cumulative source budget')
    parser.add_argument('--list-source-limit-mib', type=int, default=16, help='listing cumulative source budget per page')
    parser.add_argument('--file-limit-mib', type=int, default=16, help='maximum individual source record size')
    parser.add_argument('--record-limit', type=int, default=10000)
    parser.add_argument('--scan-build-limit', type=int, default=100, help='maximum candidate builds examined per list page')
    parser.add_argument('--record-store', help='trusted build-record records directory')
    parser.add_argument('--record-project-id', help='explicit owner provenance project identity')
    parser.add_argument('--observation-file',
                        help='explicit image-build v1 observation export for observation queries')
    subs = parser.add_subparsers(dest='operation', required=True)
    listing = subs.add_parser('list')
    for name in ('package', 'phase', 'status', 'attempt'):
        listing.add_argument('--' + name)
    inspect = subs.add_parser('inspect')
    inspect.add_argument('build_id')
    command = subs.add_parser('command')
    command.add_argument('build_id')
    command.add_argument('command_id')
    logs = subs.add_parser('logs')
    logs.add_argument('build_id')
    logs.add_argument('command_id')
    for p in (listing, inspect, logs):
        p.add_argument('--cursor')
        p.add_argument('--limit', type=int, default=50)
    compare = subs.add_parser('compare')
    compare.add_argument('before')
    compare.add_argument('after')
    export = subs.add_parser('export')
    export.add_argument('build_id')
    export.add_argument('--command-limit', type=int, default=100)
    provenance = subs.add_parser('provenance')
    provenance.add_argument('build_id')
    provenance.add_argument('package')
    provenance.add_argument('--cursor')
    provenance.add_argument('--limit', type=int, default=20)
    provenance_compare = subs.add_parser('compare-provenance')
    provenance_compare.add_argument('before')
    provenance_compare.add_argument('after')
    provenance_compare.add_argument('package')
    generation = subs.add_parser('generation-provenance')
    generation.add_argument('generation')
    membership = subs.add_parser('generations')
    member = membership.add_mutually_exclusive_group(required=True)
    member.add_argument('--output')
    member.add_argument('--attempt', help='canonical attempt-start record ID')
    for p in (generation, membership):
        p.add_argument('--cursor')
        p.add_argument('--limit', type=int, default=20)
    summary = subs.add_parser('generation-summary')
    summary.add_argument('generation')
    generation_compare = subs.add_parser('compare-generations')
    generation_compare.add_argument('before')
    generation_compare.add_argument('after')
    for p in (summary, generation_compare):
        p.add_argument('--cursor')
        p.add_argument('--limit', type=int, default=20)
    materials = subs.add_parser('materials')
    materials.add_argument('subject')
    materials.add_argument('package')
    material_compare = subs.add_parser('compare-materials')
    material_compare.add_argument('before')
    material_compare.add_argument('after')
    material_compare.add_argument('package')
    for p in (materials, material_compare):
        p.add_argument('--cursor')
        p.add_argument('--limit', type=int, default=20)
    observations = subs.add_parser('generation-observations')
    observations.add_argument('generation')
    observations.add_argument('--collection',
                              choices=('checks', 'verification', 'relationships', 'sources', 'gaps'))
    observations.add_argument('--relation',
                              choices=('needs-library', 'provides-soname', 'elf-interpreter',
                                       'script-interpreter', 'declares-build-dependency',
                                       'declares-test-dependency', 'declares-runtime-dependency',
                                       'used-build-output'))
    observations.add_argument('--package')
    observations.add_argument('--cursor')
    observations.add_argument('--limit', type=int, default=20)
    candidate = subs.add_parser('candidate-verifications')
    candidate.add_argument('candidate')
    candidate.add_argument('--cursor')
    candidate.add_argument('--limit', type=int, default=20)

    snapshot = subs.add_parser('observation-snapshot')
    snapshot.add_argument('snapshot')
    snapshot.add_argument('--collection',
                          choices=('verification-checks', 'verification-executions',
                                   'relationships', 'source-provenance', 'coverage',
                                   'declared-gaps'))
    snapshot.add_argument('--relation',
                          choices=('needs-library', 'provides-soname', 'elf-interpreter',
                                   'script-interpreter', 'declares-build-dependency',
                                   'declares-test-dependency', 'declares-runtime-dependency',
                                   'used-build-output'))
    snapshot.add_argument('--package')
    snapshot.add_argument('--family',
                          choices=('verification-commands', 'elf-interfaces',
                                   'script-interpreters', 'declared-package-dependencies',
                                   'used-build-output', 'source-provenance'))
    snapshot.add_argument('--outcome',
                          choices=('complete', 'partial', 'unavailable',
                                   'not-performed', 'not-applicable'))
    snapshot.add_argument('--gap-category',
                          choices=('upstream-identity', 'external-environment-runtime',
                                   'inventory-only-output', 'other'))
    snapshot.add_argument('--cursor')
    snapshot.add_argument('--limit', type=int, default=20)

    snapshot_compare = subs.add_parser('compare-observation-snapshots')
    snapshot_compare.add_argument('before')
    snapshot_compare.add_argument('after')
    snapshot_compare.add_argument('--collection',
                                  choices=('verification-checks', 'verification-executions',
                                           'relationships', 'source-provenance', 'coverage',
                                           'declared-gaps'))
    snapshot_compare.add_argument('--cursor')
    snapshot_compare.add_argument('--limit', type=int, default=20)

    verification_history = subs.add_parser('verification-history')
    verification_history.add_argument('check_id')
    verification_history.add_argument('snapshots', nargs='+')
    verification_history.add_argument('--definition-digest')
    verification_history.add_argument('--cursor')
    verification_history.add_argument('--limit', type=int, default=20)

    relationship_history = subs.add_parser('relationship-traversal')
    relationship_history.add_argument('direction', choices=('forward', 'reverse'))
    relationship_history.add_argument(
        'selector_kind',
        choices=('package', 'artifact-path', 'artifact-digest',
                 'package-output', 'soname', 'path'))
    relationship_history.add_argument('selector_value')
    relationship_history.add_argument('snapshots', nargs='+')
    relationship_history.add_argument(
        '--relation',
        choices=('needs-library', 'provides-soname', 'elf-interpreter',
                 'script-interpreter', 'declares-build-dependency',
                 'declares-test-dependency', 'declares-runtime-dependency',
                 'used-build-output'))
    relationship_history.add_argument('--cursor')
    relationship_history.add_argument('--limit', type=int, default=20)
    args = vars(parser.parse_args(argv))
    try:
        from pathlib import Path
        project_root, host_id = args.pop('project_root'), args.pop('host_id')
        controller, socket_path = args.pop('controller'), args.pop('socket_path')
        observation_file = args.pop('observation_file')
        reader = None
        if socket_path and not controller:
            raise TraceError('invalid-query', '--socket-path requires --controller.')
        if controller:
            try:
                from zog.box_control import BoxControl, Project
                from zog.box_control.runtime.root_control import RootControlSystemdTransport
            except ImportError:
                raise TraceError('dependency-unavailable', 'Install the supported box-control source to use --controller.') from None
            transport = RootControlSystemdTransport(socket_path=socket_path) if socket_path else None
            reader = BoxControlReader(BoxControl(Project(Path(project_root)), systemd_transport=transport))
        limits = InspectionLimits(source_bytes=args.pop('source_limit_mib') * 1024 * 1024,
                                  list_source_bytes=args.pop('list_source_limit_mib') * 1024 * 1024,
                                  file_bytes=args.pop('file_limit_mib') * 1024 * 1024,
                                  records=args.pop('record_limit'), scan_builds=args.pop('scan_build_limit'))
        observation_provider = ObservationFileProvider(observation_file) if observation_file else None
        trace = BuildTrace(project_root, host_id=host_id, controller=reader, limits=limits,
                           record_store=args.pop('record_store'), record_project_id=args.pop('record_project_id'),
                           observation_provider=observation_provider)
        operation = args.pop('operation')
        method = {'list': trace.list_builds, 'inspect': trace.inspect_build, 'command': trace.inspect_command,
                  'logs': trace.logs, 'compare': trace.compare, 'export': trace.export,
                  'provenance': trace.provenance, 'compare-provenance': trace.compare_provenance,
                  'generation-provenance': trace.generation_provenance, 'generations': trace.generations,
                  'generation-summary': trace.generation_summary, 'compare-generations': trace.compare_generations,
                  'materials': trace.materials, 'compare-materials': trace.compare_materials,
                  'generation-observations': trace.generation_observations,
                  'candidate-verifications': trace.candidate_verifications,
                  'observation-snapshot': trace.observation_snapshot,
                  'compare-observation-snapshots': trace.compare_observation_snapshots,
                  'verification-history': trace.verification_history,
                  'relationship-traversal': trace.relationship_traversal}[operation]
        result = method(**args)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except TraceError as error:
        print(json.dumps({'schema_version': 1, 'kind': 'error', 'error': {'code': error.code, 'message': str(error), 'details': redact(error.details)}}))
        return {'not-found': 4, 'invalid-query': 2, 'invalid-cursor': 2}.get(error.code, 3)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print(json.dumps({'schema_version': 1, 'kind': 'error', 'error': {'code': 'invalid-record', 'message': 'Evidence is unavailable or malformed.'}}))
        return 3


if __name__ == '__main__':
    sys.exit(main())
