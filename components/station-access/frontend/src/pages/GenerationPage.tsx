import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { generationApi, type GenerationCoverage, type GenerationProvenance } from '../api'
import { EvidenceState, PackageSourceLicense, PatchStatus } from '../provenance/SoftwareProvenance'

function coverage(value: GenerationCoverage) {
  if (value.state === 'unknown' || value.complete === null || value.total === null) return 'Unknown'
  return `${value.complete} / ${value.total} ${value.state === 'complete' ? 'complete' : 'complete · incomplete'}`
}

export function GenerationPage() {
  const { generation = '' } = useParams()
  const [query] = useSearchParams()
  const [value, setValue] = useState<GenerationProvenance | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const mirror = query.get('mirror')
    const snapshot = query.get('snapshot')
    const collection = query.get('collection')
    const digest = query.get('digest')
    if (!generation || !mirror || !snapshot || !collection || !digest) {
      setError('This generation view requires an exact archive observation.')
      return
    }
    setError('')
    generationApi.detail(generation, { mirror, snapshot, collection, digest })
      .then(setValue)
      .catch(() => setError('Generation provenance could not be loaded. Refresh the archive observation and try again.'))
  }, [generation, query])

  if (error) return <section><h1>Generation</h1><p role="alert">{error}</p><p><Link to="/archives">Back to Archives</Link></p></section>
  if (!value) return <section><h1>Generation</h1><p role="status">Loading provenance…</p></section>

  const noticeQuery = {
    mirror: value.archive.mirror,
    snapshot: value.archive.snapshot,
    collection: value.archive.collection,
    digest: value.archive.digest,
  }

  return <section className="generation-page">
    <p><Link to="/archives">← Archives</Link></p>
    <h1>Generation {value.generation}</h1>
    <p>Immutable root filesystem provenance from the selected authenticated archive observation.</p>
    <p><a href={generationApi.exportUrl(value.generation, noticeQuery)}>Export provenance (.json)</a></p>

    <div className="archive-grid">
      <article className="archive-pane">
        <h2>Identity</h2>
        <dl>
          <dt>Generation</dt><dd>{value.generation}</dd>
          <dt>Rootfs SHA-256</dt><dd className="archive-digest">{value.archive.digest}</dd>
          <dt>Archive collection</dt><dd>{value.archive.collection}</dd>
          <dt>Availability</dt><dd>{value.archive.availability}</dd>
          <dt>Archive provenance</dt><dd>{value.archive.provenance}</dd>
          <dt>Recorded approval</dt><dd>{value.archive.approval}</dd>
        </dl>
      </article>
      <article className="archive-pane">
        <h2>Provenance coverage</h2>
        <dl>
          <dt>Source provenance</dt><dd>{coverage(value.coverage.source_provenance)}</dd>
          <dt>License evidence</dt><dd>{coverage(value.coverage.license_evidence)}</dd>
          <dt>Unresolved provenance</dt><dd>{value.coverage.unresolved_provenance ?? 'Unknown'}</dd>
          <dt>Retained source material</dt><dd>{value.source_material}</dd>
        </dl>
        {value.evidence_state !== 'available' && <p role="status">Package-level evidence is {value.evidence_state}. Coverage remains unknown; absence of evidence is not treated as zero unresolved items.</p>}
      </article>
    </div>

    <section>
      <h2>Contents</h2>
      {!value.packages.length && <p>Package-level provenance is not available for this generation.</p>}
      <div className="archive-grid">
        {value.packages.map((item, index) => <article className="archive-pane" key={`${item.package}:${item.version ?? item.revision}:${item.stage ?? ''}:${item.scope}:${index}`}>
          <h3>{item.package} {item.version ?? item.revision}</h3>
          <p>Stage: {item.stage ?? 'Unknown'}</p>
          <div className="provenance-strip">
            <EvidenceState label="Source" complete={item.source_complete} />
            <EvidenceState label="License" complete={item.license_complete} />
            <PatchStatus value={item.patches} />
          </div>
          <PackageSourceLicense item={item} noticeQuery={noticeQuery} />
        </article>)}
      </div>
    </section>

    <section className="archive-pane">
      <h2>Patches</h2>
      <PatchStatus value={value.patches} />
      <p>Patch records will appear here only when an evidence producer publishes them for this exact generation. No unpatched claim is inferred from current notice metadata.</p>
    </section>
    <section className="archive-pane">
      <h2>Build evidence</h2>
      <p>Build-record/build-trace evidence is not yet integrated into this view.</p>
    </section>
  </section>
}
