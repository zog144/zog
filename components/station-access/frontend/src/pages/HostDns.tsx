import { AdditionalHostDns } from './AdditionalHostDns'
import { useState } from 'react'
import { api, type RegistryHost, type DnsMembershipReview } from '../api'

const stamp = (value: string | null) => value ? new Date(value).toLocaleString() : 'Never'
const statuses: Record<string,string> = {pending:'Pending',applying:'Applying',synchronized:'Synchronized',unpublished:'Unpublished',waiting_verification:'Waiting for verification',conflict:'Conflict',provider_error:'Provider error',storage_error:'Storage error'}
export function HostDns({host,suffix,refresh,writer}: {host: RegistryHost; suffix: string; writer?:string; refresh: () => void}) {
  const [label,setLabel]=useState('')
  const [saving,setSaving]=useState(false)
  const [error,setError]=useState('')
  const [review,setReview]=useState<DnsMembershipReview|null>(null)
  const [attempted,setAttempted]=useState(false)
  const dns=host.dns
  async function reviewChange(action:'reserve'|'release') {
    setSaving(true);setError('')
    try {setReview(await api.reviewHostDns(host.id,action,action==='reserve'?label:undefined));setAttempted(false)}
    catch(e) {setError(String(e))} finally {setSaving(false)}
  }
  async function commitReview() {
    if(!review)return
    setSaving(true);setError('');setAttempted(true)
    try {await api.commitHostDns(host.id,review.review_id);setReview(null);setAttempted(false);refresh()}
    catch(e) {setError(String(e))} finally {setSaving(false)}
  }
  async function update(enabled: boolean) {
    if(writer==='shared' && !dns){await reviewChange('reserve');return}
    setSaving(true);setError('')
    try {await api.hostDns(host.id,enabled,dns ? undefined : label);refresh()}
    catch(e) {setError(String(e))}
    finally {setSaving(false)}
  }
  if (!suffix && !dns) return null
  return <div className="host-dns">
    {dns ? <><strong>Assigned DNS</strong><div><code>{dns.name}</code> <button onClick={()=>navigator.clipboard.writeText(dns.name).catch(()=>setError('Copy failed; select the hostname to copy it.'))}>Copy DNS</button></div>
      <p><strong>{statuses[dns.status] || dns.status}</strong>{!dns.enabled && ' · publication disabled'}</p>
      <details><summary>DNS synchronization</summary>
        <p>This name stays reserved when the display label changes or the host stops.</p>
        <dl className="host-details"><dt>Desired record</dt><dd>{dns.desired_action === 'present' ? dns.desired_address : dns.desired_action === 'absent' ? 'Absent' : 'Waiting for verified address'}</dd>
        <dt>Last observed IP</dt><dd>{dns.observed_address || 'No record observed'}</dd>
        <dt>Last successful check</dt><dd>{stamp(dns.last_success)}</dd><dt>Last DNS change</dt><dd>{stamp(dns.last_change)}</dd>
        <dt>Last attempt</dt><dd>{stamp(dns.last_attempt)}</dd><dt>Next retry</dt><dd>{dns.next_attempt ? stamp(dns.next_attempt) : 'Next reconciliation'}</dd></dl>
        <p>DNS-only A record · TTL {writer === 'shared' ? 300 : 60} seconds. Cached answers may persist after removal.</p>
      </details>
      {dns.error && <p className={dns.status === 'waiting_verification' ? '' : 'error'}>{dns.error}</p>}
      <button disabled={saving || !!review || !suffix} onClick={()=>void update(!dns.enabled)}>{dns.enabled ? 'Unpublish DNS' : 'Enable DNS'}</button>
      {writer==='shared' && !dns.enabled && dns.desired_action==='absent' && !dns.record_id && <button disabled={saving || !!review} onClick={()=>void reviewChange('release')}>Review name release</button>}
    </> : host.provider === 'aws' && host.enrolled ? <details><summary>Assign DNS name</summary>
      <form onSubmit={e=>{e.preventDefault();void update(true)}}><label>DNS label <input required pattern="[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?" maxLength={63} value={label} onChange={e=>setLabel(e.target.value)} /></label><p>.{suffix}</p><button disabled={saving || !!review}>{writer==='shared'?'Review DNS reservation':'Reserve & publish'}</button></form>
      <p>Publication waits for verified AWS inventory and a matching heartbeat.</p>
    </details> : <small>DNS requires enrollment and address verification.</small>}
    {review && <section aria-label="DNS change review"><p>{review.action==='reserve'?'Reserve and enable publication of':'Release for reuse'} <strong>{review.name}</strong>?</p>
      <p>{review.action==='release'?'This removes the assignment and allows another host to reserve the name. Audit history is retained.':'The controller publishes after rechecking host evidence.'}</p>
      <button disabled={saving} onClick={()=>void commitReview()}>{attempted?'Resume DNS change':'Confirm DNS change'}</button>
      {!attempted && <button disabled={saving} onClick={()=>setReview(null)}>Dismiss review</button>}
      <details><summary>Recovery reference</summary><code>{review.review_id}</code><p>Retain this reference if completion is interrupted.</p></details></section>}
    <AdditionalHostDns host={host} refresh={refresh}/>
    {error && <p role="alert">{error}</p>}
  </div>
}
