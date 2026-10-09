import {FormEvent,useEffect,useState} from 'react'
import {useAuth} from '../auth/AuthProvider'
import {cloudApi,CloudAccount,CloudSetup} from '../api'

export function CloudsPage(){
 const {user}=useAuth()
 const [data,setData]=useState<CloudSetup|null>(null),[error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false)
 const [selected,setSelected]=useState<CloudAccount|null>(null),[label,setLabel]=useState(''),[account,setAccount]=useState(''),[region,setRegion]=useState('us-east-1'),[mode,setMode]=useState<'default'|'keys'>('default'),[enabled,setEnabled]=useState(true)
 const [access,setAccess]=useState(''),[secret,setSecret]=useState(''),[token,setToken]=useState(''),[expiry,setExpiry]=useState('')
 useEffect(()=>{if(user?.is_superuser)cloudApi.list().then(setData).catch(e=>setError(e.message))},[user?.is_superuser])
 if(!user?.is_superuser)return <p>Administrator access required.</p>
 function clearSecrets(){setAccess('');setSecret('');setToken('');setExpiry('')}
 function edit(row:CloudAccount|null){setSelected(row);setLabel(row?.label??'');setAccount(row?.account_id??'');setRegion(row?.region??'us-east-1');setMode(row?.mode??'default');setEnabled(row?.enabled??true);clearSecrets();setMessage('')}
 async function refresh(){setError('');try{setData(await cloudApi.list())}catch(e){setError((e as Error).message)}}
 async function save(event:FormEvent){event.preventDefault();setBusy(true);setError('');setMessage('');try{
  const secrets=mode==='keys'&&(access||secret||token)?{access_key_id:access,secret_access_key:secret,...(token?{session_token:token}:{})}:undefined
  setData(await cloudApi.save({id:selected?.id,revision:selected?.revision??0,label,account_id:account,mode,region,enabled,secrets,...(secrets&&token?{expires_at:expiry}:{})}));edit(null);setMessage('Cloud account saved. Apply configuration through an explicit host-deploy job; existing workers are unchanged.')
 }catch(e){setError((e as Error).message)}finally{clearSecrets();setBusy(false)}}
 async function check(row:CloudAccount){setBusy(true);setError('');setMessage('');try{await cloudApi.check(row.id,row.revision);await refresh()}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <section className="setup-page"><h1>Cloud credentials</h1><p>Save AWS account configuration and check its identity. Applying it to hosts or inventory workers requires a separate explicit host-deploy job.</p>
 {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}<button disabled={busy} onClick={refresh}>Refresh accounts</button>
 <div className="setup-grid">{data?.accounts.map(row=><article className="setup-pane" key={row.id}><h2>{row.label}</h2><p>Provider: AWS</p><p>Expected account: {row.account_id}</p><p>Region: {row.region}</p><p>Credential source: {row.mode==='default'?'Station default credential chain':'Encrypted saved keys ••••••••'}</p><p>{row.enabled?'Enabled for future explicit use':'Disabled for future use'}</p>
 {row.expires_at&&<p>Session expiry: {new Date(row.expires_at).toLocaleString()}{row.expired?' · Expired':''}</p>}
 <p>{row.check.message}</p>{row.check.finished_at&&<p>Last check: {new Date(row.check.finished_at).toLocaleString()}{!row.check.fresh?' · Not a current verification':''}</p>}
 <button disabled={busy} onClick={()=>edit(row)}>Edit account</button><button disabled={busy||!row.enabled||row.expired} onClick={()=>check(row)}>Check AWS identity</button></article>)}</div>
 <form className="setup-pane" onSubmit={save}><h2>{selected?'Edit AWS account':'Add AWS account'}</h2>
 <label>Label<input required maxLength={100} value={label} onChange={e=>setLabel(e.target.value)}/></label>
 <label>Expected AWS account ID<input required pattern="[0-9]{12}" disabled={!!selected} value={account} onChange={e=>setAccount(e.target.value)}/></label>
 <label>AWS region<input required maxLength={40} value={region} onChange={e=>setRegion(e.target.value)}/></label>
 <label>Credential source<select disabled={!!selected} value={mode} onChange={e=>{setMode(e.target.value as typeof mode);clearSecrets()}}><option value="default">Station default credentials / instance role</option><option value="keys">Encrypted saved access keys</option></select></label>
 {mode==='default'?<p>The SDK uses credentials available to the station service, which may come from its environment, profile or instance role. This does not attach a role to a host.</p>:<>
 {!data?.vault_ready&&<p role="alert">Initialize the station credential vault before saving access keys.</p>}
 <label>Access key ID<input type="password" autoComplete="new-password" required={!selected||!!secret||!!token} value={access} onChange={e=>setAccess(e.target.value)}/></label>
 <label>Secret access key<input type="password" autoComplete="new-password" required={!selected||!!access||!!token} value={secret} onChange={e=>setSecret(e.target.value)}/></label>
 <label>Session token (optional)<input type="password" autoComplete="new-password" value={token} onChange={e=>setToken(e.target.value)}/></label>
 {token&&<label>Session expiry (UTC ISO timestamp)<input required placeholder="2026-10-01T12:00:00Z" value={expiry} onChange={e=>setExpiry(e.target.value)}/></label>}
 {selected&&<p>Leave all credential fields blank to keep the saved keys and expiry. Replacement requires the complete key set.</p>}</>}
 <label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/> Enable for future explicit use</label>
 <button disabled={busy||!data||(mode==='keys'&&!data.vault_ready)}>Save AWS account</button>{selected&&<button type="button" disabled={busy} onClick={()=>edit(null)}>Cancel editing</button>}</form>
 <p>Identity checks make a read-only AWS STS request. They do not verify provisioning permissions. Disabling an entry does not revoke keys at AWS or stop existing jobs. Credentials are never returned by this page.</p>
 <div className="setup-grid"><article className="setup-pane"><h2>Microsoft Azure</h2><p>Planned · Credential entry and host-deploy support are not available.</p></article><article className="setup-pane"><h2>Google Cloud</h2><p>Planned · Credential entry and host-deploy support are not available.</p></article></div></section>
}
