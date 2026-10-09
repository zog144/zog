"""Read-only inspection of retained image-build attempts and pipelines."""
from pathlib import Path
from functools import wraps

from .model import TraceError, digest, environment, fact, limit_value, paginate, redact, response, read_cursor, make_cursor
from .source import Snapshot, component, InspectionLimits
from .shell import inline_shell
from .integration import EXTRA_SUFFIXES, read_records, job_identity, recovery, evidence, failure

PHASES = ('prepare', 'configure', 'build', 'test', 'install')
SUFFIXES = ('.view.json', '.controller.json', '.execution.json') + EXTRA_SUFFIXES


def checked(method):
    @wraps(method)
    def call(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (KeyError, TypeError, AttributeError, ValueError):
            raise TraceError('invalid-record', 'Evidence has an unsupported or malformed shape.') from None
        except OSError:
            raise TraceError('source-unavailable', 'Evidence cannot be read.') from None
    return call


class BuildTrace:
    def __init__(self, project_root, *, host_id, controller=None, allowed_build_ids=None, limits=None, record_store=None, record_project_id=None, provenance_limits=None):
        self.project_root = Path(project_root).resolve()
        self.root = self.project_root / 'state/image-build'
        if not isinstance(host_id, str) or not host_id or len(host_id) > 256:
            raise TraceError('invalid-query', 'An explicit host scope is required.')
        self.host_id = host_id
        self.limits = limits or InspectionLimits()
        from .provenance import DEFAULT_LIMITS
        self.record_store = Path(record_store).resolve() if record_store is not None else None
        self.record_project_id = record_project_id
        self.provenance_limits = provenance_limits or DEFAULT_LIMITS
        self.controller = controller
        self.allowed = None if allowed_build_ids is None else frozenset(allowed_build_ids)
        self.scope = [host_id, str(self.project_root), sorted(self.allowed) if self.allowed is not None else None]

    def _permitted(self, build_id):
        return self.allowed is None or build_id in self.allowed

    def _identity(self, build_id):
        if not isinstance(build_id, str) or ':' not in build_id:
            raise TraceError('invalid-query', 'Expected attempt:IDENTITY or pipeline:IDENTITY.')
        kind, name = build_id.split(':', 1)
        component(name)
        if kind not in ('attempt', 'pipeline'):
            raise TraceError('invalid-query', 'Unsupported build identity kind.')
        if not self._permitted(build_id):
            raise TraceError('not-found', 'Build is not available in this scope.')
        return kind, name

    def _pipeline(self, snap, name):
        component(name)
        record = snap.read('pipelines/' + name + '/pipeline.json')
        if record is not None and (record.get('schema') != 1 or record.get('pipeline_id') != name):
            raise TraceError('unsupported-schema', 'Pipeline schema or identity differs from schema 1.')
        return record

    def _snapshot(self, *, listing=False):
        if not self.root.is_dir():
            raise TraceError(
                'source-unavailable',
                'This operation requires the configured project image-build state directory.')
        return Snapshot(self.root, limits=self.limits, listing=listing)

    def _catalogue_ids(self, snap, *, attempt=None, commands_only=False):
        if attempt is not None:
            component(attempt)
            return ['attempt:' + attempt] if self._permitted('attempt:' + attempt) else []
        ids = ['attempt:' + component(n) for n in snap.names('attempts')]
        if not commands_only:
            ids += ['pipeline:' + component(n) for n in snap.names('pipelines')]
        return sorted(i for i in ids if self._permitted(i))

    def _attempt(self, snap, name):
        base = 'attempts/' + component(name)
        if snap.read(base, directory=True) is None:
            raise TraceError('not-found', 'Build is not available in this scope.')
        return snap.read(base + '/status.json') or {}

    def _layout(self, snap, name):
        base = 'attempts/' + name
        names = snap.names(base)
        package_names = snap.names(base + '/packages')
        def stems(files):
            return {n[:-len(suffix)] for n in files for suffix in SUFFIXES if n.endswith(suffix)}
        count = len(stems(names))
        supported = 'status.json' in names or bool(count)
        for package in package_names:
            files = snap.names(base + '/packages/' + component(package))
            count += len(stems(files))
            if any(n.endswith(SUFFIXES) or n in ('prepared.json', 'result.json', 'artifact-reuse.json') for n in files):
                supported = True
            for fixture in ('test-fixture-cache', 'test-fixture-runtime'):
                if fixture in files:
                    fixture_count = len(stems(snap.names(base + '/packages/' + package + '/' + fixture)))
                    count += fixture_count
                    supported = supported or bool(fixture_count)
        receipts = sorted(n for n in names if n.endswith(('-launch.json', '-job.json')))
        return dict(status='supported' if supported else 'unsupported-layout', command_count=count if supported else None,
                    reason=None if supported else ('diagnostic-receipts-without-owner-adapter' if receipts else 'unrecognized-attempt-records'),
                    diagnostic_receipts=receipts[:20], diagnostic_receipts_truncated=len(receipts) > 20)

    def _commands(self, snap, attempt, *, selected_id=None, package_filter=None, phase_filter=None):
        base = 'attempts/' + attempt
        folders = ['']
        if selected_id is not None:
            parts = selected_id.split('/') if isinstance(selected_id, str) else []
            if not (len(parts) == 1 or (len(parts) in (3, 4) and parts[0] == 'packages' and
                    (len(parts) == 3 or parts[2] in ('test-fixture-cache', 'test-fixture-runtime')))):
                raise TraceError('not-found', 'Command is not available in this build.')
            for part in parts:
                try:
                    component(part)
                except TraceError:
                    raise TraceError('not-found', 'Command is not available in this build.') from None
            folders = ['/'.join(parts[:-1])]
        else:
            for package in snap.names(base + '/packages'):
                component(package)
                folders += ['packages/' + package, 'packages/' + package + '/test-fixture-cache',
                            'packages/' + package + '/test-fixture-runtime']
        result = []
        for folder in folders:
            directory = base + ('/' + folder if folder else '')
            stems = {selected_id.split('/')[-1]} if selected_id is not None else {
                n[:-len(suffix)] for n in snap.names(directory) for suffix in SUFFIXES if n.endswith(suffix)}
            for stem in sorted(stems):
                component(stem)
                command_id = (folder + '/' if folder else '') + stem
                path = directory + '/' + stem
                view = snap.read(path + '.view.json')
                trace, summary, observation = read_records(snap, path, attempt, command_id, view, metadata_only=True)
                identity_view = trace or view or {}
                package_key = folder.split('/')[1] if folder.startswith('packages/') else None
                if package_filter is not None and package_filter not in (package_key, identity_view.get('package')):
                    continue
                if phase_filter is not None and phase_filter != identity_view.get('phase'):
                    continue
                trace, summary, observation = read_records(snap, path, attempt, command_id, view)
                checkpoint = snap.read(path + '.controller.json')
                execution = snap.read(path + '.execution.json')
                if all(v is None for v in (view, checkpoint, execution, trace, summary, observation)):
                    continue
                if view is not None:
                    if view.get('schema') != 1 or view.get('attempt_id') != attempt or view.get('checkpoint') != stem + '.controller.json':
                        raise TraceError('integrity-error', 'Command view schema or binding is invalid.')
                    if type(view.get('command_index')) is not int or view['command_index'] < 0:
                        raise TraceError('invalid-record', 'Command index is invalid.')
                requests = []
                if checkpoint:
                    requests.append((checkpoint['binding']['request'], path + '.controller.json'))
                if execution:
                    requests.append((execution['request'], path + '.execution.json'))
                if len(requests) == 2 and requests[0][0] != requests[1][0]:
                    raise TraceError('integrity-error', 'Prepared and completed command requests differ.')
                request, request_source = requests[0] if requests else ({}, path + '.view.json')
                summarized = not requests and summary is not None
                if summarized:
                    request, request_source = summary['request'], path + '.summary.json'
                argv = request.get('command', (view or {}).get('command'))
                if argv is not None and (not isinstance(argv, list) or not argv or not all(isinstance(v, str) for v in argv)):
                    raise TraceError('invalid-record', 'Recorded command is not an argv array.')
                if view and requests and view.get('command') != argv:
                    raise TraceError('integrity-error', 'Command view differs from prepared command.')
                job_id, request_id = None, None
                if checkpoint:
                    request_id = checkpoint['request_id']
                    job_id = job_identity(request_id, checkpoint.get('job_id'))
                if observation is not None:
                    observed_job = job_identity(observation.get('request_id'), observation.get('job_id'))
                    if job_id is not None and observed_job != job_id:
                        raise TraceError('integrity-error', 'Observation differs from prepared job.')
                    job_id, request_id = observed_job, observation['request_id']
                if (summary or {}).get('request_id') is not None and summary['request_id'] != request_id:
                    raise TraceError('integrity-error', 'Summary differs from observed request identity.')
                controller_record, controller_status = None, 'not-configured'
                if self.controller is not None and job_id:
                    try:
                        controller_record = self.controller.inspect(job_id)
                        controller_status = 'available' if controller_record is not None else 'missing-or-pruned'
                    except Exception:
                        controller_status = 'retrieval-failure'
                    if controller_record is not None:
                        if controller_record.get('job_id') != job_id or controller_record.get('request_id') != request_id:
                            raise TraceError('integrity-error', 'Controller returned a different job identity.')
                        for key in ('command', 'environment', 'working_directory', 'read_only_root', 'network_access'):
                            expected = controller_record.get('request', {}).get(key)
                            actual = request.get(key)
                            if summarized:
                                if key == 'environment':
                                    from .model import ENVIRONMENT
                                    expected = {k: v if k in ENVIRONMENT else '[REDACTED]' for k, v in (expected or {}).items()}
                                expected, actual = redact(expected), redact(actual)
                            if expected != actual:
                                raise TraceError('integrity-error', 'Controller request differs from retained command binding.')
                observed = controller_record or observation
                observation_source = ('box-control:job:' + job_id if controller_record else
                                      path + '.observation.json' if observation is not None else None)
                if observed and execution:
                    for key in ('runtime_id', 'invocation_id', 'exit_code'):
                        if observed.get(key) is not None and execution.get(key) is not None and observed[key] != execution[key]:
                            raise TraceError('integrity-error', 'Controller and retained completion evidence differ.')
                state = (observed or {}).get('state', 'unknown')
                outcome = (observed or {}).get('outcome') or 'unknown'
                outcome_source = observation_source
                exit_code = (observed or {}).get('exit_code')
                if controller_record is None and execution:
                    exit_code = execution.get('exit_code')
                    if type(exit_code) is int:
                        outcome = 'success' if exit_code == 0 else 'nonzero-exit'
                        state, outcome_source = ('completed' if execution.get('cleanup_complete') else 'cleanup'), path + '.execution.json'
                        observed = dict(observed or {}, state=state, outcome=outcome, process_cleanup_complete=execution.get('cleanup_complete'))
                if not checkpoint and not execution and not observation and not controller_record:
                    state = 'not-submitted-or-unrecorded'
                settings = {k: request[k] for k in ('timeout_seconds', 'read_only_root', 'network_access') if k in request}
                settings.update((checkpoint or {}).get('binding', {}).get('configuration', {}) if checkpoint else (execution or summary or {}).get('policy') or {})
                shell = inline_shell(argv)
                phase = identity_view.get('phase')
                index = identity_view.get('command_index')
                package_key = folder.split('/')[1] if folder.startswith('packages/') else None
                package = identity_view.get('package', package_key)
                prefix = folder + '/' + str(PHASES.index(phase) if phase in PHASES else 99).zfill(2)
                order = prefix + '/' + str(index if index is not None else 0).zfill(10) + '/' + command_id
                execution_fields = ('runtime_id', 'invocation_id', 'boot_id', 'unit_name', 'signal', 'completed_at', 'journal_reference')
                identity = {k: fact((observed or {}).get(k) if (observed or {}).get(k) is not None else (execution or {}).get(k),
                                    observation_source if (observed or {}).get(k) is not None else path + '.execution.json') for k in execution_fields}
                result.append(dict(id=command_id, order_key=order, package=package, package_key=package_key,
                    phase=phase, command_index=index, stage_id=identity_view.get('stage_id'),
                    pipeline_id=identity_view.get('pipeline_id'),
                    title=(trace or {}).get('title') or ' · '.join(str(v) for v in (package or 'unknown package', phase or 'unknown phase', index, identity_view.get('stage_id'), attempt) if v is not None),
                    title_origin=trace['origin'] if trace else 'derived',
                    category=(trace or {}).get('category', 'build' if view else 'unknown'),
                    provenance=fact((trace or {}).get('provenance'), path + '.trace.json', origin=(trace or {}).get('origin', 'captured')),
                    relationships=fact((trace or {}).get('relationships'), path + '.trace.json', origin=(trace or {}).get('origin', 'captured'), reason='no-owner-defined-retry-record'),
                    request_id=fact(request_id, path + ('.controller.json' if checkpoint else '.observation.json')),
                    observation_source=observation_source,
                    observed_at=fact((observation or {}).get('observed_at'), path + '.observation.json'),
                    completion_available=execution is not None,
                    recovery=recovery(observed, execution, outcome_source or observation_source or (path + '.execution.json'), observation_source),
                    evidence=evidence(path, view, checkpoint, execution, trace, summary, observation, job_id, identity['journal_reference']['value']),
                    job_id=fact(job_id, path + ('.controller.json' if checkpoint else '.observation.json'), origin='derived'),
                    command=fact(argv, request_source, origin=summary['origin'] if summarized else 'captured'), script=fact(shell['script'], request_source, origin=summary['origin'] if summarized else 'captured', reason=shell['status']),
                    shell_parsing=shell['status'], interpreter=fact(shell['interpreter'], request_source), child_commands=fact(reason='not-individually-captured'),
                    working_directory=fact(request.get('working_directory'), request_source),
                    environment=environment(request.get('environment'), request_source),
                    settings=fact(settings or None, request_source),
                    state=state, outcome=fact(outcome, outcome_source, origin=((observation or {}).get('origin', 'captured') if outcome_source == path + '.observation.json' else 'captured') if outcome_source else 'missing', reason='execution-not-established'),
                    exit_code=fact(exit_code, outcome_source), execution=identity,
                    controller_availability=controller_status,
                    missing_fields=[k for k, v in [('command', argv), ('working_directory', request.get('working_directory')),
                                    ('execution_outcome', outcome_source), ('start_timestamp', None)] if v is None]))
                result[-1]['failure_summary'] = failure(result[-1], (observed or {}).get('error'))
        return sorted(result, key=lambda c: c['order_key'])

    def _build(self, snap, build_id):
        kind, name = self._identity(build_id)
        if kind == 'pipeline':
            pipeline = self._pipeline(snap, name)
            if pipeline is None:
                raise TraceError('not-found', 'Build is not available in this scope.')
            status, commands, packages, pipeline_id = pipeline, [], [], name
            status_source = 'pipelines/' + name + '/pipeline.json'
        else:
            base = 'attempts/' + name
            status_source = base + '/status.json'
            status = self._attempt(snap, name)
            commands = self._commands(snap, name)
            owners = {c['pipeline_id'] for c in commands if c.get('pipeline_id')}
            if status.get('pipeline_id'):
                owners.add(status['pipeline_id'])
            if len(owners) > 1:
                raise TraceError('integrity-error', 'Attempt records name different pipelines.')
            pipeline_id = next(iter(owners), None)
            pipeline = self._pipeline(snap, pipeline_id) if pipeline_id else None
            packages = []
            for package in snap.names(base + '/packages'):
                folder = base + '/packages/' + component(package)
                prepared = snap.read(folder + '/prepared.json')
                result = snap.read(folder + '/result.json')
                reuse = snap.read(folder + '/artifact-reuse.json')
                provenance_binding = snap.read(folder + '/provenance.json')
                inputs = (prepared or result or {}).get('inputs')
                if prepared and result and prepared.get('inputs') != result.get('inputs'):
                    raise TraceError('integrity-error', 'Prepared inputs differ from completed package inputs.')
                outputs = (result or {}).get('outputs')
                packages.append(dict(package_key=package,
                    inputs=fact(inputs, folder + ('/prepared.json' if prepared else '/result.json')),
                    build_record=fact(provenance_binding, folder + '/provenance.json'),
                    output_identity=fact((result or {}).get('identity'), folder + '/result.json'),
                    output_manifest=fact({'entry_count': len(outputs), 'record_digest': digest(outputs)} if outputs is not None else None,
                                         folder + '/result.json', origin='derived'),
                    reuse=fact(reuse, folder + '/artifact-reuse.json', origin='imported'),
                    source_archives=fact(reason='not-projected-from-recipe-snapshot'),
                    version=fact(reason='not-recorded-in-command-view'),
                    evidence=[dict(kind=kind, reference=folder + '/' + filename, availability='available' if raw is not None else 'missing')
                              for kind, filename, raw in [('preparation', 'prepared.json', prepared), ('artifact', 'result.json', result), ('artifact-reuse', 'artifact-reuse.json', reuse)]]))
        return dict(id=build_id, host_id=self.host_id, attempt_id=name if kind == 'attempt' else None,
            pipeline_id=pipeline_id, status=fact(status.get('status'), status_source),
            error=fact(status.get('error', (pipeline or {}).get('error')), status_source),
            generation=fact(status.get('generation', (pipeline or {}).get('generation')), status_source),
            recipe_snapshot=fact({'entry_count': len(pipeline['recipes']), 'record_digest': digest(pipeline['recipes'])}
                                 if pipeline and 'recipes' in pipeline else None,
                                 'pipelines/' + str(pipeline_id) + '/pipeline.json', origin='derived'),
            packages=packages, commands=commands,
            layout=self._layout(snap, name) if kind == 'attempt' else {'status': 'supported'},
            retry_relationships=fact([dict(command_id=c['id'], **link) for c in commands for link in (c['relationships']['value'] or [])][:32] if any(c['relationships']['value'] is not None for c in commands) else None, origin='derived', reason='no-owner-defined-retry-record'),
            retry_relationships_truncated=sum(len(c['relationships']['value'] or []) for c in commands) > 32,
            failure_summary=dict(owner_error=fact(status.get('error', (pipeline or {}).get('error')), status_source),
                items=[c['failure_summary'] for c in commands if c['failure_summary']['status'] != 'none'][:20],
                truncated=sum(c['failure_summary']['status'] != 'none' for c in commands) > 20),
            evidence_completeness='partial',
            limitations=['No total chronological order across packages is recorded.',
                         'Legacy source declarations and explicit package versions may be unavailable.',
                         'Controller state is observed without refresh; multi-owner reads are not atomic.'])

    def _summary(self, snap, build_id, *, package=None, phase=None, status=None):
        kind, name = self._identity(build_id)
        if kind == 'pipeline':
            raw = self._pipeline(snap, name)
            if raw is None or raw.get('attempts') or package is not None or phase is not None:
                return None
            if status is not None and raw.get('status') != status:
                return None
            source = 'pipelines/' + name + '/pipeline.json'
            return dict(id=build_id, host_id=self.host_id, attempt_id=None, pipeline_id=name,
                        title=build_id, status=fact(raw.get('status'), source), error=fact(raw.get('error'), source),
                        command_count=0, matched_command_count=0, packages=[], command_preview=[],
                        evidence_completeness='partial', layout={'status': 'supported'})
        raw = self._attempt(snap, name)
        layout = self._layout(snap, name)
        package_names = snap.names('attempts/' + name + '/packages')
        commands = self._commands(snap, name, package_filter=package, phase_filter=phase)
        matches = [c for c in commands if status is None or status in (c['state'], c['outcome']['value'], raw.get('status'))]
        if not matches and (phase is not None or (package is not None and package not in package_names) or
                            (status is not None and raw.get('status') != status)):
            return None
        source = 'attempts/' + name + '/status.json'
        argv = (matches[0]['command']['value'] or []) if matches else []
        visible_argv = redact(argv)
        preview = [v[:512] for v in visible_argv[:8]]
        return dict(id=build_id, host_id=self.host_id, attempt_id=name,
            pipeline_id=raw.get('pipeline_id') or next((c['pipeline_id'] for c in commands if c.get('pipeline_id')), None),
            status=fact(raw.get('status'), source), error=fact(raw.get('error'), source),
            command_count=layout['command_count'],
            matched_command_count=len(matches), packages=sorted(set(package_names) | {c['package'] for c in commands if c['package']}),
            title=matches[0]['title'] if matches else build_id, command_preview=preview,
            command_preview_truncated=preview != visible_argv, evidence_completeness='partial', layout=layout)

    @checked
    def list_builds(self, *, package=None, phase=None, status=None, attempt=None, cursor=None, limit=50):
        limit_value(limit)
        snap = self._snapshot(listing=True)
        scope = [self.scope, 'list-v2', package, phase, status, attempt]
        after = read_cursor(cursor, scope)
        ids = [i for i in self._catalogue_ids(snap, attempt=attempt, commands_only=package is not None or phase is not None)
               if after is None or i > after]
        rows, scanned, last, stopped = [], 0, after, None
        for build_id in ids:
            if len(rows) >= limit or scanned >= self.limits.scan_builds:
                stopped = 'page-limit' if len(rows) >= limit else 'scan-limit'
                break
            try:
                row = self._summary(snap, build_id, package=package, phase=phase, status=status)
            except TraceError as error:
                if error.code != 'source-too-large' or scanned == 0:
                    raise
                stopped = 'source-budget'
                break
            last, scanned = build_id, scanned + 1
            if row is not None:
                rows.append(row)
        snap.finish()
        return response('build-list', items=rows, has_more=stopped is not None,
                        next_cursor=make_cursor(last, scope) if stopped else None,
                        pagination='keyset scan continuation; an empty page can have a continuation',
                        inspection=dict(snap.metrics(), scanned_builds=scanned, scan_build_limit=self.limits.scan_builds,
                                        stopped_reason=stopped))

    @checked
    def inspect_build(self, build_id, *, cursor=None, limit=50):
        snap = self._snapshot()
        build = self._build(snap, build_id)
        commands = build.pop('commands')
        page = paginate(commands, scope=[self.scope, build_id, 'commands'], cursor=cursor, limit=limit, key=lambda c: c['order_key'])
        snap.finish()
        return response('build', **build, command_count=len(commands) if build['layout']['status'] == 'supported' else None, commands=page,
                        inspection=snap.metrics(),
                        ordering='package-directory, schema-1 phase order, numeric command index; not global time')

    @checked
    def inspect_command(self, build_id, command_id):
        snap = self._snapshot()
        kind, name = self._identity(build_id)
        if kind != 'attempt':
            raise TraceError('not-found', 'Command is not available in this build.')
        self._attempt(snap, name)
        commands = self._commands(snap, name, selected_id=command_id)
        command = next(iter(commands), None)
        if command is None:
            layout = self._layout(snap, name)
            if layout['status'] != 'supported':
                raise TraceError('unsupported-layout', 'Attempt evidence needs an owner-defined adapter.', details=layout)
            raise TraceError('not-found', 'Command is not available in this build.')
        snap.finish()
        return response('command', host_id=self.host_id, build_id=build_id, inspection=snap.metrics(), **command)

    @checked
    def logs(self, build_id, command_id, *, cursor=None, limit=50):
        limit_value(limit)
        if cursor is not None and (not isinstance(cursor, str) or len(cursor) > 4096):
            raise TraceError('invalid-cursor', 'Invalid journal cursor.')
        command = self.inspect_command(build_id, command_id)
        job_id = command['job_id']['value']
        base = dict(host_id=self.host_id, build_id=build_id, command_id=command_id, job_id=job_id,
                    entries=[], has_more=False, next_cursor=cursor, inspection=command['inspection'])
        if not job_id or self.controller is None:
            return response('logs', **base, availability='identity-unavailable' if not job_id else 'not-configured')
        try:
            page = self.controller.logs(job_id, cursor=cursor, limit=limit)
        except ValueError:
            raise TraceError('invalid-cursor', 'Journal request or cursor rejected by controller.') from None
        except Exception:
            return response('logs', **base, availability='retrieval-failure')
        if page.get('job_id') != job_id or not isinstance(page.get('entries'), list) or len(page['entries']) > limit:
            raise TraceError('invalid-record', 'Controller returned an invalid journal page.')
        status = page.get('status')
        availability = {'ok': 'available', 'cursor-unavailable': 'cursor-expired-or-unavailable',
                        'identity-unavailable': 'identity-unavailable', 'unavailable': 'retrieval-failure',
                        'empty-history': 'empty-or-expired'}.get(status, 'retrieval-failure')
        if status == 'empty-history' and command['state'] in ('prepared', 'starting', 'running'):
            availability = 'pending-or-empty'
        if status not in ('ok', 'empty-history'):
            if status == 'cursor-unavailable':
                base['next_cursor'] = None
            return response('logs', **base, availability=availability, controller_status=status)
        if type(page.get('has_more', False)) is not bool or (page.get('next_cursor') is not None and
                (not isinstance(page['next_cursor'], str) or len(page['next_cursor']) > 4096)):
            raise TraceError('invalid-record', 'Controller returned invalid journal pagination.')
        return response('logs', **{**base, 'entries': page['entries'], 'has_more': page.get('has_more', False),
                                  'next_cursor': page.get('next_cursor')}, availability=availability, controller_status=status,
                        initial_page='controller tail; continuation follows returned cursor')

    @checked
    def compare(self, before, after):
        snap = self._snapshot()
        left, right = self._build(snap, before), self._build(snap, after)
        def fields(build):
            values = {}
            for package in build['packages']:
                values['package:' + package['package_key']] = {'inputs': package['inputs']['value'], 'reuse': package['reuse']['value']}
            for c in build['commands']:
                values['command:' + c['id']] = {k: c[k]['value'] for k in ('command', 'working_directory', 'environment', 'settings')}
            return values
        a, b = redact(fields(left)), redact(fields(right))
        changes = [dict(key=k, before=a.get(k), after=b.get(k)) for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]
        snap.finish()
        return response('comparison', host_id=self.host_id, before=before, after=after, differences=changes,
                        unavailable=['Unprojected source archive/version fields', 'Redacted environment values', 'Unrecorded child commands'],
                        interpretation='Recorded differences only; no claim of reproducibility or causation.')

    @checked
    def export(self, build_id, *, command_limit=100):
        result = self.inspect_build(build_id, limit=command_limit)
        if result['commands']['has_more']:
            raise TraceError('export-too-large', 'Export exceeds command limit; retrieve command pages instead.')
        return response('export', build=result, logs_included=False,
                        provenance='Redacted inspection metadata; not a recovery record or complete source archive.')

    @checked
    def provenance(self, build_id, package, *, cursor=None, limit=20):
        from .provenance import inspect_provenance
        return inspect_provenance(self, build_id, package, cursor=cursor, limit=limit)

    @checked
    def compare_provenance(self, before, after, package):
        from .provenance import compare_provenance
        return compare_provenance(self, before, after, package)


    @checked
    def generation_provenance(self, generation, *, cursor=None, limit=20):
        from .generations import generation_provenance
        return generation_provenance(self, generation, cursor=cursor, limit=limit)

    @checked
    def generations(self, *, output=None, attempt=None, cursor=None, limit=20):
        from .generations import generations
        return generations(self, output=output, attempt=attempt, cursor=cursor, limit=limit)


    @checked
    def generation_summary(self, generation, *, cursor=None, limit=20):
        from .summaries import summary
        return summary(self, generation, cursor=cursor, limit=limit)

    @checked
    def compare_generations(self, before, after, *, cursor=None, limit=20):
        from .summaries import compare
        return compare(self, before, after, cursor=cursor, limit=limit)


    @checked
    def materials(self, subject, package, *, cursor=None, limit=20):
        from .materials import inspect_materials
        return inspect_materials(self, subject, package, cursor=cursor, limit=limit)

    @checked
    def compare_materials(self, before, after, package, *, cursor=None, limit=20):
        from .materials import compare_materials
        return compare_materials(self, before, after, package, cursor=cursor, limit=limit)
