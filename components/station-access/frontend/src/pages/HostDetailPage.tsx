import {useEffect,useState} from 'react'
import {Link,useParams} from 'react-router-dom'
import {api,RemovalPreview,type HostGenerationPreview,type HostGenerationSlot} from '../api'

function generationHref(slot:HostGenerationSlot){
 if(slot.resolution!=='resolved'||!slot.archive)return null
 const query=new URLSearchParams({mirror:slot.archive.mirror,snapshot:slot.archive.snapshot,collection:slot.archive.collection,digest:slot.archive.digest})
 return `/generations/${encodeURIComponent(slot.generation)}?${query}`
}

function HostGeneration({value}:{value:HostGenerationPreview|null}){
 if(!value)return <section><h3>Host generation</h3><p>No managed host generation identity has been reported.</p></section>
 if('state' in value)return <section><h3>Host generation</h3><p role="alert">Retained host generation evidence is invalid and was not interpreted.</p></section>
 return <section className="host-pane"><h3>Host generation</h3>
  <p>Evidence source: {value.source}. Last received: {value.received_at || 'unknown'}.</p>
  <dl>
   <dt>Installation ID</dt><dd><code>{value.installation.installation_id}</code></dd>
   <dt>Installation record</dt><dd><code>{value.installation.record_id}</code> · schema {value.installation.record_schema} · {value.installation.operation}</dd>
   <dt>Selected HOST slot</dt><dd>{value.selected_slot}</dd>
   <dt>Actually booted HOST slot</dt><dd>{value.booted_slot ?? 'Not proved — transitional/non-HOST root'}</dd>
  </dl>
  <div className="archive-grid">{(['HOST-A','HOST-B'] as const).map(name=>{
   const slot=value.slots[name]
   if(!slot)return <article className="archive-pane" key={name}><h4>{name}</h4><p>Generation identity unknown.</p></article>
   const href=generationHref(slot)
   return <article className="archive-pane" key={name}><h4>{name}{value.booted_slot===name?' · Booted':''}{value.selected_slot===name?' · Selected':''}</h4>
    <dl>
     <dt>Generation</dt><dd>{slot.generation}</dd>
     <dt>Root PARTUUID</dt><dd><code>{slot.root_partuuid}</code></dd>
     <dt>Archive resolution</dt><dd>{slot.resolution}{slot.resolution==='conflict'? ` · ${slot.candidate_count} distinct rootfs digests`:''}</dd>
     <dt>Rootfs SHA-256</dt><dd className="archive-digest">{slot.digest ?? 'Unknown'}</dd>
    </dl>
    {href&&<p><Link to={href}>Generation provenance</Link></p>}
   </article>
  })}</div>
  <h4>Transitional boot bundle</h4>
  {value.transitional_boot_bundle?<dl>
   <dt>Provider</dt><dd>{value.transitional_boot_bundle.provider}</dd>
   <dt>Record reference</dt><dd><code>{value.transitional_boot_bundle.record_reference}</code></dd>
   <dt>Record SHA-256</dt><dd className="archive-digest">{value.transitional_boot_bundle.record_sha256}</dd>
  </dl>:<p>No transitional boot-bundle identity recorded.</p>}
 </section>
}

export function HostDetailPage(){
 const {hostId=''}=useParams()
 const [preview,setPreview]=useState<RemovalPreview|null>(null)
 const [confirmation,setConfirmation]=useState('')
 const [error,setError]=useState('')
 const [busy,setBusy]=useState(false)
 const [reviewing,setReviewing]=useState(false)
 async function refresh(){setError('');setConfirmation('');try{setPreview(await api.hostRemovalPreview(hostId))}catch(e){setError(String(e));setPreview(null)}}
 useEffect(()=>{setPreview(null);setReviewing(false);void refresh()},[hostId])
 async function submit(){
  if(!preview)return
  setBusy(true);setError('')
  try{await api.hostRemoval(hostId,preview.archived_at?'restore':'archive',preview.revision,confirmation);setReviewing(false);await refresh()}
  catch(e){setError(String(e));setConfirmation('')}
  finally{setBusy(false)}
 }
 return <section><h1>Host record details</h1><Link to="/hosts">Back to hosts</Link>
  {error && <p role="alert">{error}</p>}
  <button disabled={busy} onClick={()=>void refresh()}>Refresh dependencies</button>
  {preview && <><h2>{preview.host.label || 'Unlabelled host'}</h2>
   <p>Registry UUID: <code>{preview.host.id}</code></p>
   <p>Provider: {preview.host.provider}. AWS account / region / instance: {preview.host.account_id || 'none'} / {preview.host.region || 'none'} / {preview.host.instance_id || 'none'}</p>
   {preview.archived_at && <p>Archived at {preview.archived_at} by {preview.archived_by}</p>}
   <p>{preview.explanation}</p>
   <HostGeneration value={preview.host_generation}/>
   <h3>Associated identities</h3>{preview.identities.length ? <ul>{preview.identities.map(k=><li key={k.fingerprint}><code className="host-fingerprint">{k.fingerprint}</code> — {k.status}; approved by {k.approved_by} at {k.approved_at}; revoked {k.revoked_at || 'never'}</li>)}</ul>:<p>No identities</p>}
   <h3>Credentials and archive permissions</h3>
   <p>Legacy credential: {preview.legacy_credential_active?'active — blocks archival':'inactive or absent'}</p>
   <p>Station login credential: {preview.station_credential?`stored, revision ${preview.station_credential.revision}`:'none'}</p>
   <p>Archive operations: {preview.archive_policy?.operations.join(', ') || 'none'}. Collections: {preview.archive_policy?.collections.join(', ') || 'none'}</p>
   <p>Conservative token expiry bound: {preview.possible_token_expiry || 'none'}</p>
   <h3>Mirror role</h3><p>{preview.mirror_role?`${preview.mirror_role.selected?'Selected':'Unselected'}; ${preview.mirror_role.reported_state}; revision ${preview.mirror_role.revision}, acknowledged ${preview.mirror_role.acknowledged_revision}; ${preview.mirror_role.endpoint}; runtime ${preview.mirror_role.runtime_id || 'none'}`:'No role'}</p>
   <h3>Managed DNS</h3>{preview.dns.length?<ul>{preview.dns.map(d=><li key={d.name}>{d.name} — {d.enabled?'enabled':'disabled, reservation retained'} — {d.status} — provider record {d.record_id || 'none'}</li>)}</ul>:<p>No managed DNS assignment</p>}
   <h3>Pending migration fingerprints</h3>{preview.pending_fingerprints.map(f=><p key={f}><code className="host-fingerprint">{f}</code></p>)}{!preview.pending_fingerprints.length && <p>None</p>}
   {!!preview.blockers.length && <div role="alert"><strong>Archival blocked</strong><ul>{preview.blockers.map(b=><li key={b}>{b}</li>)}</ul></div>}
   <button disabled={busy || (!preview.archived_at && !preview.can_archive)} onClick={()=>setReviewing(true)}>{preview.archived_at?'Review restoration':'Remove record (archive)'}</button>
   {reviewing && <div className="host-pane"><p>{preview.archived_at?'Restore this record to the active list. This does not approve a key or restore revoked credentials.':'Archive this command-center record only. This does not stop or terminate an EC2 instance. All history is retained.'}</p>
    <label>Confirm registry UUID <input value={confirmation} onChange={e=>setConfirmation(e.target.value.trim())}/></label>
    <button disabled={busy || confirmation!==preview.host.id} onClick={()=>void submit()}>{preview.archived_at?'Confirm restoration':'Confirm archival'}</button>
    <button disabled={busy} onClick={()=>{setReviewing(false);setConfirmation('')}}>Cancel</button>
   </div>}
  </>}
 </section>
}
