import { useEffect, useState } from 'react'
import { api, IdentityAdministration } from '../api'

function EnrollmentCard({request,busy,decide}: {
  request:IdentityAdministration['pending'][number];busy:boolean;
  decide:(value:Record<string,unknown>)=>Promise<void>;
}) {
  const [fingerprint,setFingerprint]=useState('')
  const [copyError,setCopyError]=useState('')
  const match=request.match
  const host=match.host
  return <article className="host-pane"><h3>{String(request.claims.hostname || 'Unnamed request')}</h3>
    <strong>{request.claimed_host_id?'Migration request':'Enrollment request'}</strong>
    <p>Full public-key fingerprint</p><code className="host-fingerprint">{request.fingerprint}</code>
    <button onClick={()=>{navigator.clipboard.writeText(request.fingerprint).catch(()=>setCopyError('Copy failed; select the full fingerprint above.'))}}>Copy fingerprint</button>
    {copyError && <p role="alert">{copyError}</p>}
    <p>Status: {request.status}. Expires: {request.expires_at}</p>
    <p>Claimed registry UUID: {request.claimed_host_id || 'none'}</p>
    <p>Reported AWS identity: {match.cloud ? `${match.cloud.account_id} / ${match.cloud.region} / ${match.cloud.instance_id}` : 'None or invalid; see reported information below'}</p>
    {match.status==='existing' && <p>Automatically selected existing host: <a href={`/hosts/${host?.id}`}>{host?.label || host?.id}</a> — {host?.id}</p>}
    {match.status==='new' && <p>Approval will create a new {match.cloud?'AWS':'non-cloud'} record.</p>}
    <p role={match.status==='conflict'?'alert':undefined}>{match.reason}</p>
    {match.status==='conflict' && <p>Resolve the conflicting record or enrollment claim explicitly, then refresh. No new record or key transfer is offered.</p>}
    {match.candidates.map(h=><p key={h.id}>Candidate: <a href={`/hosts/${h.id}`}>{h.label || 'Unlabelled'}</a> — {h.id} — {h.account_id} / {h.region} / {h.instance_id}{h.archived?' (archived)':''}</p>)}
    <details><summary>Unverified reported information</summary><pre>{JSON.stringify(request.claims,null,2)}</pre></details>
    <p>These hints select a record only. Obtain the fingerprint independently from host-deploy before confirming.</p>
    <label>Fingerprint from trusted channel <input autoComplete="off" value={fingerprint} onChange={e=>setFingerprint(e.target.value.trim())}/></label>
    <button disabled={busy || request.status!=='pending' || fingerprint!==request.fingerprint || match.status==='conflict'} onClick={()=>void decide({action:'approve',fingerprint:request.fingerprint,confirmed_fingerprint:fingerprint,host_id:host?.id || ''})}>Approve this fingerprint for this host</button>
    <button disabled={busy || request.status!=='pending'} onClick={()=>void decide({action:'reject',fingerprint:request.fingerprint})}>Reject</button>
  </article>
}

export function IdentitiesPage() {
  const [data,setData]=useState<IdentityAdministration|null>(null)
  const [error,setError]=useState('')
  const [busy,setBusy]=useState(false)
  const [policyHost,setPolicyHost]=useState('')
  const [download,setDownload]=useState(false)
  const [list,setList]=useState(false)
  const [collections,setCollections]=useState('')
  async function refresh(){ try {setData(await api.identities());setError('')} catch(e){setError(String(e))} }
  useEffect(()=>{void refresh()},[])
  async function decide(value:Record<string,unknown>){
    setBusy(true);setError('')
    try {await api.identityDecision(value);await refresh()} catch(e){setError(String(e))} finally {setBusy(false)}
  }
  return <section><h1>Host identities</h1>
    <p>Compare the full SHA-256 fingerprint through your trusted deployment connection before approving. Reported host information is unverified. Approval does not grant archive access.</p>
    {error && <p role="alert">{error}</p>}
    <button disabled={busy} onClick={()=>void refresh()}>Refresh</button>
    <h2>Enrollment requests</h2>
    {data && !error && data.pending.length===0 && <p>No enrollment requests. No new beacons with an unapproved fingerprint have been received.</p>}
    <div className="host-pane-grid">{data?.pending.map(p=><EnrollmentCard key={p.fingerprint+':'+JSON.stringify(p.match)} request={p} busy={busy} decide={decide}/>)}</div>
    <h2>Approved and revoked identities</h2>
    {data?.identities.map(i=><article key={i.fingerprint}><p>Host: {i.host_id}</p><code>{i.fingerprint}</code>
      <p>{i.status}; approved by {i.approved_by} at {i.approved_at}</p>
      <button disabled={busy || i.status!=='approved'} onClick={()=>{if(window.confirm('Revoke this key? Existing archive tokens may remain usable for up to 15 minutes plus 5 seconds.'))void decide({action:'revoke',fingerprint:i.fingerprint})}}>Revoke key</button></article>)}
    <h2>Archive permissions</h2><p>No permissions are granted by default. Empty permissions withdraw access on the next successful heartbeat. Existing tokens may remain usable until expiry.</p>
    <label>Host <select value={policyHost} onChange={e=>{const id=e.target.value;setPolicyHost(id);const p=data?.policies.find(p=>p.host_id===id);setDownload(p?.operations.includes('download') || false);setList(p?.operations.includes('list') || false);setCollections(p?.collections.join(', ') || '')}}><option value="">Select a host</option>{data?.hosts.map(h=><option key={h.id} value={h.id}>{h.label || h.id}</option>)}</select></label>
    <label><input type="checkbox" checked={download} onChange={e=>setDownload(e.target.checked)}/> Download</label>
    <label><input type="checkbox" checked={list} onChange={e=>setList(e.target.checked)}/> List</label>
    <label>Collections (comma separated identifiers) <input value={collections} onChange={e=>setCollections(e.target.value)}/></label>
    <button disabled={busy || !policyHost} onClick={()=>void decide({action:'policy',host_id:policyHost,operations:[...(download?['download']:[]),...(list?['list']:[])],collections:collections.split(',').map(x=>x.trim()).filter(Boolean)})}>Save archive permissions</button>
    <h2>Recent decisions</h2><ul>{data?.audit.map(a=><li key={a.id}>{a.created_at} — {a.actor}: {a.action} {a.fingerprint}</li>)}</ul>
  </section>
}
