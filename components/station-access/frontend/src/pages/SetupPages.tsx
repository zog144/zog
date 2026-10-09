import {DnsDestinationSetup} from './DnsDestinationSetup'
import {DeploymentJobs} from './DeploymentJobs'
import {useEffect,useState,FormEvent} from 'react'
import {useAuth} from '../auth/AuthProvider'
import {setupApi,RegistrySetup,ProviderAccount,DeploymentSetup,BeaconDestination} from '../api'

export function RegistriesPage(){
 const {user}=useAuth()
 const [data,setData]=useState<RegistrySetup|null>(null),[error,setError]=useState(''),[saved,setSaved]=useState(''),[busy,setBusy]=useState(false)
 const [selected,setSelected]=useState<ProviderAccount|null>(null),[name,setName]=useState(''),[provider,setProvider]=useState<'cloudflare'|'porkbun'>('cloudflare'),[account,setAccount]=useState(''),[token,setToken]=useState(''),[secret,setSecret]=useState('')
 useEffect(()=>{if(user?.is_superuser)setupApi.registries().then(setData).catch(e=>setError(e.message))},[user?.is_superuser])
 if(!user?.is_superuser)return <p>Administrator access required.</p>
 function edit(row:ProviderAccount|null){setSelected(row);setName(row?.label??'');setProvider(row?.provider??'cloudflare');setAccount(row?.account_id??'');setToken('');setSecret('');setSaved('')}
 async function save(e:FormEvent){e.preventDefault();setBusy(true);setError('');setSaved('');try{
  const secrets=token||secret?(provider==='cloudflare'?{api_token:token}:{api_key:token,secret_key:secret}):undefined
  setData(await setupApi.saveRegistry({id:selected?.id,revision:selected?.revision??0,label:name,provider,account_id:account,secrets}));edit(null);setSaved('Credentials saved. API keys are never returned to the browser.')
 }catch(e){setError((e as Error).message)}finally{setToken('');setSecret('');setBusy(false)}}
 async function check(row:ProviderAccount){setBusy(true);setError('');setSaved('Checking provider read access…');try{
  await setupApi.checkProvider(row.id,row.revision);setData(await setupApi.registries());setSaved('Read-only check finished. Review the account result below.')
 }catch(e){setSaved('');setError((e as Error).message)}finally{setBusy(false)}}
 async function refresh(){setError('');try{setData(await setupApi.registries())}catch(e){setError((e as Error).message)}}
 async function select(id:string){if(!data)return;setBusy(true);setError('');try{setData(await setupApi.saveRegistry({action:'select-dns',credential_id:id,revision:data.dns_selection.revision}));setSaved('DNS credential selection saved for the next reconciliation.')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <section className="setup-page"><h1>Registries</h1><p>Domain registrar and DNS provider accounts. Credentials remain on this station; beaconers do not receive them.</p><button disabled={busy} onClick={refresh}>Refresh checks</button>
 {error&&<p role="alert">{error}</p>}{saved&&<p role="status">{saved}</p>}
 {data&&!data.vault_ready&&<p role="alert">The credential vault needs initialization. An operator must configure HOST_VAULT_CONFIGURATION using create_station_vault before saving credentials.</p>}
 <div className="setup-grid">{data?.registries.map(row=><article className="setup-pane" key={row.id}><h2>{row.label}</h2><p>Provider: {row.provider}</p>{row.account_id&&<p>Account: {row.account_id}</p>}<p>Credentials: saved ••••••••</p><p>{row.supported?'Cloudflare integration available':'Porkbun DNS integration available. Configure destinations below.'}</p><p>{data.dns_selection.credential_id===row.id?'Selected for primary DNS reconciliation':'Not selected for primary DNS reconciliation'}</p><button disabled={busy} onClick={()=>edit(row)}>Edit / replace credentials</button>{row.supported&&<button disabled={busy||data.dns_selection.credential_id===row.id} onClick={()=>select(row.id)}>Use for DNS reconciliation</button>}
 {(row.can_check??row.supported)&&<button disabled={busy} onClick={()=>check(row)}>Check access and list domains</button>}
 {row.access_check&&<div className="provider-check"><p role={row.access_check.status==='failed'?'alert':undefined}>{row.access_check.message}</p>
 {row.access_check.finished_at&&<p>Last check: {new Date(row.access_check.finished_at).toLocaleString()}{!row.access_check.fresh?' · Not a current verification':''}</p>}
 {row.access_check.domains.length>0&&<ul>{row.access_check.domains.map(domain=><li key={domain.id}>{domain.name} — {domain.status}</li>)}</ul>}
 {row.access_check.more_available&&<p>Showing up to 50 domains; more domains may be available.</p>}
 </div>}
 </article>)}</div>
 {data?.dns_selection.credential_id&&<button disabled={busy} onClick={()=>select('')}>Return DNS to configured credential file</button>}
 <DnsDestinationSetup accounts={data?.registries??[]}/><form className="setup-pane" onSubmit={save}><h2>{selected?'Edit provider account':'Add provider account'}</h2><label>Label<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label><label>Provider<select disabled={!!selected} value={provider} onChange={e=>{setProvider(e.target.value as typeof provider);setToken('');setSecret('')}}><option value="cloudflare">Cloudflare</option><option value="porkbun">Porkbun</option></select></label>
 {provider==='cloudflare'&&<label>Cloudflare account ID<input required disabled={!!selected} value={account} onChange={e=>setAccount(e.target.value)} pattern="[0-9a-f]{32}"/></label>}
 <label>{provider==='cloudflare'?'API token':'API key'}<input type="password" autoComplete="new-password" required={!selected||(provider==='porkbun'&&!!secret)} value={token} onChange={e=>setToken(e.target.value)}/></label>
 {provider==='porkbun'&&<label>Secret API key<input type="password" autoComplete="new-password" required={!selected||!!token} value={secret} onChange={e=>setSecret(e.target.value)}/></label>}
 {provider==='porkbun'&&<p>Enter both keys from Porkbun’s API Access page. Enable API access for each domain you want to manage. No domain is purchased when saving or checking these keys.</p>}
 {selected&&<p>Leave credential fields blank to keep the saved keys.</p>}
 <button disabled={busy||!data?.vault_ready}>Save provider account</button>{selected&&<button type="button" onClick={()=>edit(null)}>Cancel editing</button>}</form>
 <p>Saving does not purchase a domain or test provider permissions. The explicit access check performs one read-only domain-list request; it cannot prove DNS-write permission. DNS selection must match the account already bound to the authoritative controller.</p></section>
}

export function DeploymentsPage(){
 const {user}=useAuth()
 const [data,setData]=useState<DeploymentSetup|null>(null),[error,setError]=useState(''),[saved,setSaved]=useState(''),[busy,setBusy]=useState(false)
 const [selected,setSelected]=useState<BeaconDestination|null>(null),[name,setName]=useState(''),[server,setServer]=useState(''),[enabled,setEnabled]=useState(true),[ca,setCa]=useState('')
 useEffect(()=>{if(user?.is_superuser)setupApi.deployments().then(setData).catch(e=>setError(e.message))},[user?.is_superuser])
 if(!user?.is_superuser)return <p>Administrator access required.</p>
 function edit(row:BeaconDestination|null){setSelected(row);setName(row?.label??'');setServer(row?.server??'');setEnabled(row?.enabled??true);setCa(row?.ca_certificate??'');setSaved('')}
 async function save(e:FormEvent){e.preventDefault();setBusy(true);setError('');try{setData(await setupApi.saveDestination({id:selected?.id,revision:selected?.revision??0,label:name,server,enabled,ca_certificate:ca}));edit(null);setSaved('List saved. Review a host deployment below to apply it, or download the file for manual installation.')}catch(e){setError((e as Error).message)}finally{setBusy(false)}}
 return <section className="setup-page"><h1>Deployments</h1><p>Choose the HTTPS host registries that beaconers should contact. This saved list is deployment intent; it does not change running hosts until installed.</p>{error&&<p role="alert">{error}</p>}{saved&&<p role="status">{saved}</p>}
 <div className="setup-grid">{data?.destinations.map(row=><article className="setup-pane" key={row.id}><h2>{row.label}</h2><p>Registry: {row.server}</p><p>{row.enabled?'Enabled':'Disabled'}</p><p>TLS trust: {row.ca_certificate?'Custom CA certificate':'System certificate authorities'}</p><p>Saved revision: {row.revision} · Installation status unknown</p><button disabled={busy} onClick={()=>edit(row)}>Edit destination</button></article>)}</div>
 <form className="setup-pane" onSubmit={save}><h2>{selected?'Edit destination':'Add beacon destination'}</h2><label>Label<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label><label>Registry HTTPS URL<input type="url" required disabled={!!selected} placeholder="https://host-registry.example.org" value={server} onChange={e=>setServer(e.target.value)}/></label><label><input type="checkbox" checked={enabled} onChange={e=>setEnabled(e.target.checked)}/> Enable beaconing to this registry</label><label>Custom CA certificate (optional PEM)<textarea value={ca} maxLength={12000} onChange={e=>setCa(e.target.value)}/></label><p>Leave the certificate blank for a publicly trusted HTTPS certificate such as Let’s Encrypt. Never paste a private key.</p><button disabled={busy}>Save destination</button>{selected&&<button type="button" onClick={()=>edit(null)}>Cancel editing</button>}</form>
 {!!data?.destinations.length&&<a href="/api/setup/deployments/?download=1" download="beacon-destinations.json">Download beacon destination list</a>}
 <DeploymentJobs/>
 <p>Host-discover reads this file using --destinations alongside its existing --configuration. Include the existing primary registry in the list. Additional registries get separate keys, bindings and archive credential directories; each requires independent fingerprint approval. They receive no station login password and cannot control mirror roles.</p><p>Disable destinations rather than deleting their history. Disabling here does not revoke a remote key or immediately invalidate an issued token.</p></section>
}
