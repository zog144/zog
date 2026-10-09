import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArchiveNotices } from './ArchiveNotices'
import { useAuth } from '../auth/AuthProvider'
import { archivesApi, ArchiveMirror, ArchiveItem } from '../api'

export function megabytes(value: number | null | undefined) {
  return value == null ? 'Unknown' : `${(value / 1_000_000).toLocaleString(undefined, { maximumFractionDigits: 6 })} MB`
}
function stamp(value: string | null) { return value ? new Date(value).toLocaleString() : 'Unknown' }

export function ArchivesPage() {
  const { user } = useAuth()
  const [mirrors, setMirrors] = useState<ArchiveMirror[]>([])
  const [mirrorCursor, setMirrorCursor] = useState<string | null>(null)
  const [selected, setSelected] = useState('')
  const [collection, setCollection] = useState('')
  const [items, setItems] = useState<ArchiveItem[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [after, setAfter] = useState<number | null>(null)
  const [history, setHistory] = useState<(number | null)[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [refresh, setRefresh] = useState(0)
  const mirror = mirrors.find(row => row.host_id === selected)
  useEffect(() => {
    if (!user?.is_superuser) return
    let active = true
    setLoading(true); setError('')
    archivesApi.mirrors().then(data => {
      if (!active) return
      setMirrors(data.mirrors); setMirrorCursor(data.next_cursor)
      setSelected(current => data.mirrors.some(row => row.host_id === current) ? current : data.mirrors[0]?.host_id ?? '')
      setAfter(null); setHistory([])
    }).catch(() => { if (active) setError('Mirror observations could not be loaded. Retry to check availability.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user?.is_superuser, refresh])
  useEffect(() => {
    setItems([]); setCursor(null)
    if (!user?.is_superuser || !mirror?.snapshot) return
    let active = true
    setLoading(true); setError('')
    archivesApi.items(mirror.host_id, mirror.snapshot, collection, after).then(data => {
      if (active) { setItems(data.items); setCursor(data.next_cursor) }
    }).catch(() => { if (active) setError('Archive observations could not be loaded. Refresh if the snapshot has changed.') })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [user?.is_superuser, mirror?.host_id, mirror?.snapshot, collection, after, refresh])
  if (!user?.is_superuser) return <p>Administrator access required.</p>
  async function moreMirrors() {
    if (!mirrorCursor) return
    setLoading(true)
    try {
      const data = await archivesApi.mirrors(mirrorCursor)
      setMirrors(current => [...current, ...data.mirrors]); setMirrorCursor(data.next_cursor)
    } catch { setError('More mirror observations could not be loaded.') }
    finally { setLoading(false) }
  }
  return <section className="archives-page"><h1>Archives</h1>
    <p>Observed source archives and root filesystems. 1 MB = 1,000,000 bytes.</p>
    <p>Read only. Mirror selection retains archives when withdrawn. Imports, deletion, retention and filesystem approval use separate workflows. Host configuration is applied through explicit host-deploy jobs.</p>
    <div className="archive-controls">
      <label>Mirror<select aria-label="Mirror" value={selected} onChange={e => { setSelected(e.target.value); setCollection(''); setAfter(null); setHistory([]) }}>
        {!mirrors.length && <option value="">No mirror records</option>}
        {mirrors.map(row => <option key={row.host_id} value={row.host_id}>{row.name} · {row.state}</option>)}
      </select></label>
      <label>Collection<select aria-label="Collection" value={collection} onChange={e => { setCollection(e.target.value); setAfter(null); setHistory([]) }}>
        <option value="">All collections</option>{mirror?.summary?.collections.map(name => <option key={name}>{name}</option>)}
      </select></label>
      <button disabled={loading} onClick={() => setRefresh(n => n+1)}>Refresh observations</button>
      {mirrorCursor && <button disabled={loading} onClick={moreMirrors}>Load more mirrors</button>}
    </div>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status">Loading observations…</p>}
    {!loading && !error && !mirrors.length && <p>No mirror roles recorded. This does not establish that any store is empty.</p>}
    {mirror && <>
      <article className="archive-pane" aria-label="Mirror observation"><h2>{mirror.name}</h2>
        <dl><dt>Host</dt><dd>{mirror.host_id}</dd><dt>Role</dt><dd>{mirror.state} · revision {mirror.role_revision}</dd>
          <dt>Observation</dt><dd>{mirror.observation_state}</dd><dt>Last catalog observation</dt><dd>{stamp(mirror.observed_at)}</dd>
          <dt>Last report</dt><dd>{stamp(mirror.last_attempt_at)}</dd><dt>Role evidence</dt><dd>{stamp(mirror.role_observed_at)}{mirror.reason ? ` · ${mirror.reason}` : ''}</dd>
          <dt>Preparation record</dt><dd>{mirror.preparation.state}{mirror.preparation.fresh ? '' : ' (not current)'}</dd><dt>Catalog records</dt><dd>{mirror.archive_count ?? 'Unknown'}</dd>
        </dl>
        {mirror.observation_state !== 'observed' && <p role="status">{mirror.snapshot ? 'Last known catalog retained. Current archive availability is unknown.' : 'No complete catalog observation available. This mirror is not known to be empty.'}</p>}
        <div className="archive-grid">
          <section><h3>Catalog sizes</h3><dl><dt>Logical archive sizes</dt><dd>{megabytes(mirror.summary?.logical_bytes)}</dd>
            <dt>Distinct content size</dt><dd>{megabytes(mirror.summary?.unique_content_bytes)}</dd>
            <dt>Allocated object blocks</dt><dd>{megabytes(mirror.summary?.allocated_object_bytes)}</dd></dl>
            <p>Logical sizes count collection records. Distinct content counts each digest once on this mirror. Allocated blocks count each object inode once, including unreferenced objects; filesystem compression or shared extents can differ.</p>
          </section>
          {mirror.summary?.filesystems.map(fs => <section key={fs.id} className="archive-pane"><h3>Filesystem {fs.id}</h3><p>{fs.stores.join(', ')}</p>
            <dl><dt>Object allocation</dt><dd>{megabytes(fs.allocated_object_bytes)}</dd><dt>Filesystem used</dt><dd>{megabytes(fs.used_bytes)}</dd><dt>Available to service</dt><dd>{megabytes(fs.available_bytes)}</dd><dt>Total capacity</dt><dd>{megabytes(fs.total_bytes)}</dd></dl>
            <p>Filesystem use includes other applications and data. Device identity is local to this host; do not add capacities across mirrors.</p>
          </section>)}
        </div>
        {!mirror.summary?.filesystems.length && <p>Filesystem measurements: Unknown</p>}
      </article>
      {!loading && !error && mirror.snapshot && !items.length && <p>{mirror.observation_state === 'observed' ? (collection ? 'No archives observed in this collection.' : 'This complete catalog observation is empty.') : 'No records in the last known catalog for this filter; current contents are unknown.'}</p>}
      {Array.from(new Set(items.map(row => row.collection))).sort().map(group => <section key={group}><h2>{group}</h2><div className="archive-grid">
        {items.filter(row => row.collection === group).map(row => <article className="archive-pane" key={row.digest}>
          <h3>{row.name ?? 'Name unknown'}</h3><dl><dt>Type</dt><dd>{row.kind === 'source' ? 'Source archive' : 'Root filesystem'}</dd>
            <dt>Version / generation</dt><dd>{row.version ?? 'Unknown'}</dd><dt>SHA-256</dt><dd className="archive-digest">{row.digest}</dd>
            <dt>Archive size</dt><dd>{megabytes(row.size_bytes)}</dd><dt>Availability</dt><dd>{mirror.observation_state === 'observed' ? row.availability : 'Unknown (old observation)'}{mirror.state === 'serving' ? ' · serving confirmed at observation' : ' · serving not confirmed'}</dd>
            <dt>Provenance</dt><dd>{row.provenance}</dd><dt>Recorded approval</dt><dd>{row.approval}</dd><dt>Filesystem</dt><dd>{row.filesystem_id ?? 'Unknown'}</dd><dt>Observed</dt><dd>{stamp(mirror.observed_at)}</dd></dl>
          {row.kind === 'root-filesystem' && row.version && <p><Link to={`/generations/${encodeURIComponent(row.version)}?${new URLSearchParams({mirror: mirror.host_id, snapshot: mirror.snapshot!, collection: row.collection, digest: row.digest})}`}>Generation provenance</Link></p>}
          <ArchiveNotices key={mirror.snapshot+row.collection+row.digest} item={row} mirror={mirror.host_id} snapshot={mirror.snapshot!}/>
        </article>)}
      </div></section>)}
      <nav className="archive-controls" aria-label="Archive pages"><button disabled={loading || !history.length} onClick={() => { setAfter(history[history.length-1]); setHistory(history.slice(0,-1)) }}>Previous archives</button>
        <button disabled={loading || cursor === null} onClick={() => { setHistory([...history, after]); setAfter(cursor) }}>Next archives</button></nav>
    </>}
  </section>
}
