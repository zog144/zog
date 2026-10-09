import argparse
import json
import sys
from .core import GitHub, ShareError, check_access, create_program, list_programs, retrieve
from .publication import status, compare, publish, resume, abandon, list_versions
from .archives import preview_zip, import_zip
from .handoffs import write_handoff, create_release, retrieve_dependencies, project_index
from .transfer import retrieve_archive
from .review import review

EXIT_CODES = {'configuration': 2, 'authentication': 3, 'forbidden': 4, 'not-found': 5,
              'network': 6, 'rate-limit': 7, 'conflict': 8, 'unsupported': 9,
              'unsafe-tree': 10, 'integrity': 11, 'remote': 12, 'partial': 13, 'local': 14,
              'secret': 15, 'uncertain': 16}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='version-share')
    parser.add_argument('--token-file')
    parser.add_argument('--owner')
    parser.add_argument('--json', action='store_true')
    commands = parser.add_subparsers(dest='command', required=True)
    access = commands.add_parser('check-access')
    access.add_argument('--program')
    commands.add_parser('list-programs')
    create = commands.add_parser('create-program')
    create.add_argument('program')
    download = commands.add_parser('retrieve')
    download.add_argument('program')
    download.add_argument('destination')
    download.add_argument('--reference')
    download.add_argument('--transport', choices=('archive', 'blobs'), default='archive')
    for name in ('status', 'resume', 'abandon'):
        commands.add_parser(name).add_argument('directory')
    commands.add_parser('list-versions').add_argument('program')
    comparison = commands.add_parser('compare')
    comparison.add_argument('program')
    comparison.add_argument('before')
    comparison.add_argument('after')
    inspection = commands.add_parser('review')
    inspection.add_argument('program')
    inspection.add_argument('before')
    inspection.add_argument('after')
    inspection.add_argument('--maximum-files', type=int, default=20)
    publication = commands.add_parser('publish')
    publication.add_argument('directory')
    publication.add_argument('--branch', required=True)
    publication.add_argument('--message', required=True)
    publication.add_argument('--version')
    publication.add_argument('--publication-id')
    preview = commands.add_parser('preview-zip')
    preview.add_argument('archive')
    preview.add_argument('--source-root', required=True)
    migration = commands.add_parser('import-zip')
    migration.add_argument('program')
    migration.add_argument('archive')
    migration.add_argument('destination')
    migration.add_argument('--source-root', required=True)
    migration.add_argument('--reference')
    handoff = commands.add_parser('handoff')
    handoff.add_argument('directory')
    handoff.add_argument('--notes-file', required=True)
    handoff.add_argument('--test-results-file')
    handoff.add_argument('--dependency', action='append', default=[])
    handoff.add_argument('--limitation', action='append', default=[])
    release = commands.add_parser('release')
    release.add_argument('program')
    release.add_argument('version')
    dependencies = commands.add_parser('retrieve-dependencies')
    dependencies.add_argument('directory')
    dependencies.add_argument('destination')
    commands.add_parser('project-index')
    args = parser.parse_args(argv)
    client = None
    try:
        if args.command != 'preview-zip' and (not args.token_file or not args.owner):
            raise ShareError('configuration', '--token-file and --owner are required for this command.')
        client = GitHub.from_file(args.token_file) if args.token_file else None
        if args.command == 'check-access':
            result = check_access(client, args.owner, args.program)
        elif args.command == 'list-programs':
            result = list_programs(client, args.owner)
        elif args.command == 'create-program':
            result = create_program(client, args.owner, args.program)
        elif args.command == 'retrieve':
            operation = retrieve_archive if args.transport == 'archive' else retrieve
            result = operation(client, args.owner, args.program, args.destination, args.reference)
        elif args.command == 'status':
            result = status(client, args.directory)
        elif args.command == 'compare':
            result = compare(client, args.owner, args.program, args.before, args.after)
        elif args.command == 'review':
            result = review(client, args.owner, args.program, args.before, args.after, args.maximum_files)
        elif args.command == 'list-versions':
            result = list_versions(client, args.owner, args.program)
        elif args.command == 'publish':
            result = publish(client, args.directory, args.branch, args.message, args.version, args.publication_id)
        elif args.command == 'resume':
            result = resume(client, args.directory)
        elif args.command == 'abandon':
            result = abandon(args.directory)
        elif args.command == 'preview-zip':
            result = preview_zip(args.archive, args.source_root, client._token if client else '')
        elif args.command == 'import-zip':
            result = import_zip(client, args.owner, args.program, args.archive, args.destination, args.source_root, args.reference)
        elif args.command == 'handoff':
            result = write_handoff(client, args.directory, args.notes_file, args.test_results_file, args.dependency, args.limitation)
        elif args.command == 'release':
            result = create_release(client, args.owner, args.program, args.version)
        elif args.command == 'retrieve-dependencies':
            result = retrieve_dependencies(client, args.directory, args.destination)
        else:
            result = project_index(client, args.owner)
        output, exit_status = {'ok': True, 'result': result}, 0
    except (ShareError, OSError) as error:
        if isinstance(error, OSError):
            error = ShareError('local', 'Local filesystem operation failed; inspect publication state before retrying.',
                               'uncertain' if args.command in ('publish', 'resume') else 'not-applicable')
        output = {'ok': False, 'error': {'code': error.code, 'message': str(error), 'outcome': error.outcome}}
        if hasattr(error, 'retry_after'):
            output['error']['retry_after_seconds'] = error.retry_after
        exit_status = EXIT_CODES[error.code]
    encoded = json.dumps(output, indent=None if args.json else 2)
    if client:
        encoded = encoded.replace(client._token, '[REDACTED]')
    print(encoded, file=sys.stdout if args.json or exit_status == 0 else sys.stderr)
    return exit_status

if __name__ == '__main__':
    sys.exit(main())
