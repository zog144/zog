import { useEffect, useRef, useState } from 'react'
import { api, type RegistryHost } from '../api'

export function HostOperations({host,refresh}: {host:RegistryHost;refresh:()=>void}) {
  const login=host.station_login
  const role=host.mirror_role
  const [secret,setSecret]=useState('')
  const [busy,setBusy]=useState(false)
  const [error,setError]=useState('')
  const [endpoint,setEndpoint]=useState(role?.endpoint || (host.dns?.name ? `https://${host.dns.name}` : ''))
  const request=useRef(0)
  function hide(){request.current++;setSecret('');setBusy(false)}
  useEffect(()=>{hide();return ()=>{request.current++}},[host.id,login?.revision,login?.available,login?.source_active])
  useEffect(()=>{setEndpoint(role?.endpoint || (host.dns?.name ? `https://${host.dns.name}` : ''))},[role?.endpoint,host.dns?.name])
  useEffect(()=>{
    if(!secret)return
    const timer=setTimeout(hide,30000)
    return ()=>clearTimeout(timer)
  },[secret])
  useEffect(()=>{
    const hidden=()=>{if(document.hidden)hide()}
    document.addEventListener('visibilitychange',hidden)
    return ()=>document.removeEventListener('visibilitychange',hidden)
  },[])
  async function reveal(){
    const revision=login?.revision;if(revision===undefined)return
    const ticket=++request.current;setBusy(true);setError('')
    try{const value=await api.hostLogin(host.id,revision);if(request.current===ticket && !document.hidden)setSecret(value.password)}
    catch{if(request.current===ticket)setError('Could not reveal credentials. Refresh and retry.')}
    finally{if(request.current===ticket)setBusy(false)}
  }
  async function assign(selected:boolean){
    setBusy(true);setError('')
    try{await api.hostMirror(host.id,selected,endpoint,role?.revision||0);refresh()}
    catch{setError('Role change failed. Approve the host identity, check the HTTPS endpoint, and refresh.')}
    finally{setBusy(false)}
  }
  return <div className="host-operations">
    <section aria-label="Station login"><h3>Station login</h3>
      <p>Username: <code>station-admin</code></p>
      {login?.available ? <><p>Password: <code className="station-secret">{secret || '••••••••'}</code></p>
        <button type="button" disabled={busy} onClick={()=>secret?hide():void reveal()}>{secret?'Hide password':'Reveal password'}</button>
        {secret && <p>Hidden automatically after 30 seconds or when this tab is hidden.</p>}
        {login.source_active===false && <p role="status">Saved credential is from a key that is no longer approved. It may be outdated.</p>}
      </> : <p>No credential reported.</p>}
    </section>
    <section aria-label="Archive mirror role"><h3>Archive mirror</h3>
      <p>Role: {role?.selected?'Selected':'Not selected'}</p>
      <p>Status: {role?.state || 'unassigned'}{role?.ready?' · host serving check passed':''}</p>
      {role?.reason && <p>Reason: {role.reason}</p>}
      <label>Mirror HTTPS address<input type="url" value={endpoint} placeholder="https://mirror.example.org" onChange={e=>setEndpoint(e.target.value)} /></label>
      <div className="host-actions"><button disabled={busy || !endpoint} onClick={()=>void assign(true)}>{role?.selected?'Save mirror address':'Assign mirror role'}</button>
        {role?.selected && <button disabled={busy} onClick={()=>void assign(false)}>Remove role; retain archives</button>}</div>
      <small>Requires an approved identity and an installed mirror application. Archive download permissions are assigned separately.</small>
    </section>
    {error && <p role="alert">{error}</p>}
  </div>
}
