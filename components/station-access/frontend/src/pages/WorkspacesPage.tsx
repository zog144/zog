import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, type Workspace } from '../api'
import { useVncSessions } from '../vnc/VncSessionProvider'

export function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loaded, setLoaded] = useState(false)
  const [editing, setEditing] = useState<Workspace | 'new' | null>(null)
  const [deleting, setDeleting] = useState<Workspace | null>(null)
  const [name, setName] = useState('')
  const [network, setNetwork] = useState('default')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const { close } = useVncSessions()
  const load = async () => { const result = await api.workspaces(); setWorkspaces(result.workspaces); setLoaded(true) }
  useEffect(() => { void load().catch(reason => setError(String(reason))) }, [])
  const edit = (workspace: Workspace | 'new') => {
    setEditing(workspace); setDeleting(null); setError(null)
    setName(workspace === 'new' ? '' : workspace.name)
    setNetwork(workspace === 'new' ? 'default' : workspace.network)
  }
  const act = async (action: () => Promise<unknown>) => {
    setBusy(true); setError(null)
    try { await action(); await load() }
    catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); await load().catch(() => undefined) }
    finally { setBusy(false) }
  }
  const save = (event: FormEvent) => {
    event.preventDefault()
    void act(async () => {
      if (editing === 'new') await api.createWorkspace(name.trim(), network)
      else if (editing) await api.updateWorkspace(editing, name.trim(), network)
      setEditing(null)
    })
  }
  return <section><h1>Workspaces</h1><p>Open a workspace to start its desktop. It keeps running when you leave.</p>
    <button className="create-workspace" disabled={busy} onClick={() => edit('new')}>Create new workspace</button>
    {error && <p role="alert" className="error">{error} Reload the list before retrying a changed workspace.</p>}
    {(error || !loaded) && <button disabled={busy} onClick={() => { setEditing(null); setDeleting(null); void act(load) }}>Reload workspaces</button>}
    {editing && <form className="card workspace-editor" onSubmit={save} aria-label={editing === 'new' ? 'Create workspace' : 'Edit workspace'}>
      <h2>{editing === 'new' ? 'Create workspace' : `Edit ${editing.name}`}</h2>
      <label>Name<input autoFocus required maxLength={255} value={name} onChange={event => setName(event.target.value)} /></label>
      <label>Network<select value={network} onChange={event => setNetwork(event.target.value)}><option value="default">Default — shared host network</option></select></label>
      <p>Workspaces share the host network; this does not provide network isolation. Creating or editing a workspace does not start its desktop.</p>
      <div className="actions"><button disabled={busy || !name.trim()} type="submit">Save workspace</button><button disabled={busy} type="button" onClick={() => setEditing(null)}>Cancel</button></div>
    </form>}
    {deleting && <section className="card workspace-delete" role="region" aria-label="Confirm workspace deletion">
      <h2>Delete {deleting.name}?</h2><p>This stops its desktop and disconnects viewers. Applications attached to this workspace must be stopped first. This cannot be undone.</p>
      <div className="actions"><button disabled={busy} onClick={() => void act(async () => { await api.deleteWorkspace(deleting); close(deleting.id); setDeleting(null) })}>Delete workspace</button><button disabled={busy} onClick={() => setDeleting(null)}>Cancel</button></div>
    </section>}
    {loaded && !workspaces.length && <p>No workspaces yet. Create a workspace to get started.</p>}
    <div className="cards workspace-list">{workspaces.map(workspace => <article className="card" key={workspace.id}>
      <h2><Link to={`/vnc/${workspace.id}`}>{workspace.name}</Link></h2>
      <p>Workspace {workspace.number} · {workspace.status} · Default — shared host network</p>
      {workspace.last_error && <p className="error">{workspace.last_error}</p>}
      <div className="actions"><button disabled={busy} onClick={() => edit(workspace)} aria-label={`Edit ${workspace.name}`}>Edit</button>
      <button disabled={busy} onClick={() => { setDeleting(workspace); setEditing(null); setError(null) }} aria-label={`Delete ${workspace.name}`}>Delete</button>
      <Link to={`/workspaces/${workspace.id}/provenance`}>Provenance</Link>
      {workspace.desired_running && <button disabled={busy} onClick={() => void act(async () => { await api.stopWorkspace(workspace.id); close(workspace.id) })}>Stop desktop</button>}
      {workspace.last_error && <button disabled={busy} onClick={() => void act(() => api.reconcileWorkspace(workspace.id))}>Retry reconciliation</button>}
      </div></article>)}</div>
  </section>
}
