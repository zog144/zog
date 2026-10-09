"""Inspect literal package research and derive explicit developer host plans.

This catalogue is not executable build metadata. It deliberately has no install
operation and cannot promote unverified sources into reviewed build definitions.
"""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from ..errors import ImageBuildError
from ..metadata import literal, names, identity


def _mapping(path):
    value = literal(path)
    if not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1:
        raise ImageBuildError(f'{path}: expected schema 1 mapping')
    return value


def load_catalogue(directory):
    result = {}
    for entry in sorted(Path(directory).iterdir()):
        if not entry.is_dir() or entry.name.startswith('.'):
            continue
        names([entry.name])
        package = _mapping(entry / 'package.py')
        if package.get('name') != entry.name or package.get('status') != 'catalogue-only':
            raise ImageBuildError(f'{entry.name}: invalid catalogue identity or status')
        upstream = _mapping(entry / 'upstream.py')
        url = upstream.get('release_url')
        if not isinstance(url, str) or urlsplit(url).scheme != 'https' or not urlsplit(url).hostname:
            raise ImageBuildError(f'{entry.name}: release URL must be HTTPS')
        if not isinstance(upstream.get('version'), str) or not upstream['version']:
            raise ImageBuildError(f'{entry.name}: missing source version')
        distributions = _mapping(entry / 'distribution.py')
        profiles = distributions.get('profiles')
        if not isinstance(profiles, dict):
            raise ImageBuildError(f'{entry.name}: missing distribution profiles')
        for profile in profiles.values():
            if not isinstance(profile, dict):
                raise ImageBuildError(f'{entry.name}: invalid distribution profile')
            seed_required = profile.get('seed_required', True)
            if type(seed_required) is not bool:
                raise ImageBuildError(f'{entry.name}: seed_required must be boolean')
            if not seed_required and profile.get('seed_packages') != []:
                raise ImageBuildError(f'{entry.name}: source-only profile cannot request seed packages')
            if profile.get('status') == 'repository-names-verified':
                related = names(profile.get('related_packages'))
                seed = names(profile.get('seed_packages'))
                if not set(seed) <= set(related):
                    raise ImageBuildError(f'{entry.name}: seed packages must have a distribution mapping')
            elif profile.get('status') != 'unreviewed':
                raise ImageBuildError(f'{entry.name}: unknown distribution review status')
        recipe = _mapping(entry / 'recipe-plan.py')
        if recipe.get('status') != 'not-authored':
            raise ImageBuildError(f'{entry.name}: catalogue recipes cannot authorize execution')
        from ..licensing import load as load_license
        license_record = load_license(entry / 'license.py')
        if license_record['package'] != entry.name or license_record['version'] != upstream['version']:
            raise ImageBuildError('license identity differs from upstream catalogue')
        if upstream.get('sha256') and license_record['source']['sha256'] != upstream['sha256']:
            raise ImageBuildError('license source differs from pinned upstream archive')
        record = dict(licensing=license_record, package=package, upstream=upstream, distribution=distributions, recipe=recipe)
        result[entry.name] = dict(record, fingerprint=identity(record))
    if not result:
        raise ImageBuildError('package catalogue is empty')
    return result


def host_plan(catalogue, distribution):
    if distribution not in {'amazon-linux-2023', 'fedora-rawhide'}:
        raise ImageBuildError(f'unsupported distribution: {distribution}')
    packages, reasons = set(), {}
    for name, entry in catalogue.items():
        profile = entry['distribution']['profiles'].get(distribution)
        if profile and profile.get('seed_required') is False:
            if profile.get('seed_packages') != []:
                raise ImageBuildError(f'{name}: source-only profile cannot request seed packages')
            continue
        if not profile or profile.get('status') != 'repository-names-verified':
            raise ImageBuildError(f'{name}: {distribution} mapping requires review')
        for rpm in profile['seed_packages']:
            packages.add(rpm)
            reasons.setdefault(rpm, []).append(name)
    return {'distribution': distribution, 'packages': sorted(packages),
            'install_command': ['dnf', '-y', 'install', *sorted(packages)],
            'required_command_aliases': [alias for entry in catalogue.values()
                for alias in entry['distribution'].get('required_command_aliases', [])],
            'reasons': reasons, 'catalogue_fingerprint': identity(catalogue),
            'scope': 'host prerequisites; not an RPM dependency closure or a seed file inventory'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package-dir', type=Path, required=True)
    parser.add_argument('--distribution', default='amazon-linux-2023')
    parser.add_argument('--list', action='store_true', help='show all source and distribution metadata')
    args = parser.parse_args()
    catalogue = load_catalogue(args.package_dir)
    print(json.dumps(catalogue if args.list else host_plan(catalogue, args.distribution), indent=2))


if __name__ == '__main__':
    main()
