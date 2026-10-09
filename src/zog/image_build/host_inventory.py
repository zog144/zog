"""Report catalogue coverage for a proposed host profile; never infer installed state."""
import argparse
import json
from pathlib import Path

from .errors import ImageBuildError
from .metadata import literal, identity
from .filesystem import digest

RECIPE_FILES = ('package.py', 'sources.py', 'build.py', 'dependencies.py', 'produce-manifest.py')


def inspect(profile, catalogue):
    profile = literal(profile); catalogue = Path(catalogue)
    if profile['schema'] != 1 or profile['status'] != 'planning-not-installable':
        raise ImageBuildError('unsupported planning profile')
    items = []
    for item in profile['items']:
        name = item['project']
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in name):
            raise ImageBuildError('invalid profile project')
        directory = catalogue/name
        stages = []
        for d in sorted((directory/'stages').glob('*')):
            if not d.is_dir(): continue
            # Stage package.py is normally materialized from the canonical package record.
            expected = RECIPE_FILES[1:]
            missing = [f for f in expected if not (d/f).is_file()]
            stages.append({'stage':d.name, 'recipe_files_present':not missing,
                           'missing_files':missing,
                           'file_hashes':{f:digest(d/f) for f in expected if (d/f).is_file()}})
        items.append({**item, 'catalogue_present':directory.is_dir(),
                      'package_metadata_present':(directory/'package.py').is_file(),
                      'license_metadata_present':(directory/'license.py').is_file(),
                      'stages':stages, 'host_acceptance':'not-assessed',
                      'recipe_gap':not any(s['recipe_files_present'] for s in stages)})
    return {'schema':1, 'profile':profile['profile'], 'profile_identity':identity(profile),
            'installable':False, 'dependency_closure':'not-reviewed',
            'live_inventory':'not-performed', 'items':items,
            'recipe_review_candidates':profile['recipe_review_candidates'],
            'candidate_note':profile['candidate_note'], 'acceptance':profile['acceptance'],
            'excluded_from_first_host':profile['excluded_from_first_host']}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--profile', required=True); p.add_argument('--catalogue', required=True)
    a = p.parse_args(); print(json.dumps(inspect(a.profile, a.catalogue), indent=2))


if __name__ == '__main__': main()
