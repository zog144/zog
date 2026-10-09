"""Literal, source-bound upstream declarations; no discovery or network access."""
import re
from pathlib import Path

from .errors import ImageBuildError
from .metadata import literal

NAME = 'source-provenance.py'


def _require(value, message):
    if not value:
        raise ImageBuildError(message)


def validate(value, sources):
    _require(isinstance(value, dict) and set(value) == {'schema', 'sources'}
             and type(value['schema']) is int and value['schema'] == 1,
             'unsupported source provenance declaration')
    _require(isinstance(value['sources'], list), 'source provenance requires a source list')
    seen = []
    for entry in value['sources']:
        _require(isinstance(entry, dict) and set(entry) == {'source', 'upstream'},
                 'invalid source provenance entry')
        source = entry['source']
        _require(source in sources and source not in seen,
                 'upstream declaration must bind one unique exact recipe source')
        seen.append(source)
        _require(isinstance(entry['upstream'], list) and bool(entry['upstream']),
                 'upstream declaration requires explicit identities or unknowns')
        repositories = set()
        for upstream in entry['upstream']:
            _require(isinstance(upstream, dict) and set(upstream) == {'repository', 'revision', 'revision_type'},
                     'invalid upstream identity declaration')
            repository = upstream['repository']
            _require(isinstance(repository, str) and 0 < len(repository) <= 4096
                     and not any(ord(c) < 32 for c in repository) and repository not in repositories,
                     'invalid or duplicate upstream repository')
            repositories.add(repository)
            revision, kind = upstream['revision'], upstream['revision_type']
            if kind == 'git':
                _require(isinstance(revision, str) and re.fullmatch(r'(?:[0-9a-f]{40}|[0-9a-f]{64})', revision),
                         'Git provenance requires a full lowercase revision')
            elif kind == 'unknown':
                _require(revision is None, 'unknown upstream revision must be null')
            elif kind in ('opaque', 'tag'):
                _require(isinstance(revision, str) and 0 < len(revision) <= 256
                         and not any(ord(c) < 32 for c in revision), 'invalid tag/opaque upstream revision')
            else:
                raise ImageBuildError('unsupported upstream revision type')
    return value


def load(path, sources):
    path = Path(path)
    if path.is_symlink():
        raise ImageBuildError('source provenance declaration must not be a symlink')
    return validate(literal(path), sources)


def upstream_for(declaration, source):
    """Project supported identities; retain unsupported originals in recipe bytes."""
    entries = [e for e in declaration['sources'] if e['source'] == source]
    if not entries:
        return [{'repository': 'not-captured', 'revision': None}], ['Upstream revision is not declared for this exact source; archive bytes are pinned.']
    result, gaps = [], []
    for upstream in entries[0]['upstream']:
        revision = upstream['revision'] if upstream['revision_type'] == 'git' else None
        result.append(dict(repository=upstream['repository'], revision=revision))
        if upstream['revision_type'] in ('opaque', 'tag'):
            gaps.append('Unsupported upstream revision type; original opaque identity is retained in source-provenance.py.')
        elif revision is None:
            gaps.append('Upstream revision is explicitly unknown; archive bytes are pinned.')
    return result, list(dict.fromkeys(gaps))


def patch_sources(package, state):
    """Reuse the licensing patch declaration contract; preserve reviewed order."""
    from .licensing import patch_declarations
    complete = package.integration.get('patches_complete', False)
    _require(type(complete) is bool, 'patches_complete must be boolean')
    _require(not complete or 'patches' in package.integration,
             'complete patch classification requires an explicit patches list')
    patches = patch_declarations(package, state)
    destinations = [patch['source']['destination'] for patch in patches]
    _require(len(set(destinations)) == len(destinations), 'duplicate patch source application is unsupported')
    gaps = [] if complete else ['Patch classification is not declared exhaustive; additional recipe transformations may exist.']
    return patches, gaps
