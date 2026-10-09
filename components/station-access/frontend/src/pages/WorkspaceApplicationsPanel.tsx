import { PreflightChecks } from './WorkspaceReadinessPanel'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Runtime, type WorkspaceApplications, type WorkspacePreflight } from '../api'
import { ApplicationSourceLicense } from '../provenance/SoftwareProvenance'

export function WorkspaceApplicationsPanel({ workspaceId, onClose }: { workspaceId: string; onClose: () => void }) {
  const [preflight, setPreflight] = useState<{ name: string; value: WorkspacePreflight } | null>(null)
  const [checking, setChecking] = useState(false)
  const diagnosticRequest = useRef<AbortController | null>(null)
  useEffect(() => () => diagnosticRequest.current?.abort(), [])
  const checkApplication = async (name: string) => {
    diagnosticRequest.current?.abort()
    const abort = new AbortController(); diagnosticRequest.current = abort
    setChecking(true); setPreflight(null)
    try {
      const value = await api.workspacePreflight(workspaceId, name, abort.signal)
      if (!abort.signal.aborted) setPreflight({ name, value })
    } catch {
      if (!abort.signal.aborted) setPreflight({ name, value: { status: 'unable-to-verify', advisory: true, checks: [] } })
    } finally { if (!abort.signal.aborted) setChecking(false) }
  }
  const [data, setData] = useState<WorkspaceApplications | null>(null)
  const [query, setQuery] = useState('')
  const [error, setError] = useState('')
  const [actionError, setActionError] = useState('')
  const [notice, setNotice] = useState('')
  const [stale, setStale] = useState(true)
  const [refresh, setRefresh] = useState(0)
  const [selected, setSelected] = useState<Runtime | null>(null)
  const [busy, setBusy] = useState(false)
  const [retryLaunch, setRetryLaunch] = useState<{ application: string; id: string } | null>(null)
  const mutation = useRef(false)
  const mounted = useRef(true)
  const request = useRef<AbortController | null>(null)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      if (!document.hidden && !mutation.current) {
        const controller = new AbortController(); request.current = controller
        try {
          const result = await api.workspaceApplications(workspaceId, controller.signal)
          if (active && !controller.signal.aborted) { setData(result); setStale(false); setError('') }
        } catch (reason) {
          if (active && !controller.signal.aborted) { setStale(true); setError(reason instanceof Error ? reason.message : String(reason)) }
        }
      }
      if (active) timer = setTimeout(poll, 5000)
    }
    void poll()
    return () => { active = false; clearTimeout(timer); request.current?.abort() }
  }, [workspaceId, refresh])
  const stop = async () => {
    if (!selected || mutation.current) return
    mutation.current = true; request.current?.abort(); setBusy(true); setActionError(''); setNotice('')
    try {
      const result = await api.stopWorkspaceApplication(workspaceId, selected.runtime_id)
      if (mounted.current) { setSelected(null); setNotice(result.stopped ? 'Application stopped.' : 'Stop requested; termination is not yet confirmed.') }
    } catch (reason) {
      if (mounted.current) { setActionError(reason instanceof Error ? reason.message : String(reason)); setStale(true) }
    } finally {
      mutation.current = false
      if (mounted.current) { setBusy(false); setRefresh(value => value + 1) }
    }
  }
  const launch = async (application: string, id: string = crypto.randomUUID()) => {
    if (mutation.current) return
    mutation.current = true; request.current?.abort(); setBusy(true); setActionError(''); setNotice('')
    setRetryLaunch({ application, id })
    try {
      await api.launchWorkspaceApplication(workspaceId, application, id)
      if (mounted.current) { setRetryLaunch(null); setNotice('Launch recorded. Runtime status and logs are available below.') }
    } catch (reason) {
      if (mounted.current) { setActionError(reason instanceof Error ? reason.message : String(reason)); setStale(true) }
    } finally {
      mutation.current = false
      if (mounted.current) { setBusy(false); setRefresh(value => value + 1) }
    }
  }
  const cancelLaunch = async (id: string) => {
    if (mutation.current) return
    mutation.current = true; request.current?.abort(); setBusy(true); setActionError('')
    try {
      const result = await api.cancelWorkspaceLaunch(workspaceId, id)
      if (mounted.current) {
        if (['cancelled', 'accepted'].includes(result.state)) setRetryLaunch(null)
        setNotice(result.state === 'cancelled' ? 'Pending launch cancelled.' : result.state === 'accepted' ? 'Launch was already accepted. Use Stop application to terminate its runtime.' : 'Cancellation remains unresolved; the launch claim is retained.')
      }
    } catch (reason) {
      if (mounted.current) setActionError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      mutation.current = false
      if (mounted.current) { setBusy(false); setRefresh(value => value + 1) }
    }
  }
  const search = query.trim().toLocaleLowerCase()
  const applications = data?.applications.filter(application => `${application.name} ${application.description ?? ''}`.toLocaleLowerCase().includes(search)) ?? []
  return <aside id="workspace-applications" className="workspace-applications-panel" aria-label="Workspace applications" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}>
    <div className="panel-heading"><h2>Applications</h2><button onClick={onClose} aria-label="Close application panel">Close</button></div>
    <p>{data ? `Workspace: ${data.workspace.name}` : 'Loading workspace applications…'}</p>
    <label className="application-search">Search applications<input autoFocus type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Name or description" /></label>
    {error && <p className="error" role="alert">{error}</p>}
    {actionError && <p className="error" role="alert">{actionError}</p>}
    {notice && <p role="status">{notice}</p>}
    <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>Refresh applications</button>
    {stale && data && <p>Information may be out of date. Application controls are paused until refresh succeeds.</p>}
    {checking && <p role="status">Checking application readiness…</p>}
    {preflight && <section aria-label="Application launch checks"><h3>{preflight.name}</h3><p>Result from the last check. Check again after configuration changes.</p><PreflightChecks value={preflight.value} /></section>}
    {data && <>
      <section aria-label="Launch application"><h3>Launch application</h3>
        <p className="launch-unavailable">{data.launch.reason}</p>
        {!data.applications.length && <p>No applications are available to your account.</p>}
        {!!data.applications.length && !applications.length && <p>No applications match your search.</p>}
        <ul className="application-choices">{applications.map(application => <li key={application.name}>
          <button disabled={checking || busy} onClick={() => void checkApplication(application.name)} aria-label={`Check ${application.name}`}>Check readiness</button>
          <strong>{application.name}</strong><p>{application.description || 'No description provided.'}</p>
          <div className="actions"><button disabled={busy || stale || !data.launch.available || !application.eligible || !!retryLaunch || data.launch_actions?.some(action => ['pending', 'uncertain'].includes(action.state) && action.application === application.name)} title={!application.eligible ? application.reason || data.launch.reason : data.launch.reason} aria-label={`Launch ${application.name}`} onClick={() => void launch(application.name)}>{data.launch.available && application.eligible ? 'Launch' : 'Launch · Unavailable'}</button>
          <ApplicationSourceLicense application={application} /></div>
        </li>)}</ul>
      </section>
      {retryLaunch && <p>Launch outcome needs checking. <button disabled={busy || stale || !data.launch.available} onClick={() => void launch(retryLaunch.application, retryLaunch.id)}>Retry same launch</button> {data.launch_actions?.some(action => action.id === retryLaunch.id) && <button disabled={busy || stale} onClick={() => void cancelLaunch(retryLaunch.id)}>Cancel pending launch</button>}</p>}
      {data.launch_actions?.filter(action => ['pending', 'uncertain'].includes(action.state) && action.id !== retryLaunch?.id).map(action => <p key={action.id}>{action.application}: {action.state}. <button disabled={busy || stale || !data.launch.available} onClick={() => void launch(action.application, action.id)}>Retry recorded launch</button> <button disabled={busy || stale} onClick={() => void cancelLaunch(action.id)}>Cancel pending launch</button></p>)}
      <section aria-label="Applications in this workspace"><h3>Applications in this workspace</h3>
        <p>{data.membership.authoritative ? `Controller membership. ${data.membership.pending_count ?? 0} pending ownership claims; ${data.membership.cleanup_count ?? 0} runtimes awaiting cleanup.` : 'Recorded runtime state; pending launches may not appear yet.'} Refreshes every five seconds while this panel is visible.</p>
        {!data.runtimes.length && <p>No recorded applications are attached to this workspace.</p>}
        <ul className="application-choices">{data.runtimes.map(runtime => <li key={runtime.runtime_id}>
          <strong>{runtime.application_name}</strong><p>{runtime.instance_id} · Recorded: {runtime.state}{["terminated", "failed"].includes(runtime.state) && runtime.cleanup_pending ? " · Cleanup pending" : ""}</p>
          <div className="actions"><Link to={`/runtimes/${encodeURIComponent(runtime.runtime_id)}`}>View logs</Link>
          {(!['terminated','failed'].includes(runtime.state) || runtime.cleanup_pending) && <button disabled={busy || stale} onClick={() => { setSelected(runtime); setNotice('') }} aria-label={`Stop ${runtime.instance_id}`}>Stop application</button>}</div>
        </li>)}</ul>
      </section>
    </>}
    {selected && <section className="application-stop-confirmation" aria-label="Confirm application stop">
      <h3>Stop {selected.instance_id}?</h3><p>This stops all programs in this application runtime. Unsaved work may be lost. The workspace desktop stays running.</p>
      <div className="actions"><button disabled={busy || stale} onClick={() => void stop()}>Confirm stop</button><button disabled={busy} onClick={() => setSelected(null)}>Cancel</button></div>
    </section>}
  </aside>
}
