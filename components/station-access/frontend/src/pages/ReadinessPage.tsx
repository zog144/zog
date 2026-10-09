import {useEffect,useState} from 'react'
import {Link} from 'react-router-dom'
import {useAuth} from '../auth/AuthProvider'
import {setupApi,SetupReadiness} from '../api'

const labels:Record<string,string>={observed:'Recently observed',configured:'Configured',needs_attention:'Needs attention',not_configured:'Not configured',not_checked:'Not checked',blocked:'Blocked'}
export function ReadinessPage(){
 const {user}=useAuth()
 const [data,setData]=useState<SetupReadiness|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false)
 async function refresh(){setBusy(true);setError('');try{setData(await setupApi.readiness())}catch(e){setData(null);setError((e as Error).message)}finally{setBusy(false)}}
 useEffect(()=>{if(user?.is_superuser)void refresh()},[user?.is_superuser])
 if(!user?.is_superuser)return <p>Administrator access required.</p>
 const areas=Array.from(new Set(data?.checks.map(check=>check.area)??[]))
 return <section className="setup-page"><h1>Setup readiness</h1>
 <p>Review local configuration and recorded observations. This page does not start services or contact providers. Configured settings do not establish that a service is operational.</p>
 <p>Choose the capabilities this station needs: central-registry and optional-service items are not requirements for every local station.</p>
 <button disabled={busy} onClick={refresh}>{busy?'Refreshing…':'Refresh observations'}</button>
 {error&&<p role="alert">{error}</p>}
 {data&&<p>Snapshot: {new Date(data.server_time).toLocaleString()}. Refresh to evaluate observation age again.</p>}
 {areas.map(area=><section key={area}><h2>{area}</h2><div className="setup-grid">{data?.checks.filter(check=>check.area===area).map(check=><article className="setup-pane" key={check.id}>
 <h3>{check.title}</h3><p className={`readiness-state readiness-${check.status}`}>{labels[check.status]}</p><p>{check.detail}</p>
 {check.observed_at&&<p>Evidence timestamp: {new Date(check.observed_at).toLocaleString()}</p>}
 {check.link&&<Link to={check.link}>Open related settings</Link>}
 </article>)}</div></section>)}
 </section>
}
