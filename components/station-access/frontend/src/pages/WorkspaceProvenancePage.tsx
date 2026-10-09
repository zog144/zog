import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type WorkspaceProvenance, type WorkspaceProvenanceRuntime } from '../api'

function generationStatus(runtime: WorkspaceProvenanceRuntime) {
  if (!runtime.generation) return 'No launched generation recorded'
  switch (runtime.generation_resolution) {
    case 'resolved': return 'Matched to an observed root filesystem'
    case 'unresolved': return 'Generation is not present in the archive observations known to this station'
    case 'conflict': return `Conflicting root filesystem digests observed (${runtime.generation_candidate_count})`
    case 'ambiguous': return 'Too many archive observations to resolve safely'
    default: return 'Generation provenance is unknown'
  }
}

function generationHref(runtime: WorkspaceProvenanceRuntime) {
  const value = runtime.generation_archive
  if (!runtime.generation || !value) return null
  const query = new URLSearchParams({
    mirror: value.mirror,
    snapshot: value.snapshot,
    collection: value.collection,
    digest: value.digest,
  })
  return `/generations/${encodeURIComponent(runtime.generation)}?${query}`
}

export function WorkspaceProvenancePage() {
  const { workspaceId = '' } = useParams()
  const [value, setValue] = useState<WorkspaceProvenance | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const controller = new AbortController()
    setError('')
    api.workspaceProvenance(workspaceId, controller.signal)
      .then(setValue)
      .catch(reason => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : String(reason))
      })
    return () => controller.abort()
  }, [workspaceId])

  if (error) return <section><h1>Workspace provenance</h1><p role="alert">{error}</p><p><Link to="/workspaces">← Workspaces</Link></p></section>
  if (!value) return <section><h1>Workspace provenance</h1><p role="status">Loading workspace provenance…</p></section>

  return <section className="workspace-provenance">
    <p><Link to="/workspaces">← Workspaces</Link></p>
    <h1>{value.workspace.name} · Provenance</h1>
    <p>This view follows immutable runtime history. It shows the generation recorded when each runtime was launched; it does not re-resolve the current application specification.</p>
    <p>Workspace {value.workspace.number} · Evidence basis: immutable runtime history.</p>

    {!value.runtimes.length && <p>No recorded runtime provenance is available for this workspace.</p>}
    <div className="archive-grid">
      {value.runtimes.map(runtime => {
        const detail = generationHref(runtime)
        return <article className="archive-pane" key={runtime.runtime_id}>
          <div className="provenance-runtime-heading">
            <h2>{runtime.application}</h2>
            <span className="provenance-state">{runtime.role === 'desktop' ? 'Workspace desktop' : 'Application'}</span>
          </div>
          <dl>
            <dt>Runtime identity</dt><dd className="archive-digest">{runtime.runtime_id}</dd>
            <dt>Instance</dt><dd>{runtime.instance_id}</dd>
            <dt>Recorded state</dt><dd>{runtime.state}</dd>
            <dt>Launched generation</dt><dd>{runtime.generation ?? 'Unknown'}</dd>
            <dt>Generation resolution</dt><dd>{generationStatus(runtime)}</dd>
            <dt>Rootfs SHA-256</dt><dd className="archive-digest">{runtime.generation_digest ?? 'Unknown'}</dd>
          </dl>
          <div className="actions">
            <Link to={`/runtimes/${encodeURIComponent(runtime.runtime_id)}`}>Runtime details &amp; logs</Link>
            {detail && value.administrator_generation_details
              ? <Link to={detail}>Generation provenance</Link>
              : runtime.generation_resolution === 'resolved'
                ? <span className="source-license-unavailable">Detailed generation provenance is administrator-only</span>
                : null}
          </div>
        </article>
      })}
    </div>
  </section>
}
