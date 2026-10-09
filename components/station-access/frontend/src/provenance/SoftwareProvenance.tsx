import type { Application, GenerationPackage, NoticeQuery } from '../api'
import { noticeUrl } from '../api'

export function EvidenceState({ label, complete }: { label: string; complete: boolean }) {
  return <span className={`provenance-state ${complete ? 'complete' : 'incomplete'}`}>{label}: {complete ? 'Complete' : 'Incomplete'}</span>
}

export function PatchStatus({ value }: { value: GenerationPackage['patches'] }) {
  if (value.state !== 'available' || value.count === null) {
    return <span className="provenance-state unknown">Patch evidence unavailable</span>
  }
  if (value.count > 0) {
    return <span className="provenance-state patched">Patched · {value.count}</span>
  }
  return <span className="provenance-state complete">No patches recorded</span>
}

export function PackageSourceLicense({ item, noticeQuery }: { item: GenerationPackage; noticeQuery: NoticeQuery }) {
  return <details className="source-license">
    <summary>Source &amp; license</summary>
    <dl>
      <dt>Source SHA-256</dt><dd className="archive-digest">{item.source_digest ?? 'Unknown'}</dd>
      <dt>Upstream origin</dt><dd>{item.origin ? <a href={item.origin} target="_blank" rel="noreferrer">Upstream source</a> : 'Unknown'}</dd>
      <dt>License</dt><dd>{item.expression ?? 'Unknown'}</dd>
      <dt>License review</dt><dd>{item.review}</dd>
      <dt>Notice documents</dt><dd>{item.notice_count}</dd>
      <dt>Scope</dt><dd>{item.scope}</dd>
    </dl>
    {item.exceptions.length > 0 && <section><h4>Components / exceptions</h4>
      <ul>{item.exceptions.map((part, index) => <li key={index}>{part.scope} · {part.expression ?? 'Unknown'} · {part.review}{part.notes ? ` — ${part.notes}` : ''}</li>)}</ul>
    </section>}
    {item.issues.length > 0 && <section><h4>Unresolved issues</h4><ul>{item.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul></section>}
    <p><a href={noticeUrl(noticeQuery, 'text')} download>Download generation notices (.txt)</a></p>
  </details>
}

function applicationReason(reason: string | undefined) {
  if (reason === 'application-source-identity-not-published') {
    return 'Application source identity is not published by the controller yet.'
  }
  return 'Application source and license evidence is unavailable.'
}

export function ApplicationSourceLicense({ application }: { application: Application }) {
  const evidence = application.source_license
  if (evidence?.state === 'available' && evidence.href) {
    return <a className="source-license-action" href={evidence.href}>Source &amp; license</a>
  }
  return <span className="source-license-unavailable" title={applicationReason(evidence?.reason)}>Source &amp; license unavailable</span>
}
