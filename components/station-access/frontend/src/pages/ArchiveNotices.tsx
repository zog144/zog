import { useState } from 'react'
import { ArchiveItem, LicenseRecord, noticesApi, noticeUrl } from '../api'

export function ArchiveNotices({item,mirror,snapshot}:{item:ArchiveItem;mirror:string;snapshot:string}) {
  const [records,setRecords]=useState<LicenseRecord[]>([])
  const [next,setNext]=useState<number|null>(null)
  const [opened,setOpened]=useState(false)
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [text,setText]=useState<string|null>(null)
  const [generation,setGeneration]=useState<string|null>(null)
  const summary=item.licenses
  const query={mirror,snapshot,collection:item.collection,digest:item.digest}
  async function load(offset=0) {
    setBusy(true);setError('')
    try {
      const result=await noticesApi.metadata(query,offset)
      setRecords(result.records);setNext(result.next_offset);setOpened(true);setGeneration(result.generation)
    } catch { setError('Notice evidence is unavailable or has not reached the portal. Refresh observations and retry.') }
    finally {setBusy(false)}
  }
  async function read() {
    setBusy(true);setError('')
    try {setText(await noticesApi.text(query))}
    catch {setError('Notice text could not be loaded.')}
    finally {setBusy(false)}
  }
  return <section className="archive-notices" aria-label="Source & license">
    <h4>Source &amp; license</h4>
    {summary?.state!=='available' ? <p>{summary?.state==='broken' ? 'Notice evidence verification failed.' : summary?.state==='missing' ? 'Notice evidence missing for this archive.' : 'License information unavailable. No license is inferred.'}</p> : <>
      <p><strong>Review: {summary.review}</strong> · {summary.package_count} package records</p>
      <p>Coverage: {summary.coverage}. Retained source material: {summary.source_material}. Issues: {summary.issue_count}.</p>
      <p>Notice availability does not mean release approval. Evidence describes this exact archive, including when the mirror observation is stale.</p>
      <button disabled={busy} onClick={()=>load()}>Source &amp; license</button>
      {opened && <>
        {generation && <p>Generation: {generation}</p>}
        {records.map((record,index)=><section key={index} className="archive-pane">
          <h5>{record.package} {record.version??record.revision}</h5>
          <p><strong>{record.expression??'License unknown'}</strong> · {record.review}</p>
          <p>Stage: {record.stage??'Unknown'}</p><p>Scope: {record.scope}</p><p>Public origin: {record.origin??'Unknown'}</p>
          {record.exceptions.map((part,i)=><p key={i}>Component / exception: {part.scope} · {part.expression??'Unknown'} · {part.review}{part.notes ? ` — ${part.notes}` : ''}</p>)}
          {record.issues.map((issue,i)=><p key={i}>Unresolved / note: {issue}</p>)}
          {!record.texts.length && <p>Notice text missing for this package.</p>}
        </section>)}
        <div className="archive-controls">
          {next!==null && <button disabled={busy} onClick={()=>load(next)}>Next license records</button>}
          <button disabled={busy} onClick={read}>Read full notice document</button>
          <a href={noticeUrl(query,'text')} download>Download notices (.txt)</a>
        </div>
        <p className="archive-digest">Notice SHA-256: {summary.notice_digest}</p>
        {text!==null && <pre className="archive-notice-text">{text}</pre>}
      </>}
    </>}
    {error && <p role="alert">{error}</p>}
  </section>
}
