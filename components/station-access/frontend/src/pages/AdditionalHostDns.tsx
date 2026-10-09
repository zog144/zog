import {useEffect,useState} from 'react'
import {api,type RegistryHost,type DnsDestination,type AdditionalDnsAssignment} from '../api'

export function AdditionalHostDns({host,refresh}:{host:RegistryHost;refresh:()=>void}) {
 const [destinations,setDestinations]=useState<DnsDestination[]>([])
 const [error,setError]=useState('')
 const [busy,setBusy]=useState(false)
 const [target,setTarget]=useState('')
 const [label,setLabel]=useState('')
 const [release,setRelease]=useState<string|null>(null)
 useEffect(()=>{let live=true;async function load(){try{const result=await api.dnsDestinations();if(live)setDestinations(result.destinations)}catch{if(live && host.additional_dns?.length)setError('DNS destinations could not be loaded.')}}void load();return()=>{live=false}},[host.id])
 async function change(binding:string,action:string,row?:AdditionalDnsAssignment) {
  setBusy(true);setError('')
  try {await api.additionalDns(host.id,binding,action,row?.revision,action==='reserve'?(row?.name.slice(0,-row.prefix.length-1)||label):undefined);setRelease(null);refresh()}
  catch(e){setError(String(e))}finally{setBusy(false)}
 }
 const assignments=host.additional_dns||[]
 const available=destinations.filter(d=>!assignments.some(a=>a.binding_id===d.id))
 if(!assignments.length && !available.length)return null
 return <section aria-label="Additional DNS destinations">
  {assignments.map(row=><section key={row.id} aria-label={row.name}>
   <strong>{row.provider} DNS</strong><p><code>{row.name}</code></p>
   <p>{row.status} · {row.observed_address||'No address observed'} · TTL {row.ttl}s</p>
   {row.error && <p role="alert">{row.error}</p>}
   {row.phase==='reserving'?<><button disabled={busy} onClick={()=>void change(row.binding_id,'reserve',row)}>Resume DNS reservation</button><button disabled={busy} onClick={()=>void change(row.binding_id,'cancel',row)}>Discard uncommitted reservation</button></>:
    row.phase==='releasing'?<button disabled={busy} onClick={()=>void change(row.binding_id,'release',row)}>Resume DNS release</button>:
    <button disabled={busy} onClick={()=>void change(row.binding_id,row.enabled?'unpublish':'enable',row)}>{row.enabled?'Unpublish':'Enable'} {row.provider} DNS</button>}
   {row.phase==='ready' && !row.enabled && row.desired_action==='absent' && !row.record_id && <button disabled={busy} onClick={()=>setRelease(row.id)}>Review {row.provider} name release</button>}
   {release===row.id && <div><p>Release {row.name} for reuse? DNS deletion must already be confirmed.</p><button disabled={busy} onClick={()=>void change(row.binding_id,'release',row)}>Confirm name release</button><button disabled={busy} onClick={()=>setRelease(null)}>Cancel</button></div>}
  </section>)}
  {!!available.length && host.provider==='aws' && host.enrolled && <details><summary>Add DNS destination</summary><form onSubmit={e=>{e.preventDefault();void change(target,'reserve')}}>
   <label>Destination <select required value={target} onChange={e=>setTarget(e.target.value)}><option value="">Select destination</option>{available.map(d=><option key={d.id} value={d.id}>{d.provider}: {d.prefix}</option>)}</select></label>
   <label>DNS label <input required pattern="[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?" maxLength={63} value={label} onChange={e=>setLabel(e.target.value)}/></label>
   <button disabled={busy||!target}>Reserve and publish</button>
  </form></details>}
  {error && <p role="alert">{error}</p>}
 </section>
}
