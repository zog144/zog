import {useEffect,useState} from 'react'
import {api,dnsSetupApi,type ProviderAccount,type DnsDestination,type DnsSetupReview,type DnsInspection} from '../api'
export function DnsDestinationSetup({accounts}:{accounts:ProviderAccount[]}){
 const [destinations,setDestinations]=useState<DnsDestination[]>([]),[account,setAccount]=useState(''),[zones,setZones]=useState<{id:string;name:string}[]>([]),[cursor,setCursor]=useState<string|null>(null),[zone,setZone]=useState(''),[label,setLabel]=useState('hosts')
 const [review,setReview]=useState<DnsSetupReview|null>(null),[inspection,setInspection]=useState<DnsInspection|null>(null),[inspected,setInspected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(''),[message,setMessage]=useState('')
 const selected=accounts.find(a=>a.id===account)
 async function refresh(){setDestinations((await api.dnsDestinations()).destinations)}
 useEffect(()=>{void refresh().catch(e=>setError(e.message))},[])
 async function run(action:()=>Promise<void>){setBusy(true);setError('');setMessage('');try{await action()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 async function load(more=false){if(!selected)return;setReview(null);const result=await dnsSetupApi.zones(selected.id,selected.revision,more?cursor??undefined:undefined);setZones(old=>more?[...old,...result.zones]:result.zones);setCursor(result.cursor);if(!more)setZone('')}
 async function inspect(id:string,name:string){setInspected(name);setInspection(null);setInspection(await dnsSetupApi.inspect(id))}
 return <section className="setup-pane" aria-label="DNS destinations"><h2>DNS destinations</h2>
 <p>Choose where approved hosts may publish names. Each host is assigned separately from the Hosts page. Setup checks read access and DNS authority; write permission is verified when an actual record is published.</p>
 {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 <button disabled={busy} onClick={()=>void run(()=>inspect('primary','Primary DNS destination'))}>Check primary DNS destination</button>
 {destinations.map(d=><article key={d.id}><h3>{d.prefix}</h3><p>{d.provider}</p><button disabled={busy} onClick={()=>void run(()=>inspect(d.id,d.prefix))}>Check {d.prefix}</button></article>)}
 {inspection&&<article aria-label="DNS diagnostic result"><h3>{inspected}</h3><p>{inspection.ready?'Checks passed':'Attention required'} · DNS authority: {inspection.authority} · Provider reads: {inspection.provider_reads}</p><p>Write permission: {inspection.write_permission}. This check makes no DNS changes.</p>
 {inspection.operations.map((o,i)=><p role="alert" key={i}>Pending recovery: {o.state} · Host {o.host_id}{o.code&&` · ${o.code}`}. Inspect the retained operation before retrying.</p>)}
 {inspection.hosts.map(h=><p key={h.host_id}>Host {h.label||h.host_id} · {h.code}: {h.message}</p>)}</article>}
 <fieldset disabled={busy}><legend>Add a DNS destination</legend>
 <label>Saved provider account<select value={account} onChange={e=>{setAccount(e.target.value);setZones([]);setCursor(null);setZone('');setReview(null)}}><option value="">Select an account</option>{accounts.map(a=><option key={a.id} value={a.id}>{a.label} ({a.provider})</option>)}</select></label>
 <button disabled={!selected} onClick={()=>void run(()=>load())}>Load domains</button>
 <label>Domain<select value={zone} onChange={e=>{setZone(e.target.value);setReview(null)}}><option value="">Select a domain</option>{zones.map(z=><option key={z.id} value={z.id}>{z.name}</option>)}</select></label>
 {cursor&&<button onClick={()=>void run(()=>load(true))}>Load more domains</button>}
 <label>Host-name prefix<input value={label} maxLength={63} pattern="[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?" onChange={e=>{setLabel(e.target.value);setReview(null)}}/></label>
 <p>For example, “hosts” gives each assigned host a name under hosts.example.org. Existing records within the selected namespace require a separate ownership review.</p>
 <button disabled={!selected||!zone||!label} onClick={()=>void run(async()=>{setReview(null);setReview(await dnsSetupApi.review(selected!.id,selected!.revision,zone,label))})}>Review DNS destination</button>
 </fieldset>
 {review&&<article aria-label="DNS destination review"><h3>Review destination</h3><p>{review.provider} · {review.domain}</p><p>Host names: &lt;label&gt;.{review.prefix}</p><p>Nameservers: {review.nameservers.join(', ')}</p><p>Review expires {new Date(review.expires_at*1000).toLocaleString()}. Confirmation saves an empty destination; it does not purchase a domain, change nameservers or publish a record.</p>
 <button disabled={busy} onClick={()=>void run(async()=>{await dnsSetupApi.commit(review.review_id);setReview(null);await refresh();setMessage('DNS destination saved. Assign hosts from the Hosts page.')})}>Confirm DNS destination</button><button disabled={busy} onClick={()=>setReview(null)}>Cancel review</button></article>}
 </section>
}
