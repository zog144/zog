import {useEffect,useRef,useState} from 'react'
import {deploymentApi,DeploymentJob,DeploymentJobsData,DestinationSummary} from '../api'

function Destinations({rows}:{rows:DestinationSummary[]}){
 return rows.length?<ul>{rows.map((row,i)=><li key={row.server+i}><strong>{row.label}</strong> — {row.server} · {row.enabled?'Enabled':'Disabled'} · Revision {row.revision} · {row.custom_ca||row.ca_sha256?'Custom CA':'System trust'}{row.ca_sha256&&<> · CA SHA-256: <code>{row.ca_sha256}</code></>}</li>)}</ul>:<p>No valid installed destination list was observed.</p>
}

export function DeploymentJobs(){
 const [data,setData]=useState<DeploymentJobsData|null>(null),[host,setHost]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 const mounted=useRef(false),generation=useRef(0),pending=useRef(false)
 async function refresh(){
  const current=++generation.current
  try{const next=await deploymentApi.list();if(mounted.current&&current===generation.current){setData(next);setError('')}}
  catch(e){if(mounted.current&&current===generation.current)setError((e as Error).message)}
 }
 useEffect(()=>{mounted.current=true;void refresh();const timer=setInterval(()=>{if(!pending.current)void refresh()},5000);return()=>{mounted.current=false;generation.current++;clearInterval(timer)}},[])
 async function act(action:()=>Promise<{job:DeploymentJob}>){
  if(pending.current)return
  pending.current=true;setBusy(true);setError('');generation.current++
  try{await action();await refresh()}catch(e){if(mounted.current)setError((e as Error).message)}finally{pending.current=false;if(mounted.current)setBusy(false)}
 }
 const active=(id:string)=>data?.jobs.some(job=>job.host_id===id&&['queued','submitting','running','uncertain'].includes(job.state))
 const now=Date.now()
 return <section className="setup-pane deployment-jobs"><h2>Host deployment jobs</h2><p>Inspect an existing AWS host, then review and explicitly apply the saved beacon destinations. Saving the list above never starts a job.</p>
 {error&&<p role="alert">{error}</p>}
 {data&&!data.enabled&&<p role="status">Deployment jobs are not enabled. An operator must install the pinned host-deploy package, configure the worker and enable HOST_DEPLOY_JOBS_ENABLED.</p>}
 <label>Deployment host<select value={host} onChange={e=>setHost(e.target.value)}><option value="">Choose a host</option>{data?.hosts.map(row=><option key={row.id} value={row.id} disabled={!row.eligible}>{row.label||row.id}{!row.eligible?' — not eligible':''}</option>)}</select></label>
 <button disabled={busy||!data?.enabled||!host||active(host)} onClick={()=>void act(()=>deploymentApi.inspect(host,crypto.randomUUID()))}>Inspect host deployment</button>{' '}
 <button disabled={busy} onClick={()=>void refresh()}>Refresh job status</button>
 <p>Hosts need an approved identity, AWS account, instance, region and deployment workspace. Applying requires an active beacon already using the supported destination file.</p>
 {data?.jobs.map(job=>{
  const observation=job.result.observation
  const expired=!!job.expires_at&&Date.parse(job.expires_at)<=now
  const fresh=!!job.finished_at&&now-Date.parse(job.finished_at)<300000
  return <article className="deployment-job" key={job.id} aria-label={`${job.operation==='inspect'?'Inspection':'Destination change'} for ${job.host_label}`}>
   <h3>{job.operation==='inspect'?'Inspect deployment':'Apply beacon destinations'} — {job.host_label||job.host_id}</h3>
   <p><strong>{job.state==='review'?(expired?'Review expired':'Awaiting confirmation'):job.state}</strong>{job.message?` · ${job.message}`:''}</p>
   <p>Target: {job.target.account_id} / {job.target.region} / {job.target.instance_id}</p>
   <p>Created {new Date(job.created_at).toLocaleString()}{job.finished_at?` · Finished ${new Date(job.finished_at).toLocaleString()}`:''}</p>
   {observation&&<><p>Beacon: {observation.beacon_version??'Version unknown'} · {observation.beacon_state}. Station-access: {observation.station_version??'Version unknown'} · {observation.station_state}.</p><p>Primary registry: {observation.primary}</p><Destinations rows={observation.destinations}/><p>{observation.reason}</p>
   {job.state==='succeeded'&&<button disabled={busy||!data.enabled||!fresh||!observation.apply_supported||active(job.host_id)} onClick={()=>void act(()=>deploymentApi.review(job.host_id,job.id))}>Review saved destinations</button>}
   {!fresh&&<p>Inspect again to review a change; inspections are valid for five minutes.</p>}</>}
   {job.state==='review'&&<><h4>Currently installed</h4><Destinations rows={job.result.before??[]}/><h4>Proposed destination list</h4><Destinations rows={job.destinations}/><p>The entire destination list will be replaced. The primary registry ({job.result.primary}) stays enabled. Existing identity keys are retained. The beacon reads the file on its next cycle; no service restart is requested. Additional registries require separate fingerprint approval.</p><p>Review expires {new Date(job.expires_at!).toLocaleString()}. Changed settings or a changed remote file invalidate this review.</p><button disabled={busy||!data.enabled||expired||active(job.host_id)} onClick={()=>void act(()=>deploymentApi.action(job.id,'apply'))}>Confirm and apply destinations</button></>}
   {job.state==='uncertain'&&<><p>Do not start a replacement change. This checks the original job’s installed-file evidence without applying it again.</p><button disabled={busy||!data.enabled} onClick={()=>void act(()=>deploymentApi.action(job.id,'check-outcome'))}>Check original outcome</button></>}
   {job.state==='succeeded'&&job.operation==='apply'&&<p>Verified file SHA-256: <code>{job.result.sha256}</code>. This does not prove that another registry has approved the host or received a heartbeat.</p>}
  </article>
 })}
 {data&&!data.jobs.length&&<p>No deployment jobs yet.</p>}
 <p>Showing the latest 25 jobs plus unresolved jobs. Software installation and upgrades are deferred until after release.</p>
 </section>
}
