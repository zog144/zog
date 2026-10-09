import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type WorkspacePreflight, type WorkspaceReadiness } from '../api'

export function PreflightChecks({ value }: { value: WorkspacePreflight }) {
  return <div><p>Launch checks: {value.status.replaceAll('-', ' ')}. These checks do not start an application or guarantee a successful launch.</p>
    <ul className="readiness-checks">{value.checks.map((check, index) => <li key={`${check.code}-${index}`}><strong>{check.title}</strong> · {check.status.replaceAll('-', ' ')}<p>{check.detail}</p></li>)}</ul>
  </div>
}

export function WorkspaceReadinessPanel({ workspaceId, onConnect, onApplications, onClose, onStopped }: { workspaceId: string; onConnect: () => void; onApplications: () => void; onClose: () => void; onStopped?: () => void }) {
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  const [data, setData] = useState<WorkspaceReadiness | null>(null)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const [stale, setStale] = useState(true)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState(false)
  const [notice, setNotice] = useState('')
  useEffect(() => {
    let active = true
    const abort = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    const read = async () => {
      try {
        const result = await api.workspaceReadiness(workspaceId, abort.signal)
        if (active) { setData(result); setError(''); setStale(false) }
      } catch {
        if (active) { setError('Workspace status is unavailable. Refresh to try again.'); setStale(true) }
      }
      if (active) timer = setTimeout(read, 10000)
    }
    if (!busy) void read()
    return () => { active = false; abort.abort(); clearTimeout(timer) }
  }, [workspaceId, refresh, busy])
  const stop = async () => {
    setBusy(true); setNotice('')
    try {
      await api.stopWorkspace(workspaceId)
      if (mounted.current) { setNotice('Desktop stop completed. Refreshing observations.'); setConfirm(false); onStopped?.() }
    } catch {
      if (mounted.current) { setNotice('Stop or cancellation is unresolved. Original launch evidence is retained; refresh before retrying.'); setStale(true) }
    } finally { if (mounted.current) { setBusy(false); setRefresh(value => value + 1) } }
  }
  return <aside className="workspace-readiness-panel" aria-label="Workspace status" onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); onClose() } }}>
    <div className="panel-heading"><h2>Workspace status</h2><button onClick={onClose}>Close status</button></div>
    <p>Applications and logs remain accessible while the desktop is unavailable. Networking is shared with the host.</p>
    <button onClick={onApplications}>Applications and logs</button>
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">Checking controller and desktop…</p>}
    {data && <>
      <p>Observed: {new Date(data.observed_at).toLocaleString()}{stale ? ' · Out of date' : ''}</p>
      <dl><dt>Controller</dt><dd>{data.controller}</dd><dt>Desktop</dt><dd>{data.desktop.replaceAll('-', ' ')}</dd></dl>
      {data.desktop === 'running' && <p>The desktop process is running; display access has not been verified.</p>}
      {data.desktop === 'ready' && <p>Controller display probes passed. Browser connectivity is verified only by connecting the viewer.</p>}
      {data.registration === 'legacy-recovery-required' && <p role="alert">Older desktop launch evidence requires administrator recovery. It will not be cleared automatically.</p>}
      {data.launch_pending && <p>Desktop launch is pending or unresolved. Connect retries the original request; it does not create a replacement request.</p>}
      {data.desktop_runtime_id && <Link to={`/runtimes/${encodeURIComponent(data.desktop_runtime_id)}`}>View desktop logs</Link>}
      <p>Pending controller claims: {data.pending_count ?? 'Not verified'} · Runtimes awaiting cleanup: {data.cleanup_count ?? 'Not verified'}</p>
      {!!data.pending_count && <p>Controller claims may include externally requested work. Claims without a recorded launch action require controller-side recovery.</p>}
      {data.cleanup_pending && <p>Desktop cleanup is pending. A stopped process does not yet prove its resources are released.</p>}
      {!!data.launch_actions.length && <section aria-label="Recorded launch recovery"><h3>Launch recovery</h3><ul>{data.launch_actions.map(action => <li key={action.id}>{action.application}: {action.state}. Use Applications and logs to retry this recorded launch or request cancellation.</li>)}</ul></section>}
      {data.preflight && <PreflightChecks value={data.preflight} />}
      <div className="actions">
        <button disabled={busy || stale || data.controller !== 'available' || data.registration === 'legacy-recovery-required'} onClick={onConnect}>Connect desktop</button>
        {(data.launch_pending || data.desktop_runtime_id) && <button disabled={busy || stale || data.controller !== 'available'} onClick={() => setConfirm(true)}>Stop or cancel desktop</button>}
      </div>
    </>}
    <button disabled={busy} onClick={() => setRefresh(value => value + 1)}>Refresh status</button>
    {notice && <p role="status">{notice}</p>}
    {confirm && <section aria-label="Confirm desktop stop"><h3>Stop this desktop?</h3><p>Unsaved desktop work may be lost. Pending application launches must be resolved first. An uncertain cancellation keeps its original request.</p><button disabled={busy || stale} onClick={() => void stop()}>Confirm desktop stop</button><button disabled={busy} onClick={() => setConfirm(false)}>Keep desktop</button></section>}
  </aside>
}
