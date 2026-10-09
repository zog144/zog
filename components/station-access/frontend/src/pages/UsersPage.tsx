import {useEffect,useRef,useState,FormEvent} from 'react'
import {usersApi,ManagedUser,UserFields,UserList} from '../api'
import {useAuth} from '../auth/AuthProvider'
const blank:UserFields={username:'',email:'',first_name:'',last_name:'',is_active:true,is_superuser:false,password:''}
export function UsersPage(){
 const {user,refresh}=useAuth()
 const [data,setData]=useState<UserList|null>(null),[query,setQuery]=useState(''),[page,setPage]=useState(1)
 const [selected,setSelected]=useState<ManagedUser|null>(null),[fields,setFields]=useState<UserFields>({...blank}),[deleting,setDeleting]=useState<ManagedUser|null>(null),[confirmation,setConfirmation]=useState('')
 const [error,setError]=useState(''),[message,setMessage]=useState(''),[busy,setBusy]=useState(false),[reload,setReload]=useState(0)
 const pending=useRef(false)
 useEffect(()=>{let active=true;if(user?.is_superuser)usersApi.list(query,page).then(value=>{if(active)setData(value)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[user?.is_superuser,query,page,reload])
 if(!user?.is_superuser)return <p>Administrator access required.</p>
 function edit(row:ManagedUser|null){setSelected(row);setFields(row?{username:row.username,email:row.email,first_name:row.first_name,last_name:row.last_name,is_active:row.is_active,is_superuser:row.is_superuser,password:''}:{...blank});setDeleting(null);setConfirmation('');setError('');setMessage('')}
 function text(key:'username'|'email'|'first_name'|'last_name'|'password',value:string){setFields(old=>({...old,[key]:value}))}
 async function save(e:FormEvent){e.preventDefault();if(pending.current)return;pending.current=true;setBusy(true);setError('');setMessage('')
  try{if(selected)await usersApi.update(selected.id,{...fields,revision:selected.revision});else await usersApi.create(fields)
   if(selected?.id===user?.id)await refresh();edit(null);setReload(n=>n+1);setMessage('User saved.')
  }catch(e){setError((e as Error).message)}finally{setFields(old=>({...old,password:''}));pending.current=false;setBusy(false)}
 }
 async function remove(e:FormEvent){e.preventDefault();if(!deleting||pending.current)return;pending.current=true;setBusy(true);setError('');setMessage('')
  try{await usersApi.remove(deleting.id,deleting.revision,confirmation);edit(null);setReload(n=>n+1);setMessage('User deleted.')}
  catch(e){setError((e as Error).message)}finally{pending.current=false;setBusy(false)}
 }
 return <section className="setup-page"><h1>Users</h1><p>Manage station-access accounts. Administrator accounts can manage all users, hosts and workspaces.</p>
 {error&&<p role="alert">{error}</p>}{message&&<p role="status">{message}</p>}
 <label>Search users<input type="search" value={query} onChange={e=>{setQuery(e.target.value);setPage(1)}}/></label>
 <button disabled={busy} onClick={()=>edit(null)}>Create new user</button>{' '}<button disabled={busy} onClick={()=>{edit(null);setReload(n=>n+1)}}>Refresh users</button>
 <div className="setup-grid">{data?.users.map(row=><article className="setup-pane" key={row.id}><h2>{row.username}{row.id===user.id?' (you)':''}</h2><p>{[row.first_name,row.last_name].filter(Boolean).join(' ')}</p>{row.email&&<p>{row.email}</p>}<p>{row.is_superuser?'Administrator':'User'} · {row.is_active?'Active':'Inactive'}</p><p>{row.workspace_count} workspaces · {row.application_count} applications</p><p>Last login: {row.last_login?new Date(row.last_login).toLocaleString():'Never'}</p><button disabled={busy} onClick={()=>edit(row)}>Edit {row.username}</button>{' '}<button disabled={busy||row.id===user.id||row.workspace_count>0||row.application_count>0} onClick={()=>{edit(null);setDeleting(row)}}>Delete {row.username}</button>{(row.workspace_count>0||row.application_count>0)&&<p>Resolve workspace/application ownership before deletion, or make this account inactive.</p>}</article>)}</div>
 {data&&<p>{data.total} users · Page {data.page} of {data.pages}{' '}<button disabled={busy||data.page<=1} onClick={()=>setPage(data.page-1)}>Previous</button>{' '}<button disabled={busy||data.page>=data.pages} onClick={()=>setPage(data.page+1)}>Next</button></p>}
 {deleting?<form className="setup-pane" onSubmit={remove}><h2>Delete user {deleting.username}</h2><p>This permanently removes the account. Existing audit history is retained.</p><label>Type the username to confirm<input required value={confirmation} onChange={e=>setConfirmation(e.target.value)}/></label><button disabled={busy||confirmation!==deleting.username}>Confirm deletion</button>{' '}<button type="button" disabled={busy} onClick={()=>edit(null)}>Cancel</button></form>:
 <form className="setup-pane" onSubmit={save}><h2>{selected?`Edit user ${selected.username}`:'Create user'}</h2><fieldset disabled={busy}><label>Username<input required maxLength={150} autoComplete="off" value={fields.username} onChange={e=>text('username',e.target.value)}/></label><label>Email<input type="email" maxLength={254} value={fields.email} onChange={e=>text('email',e.target.value)}/></label><label>First name<input maxLength={150} value={fields.first_name} onChange={e=>text('first_name',e.target.value)}/></label><label>Last name<input maxLength={150} value={fields.last_name} onChange={e=>text('last_name',e.target.value)}/></label><label>{selected?'New password (optional)':'Password'}<input type="password" required={!selected} minLength={12} maxLength={1024} autoComplete="new-password" value={fields.password} onChange={e=>text('password',e.target.value)}/></label><p>Use at least 12 characters and avoid common passwords or account details. {selected?'Leave blank to keep the current password.':''}</p><label><input type="checkbox" disabled={selected?.id===user.id} checked={fields.is_active} onChange={e=>setFields(old=>({...old,is_active:e.target.checked}))}/> Active account</label><label><input type="checkbox" disabled={selected?.id===user.id} checked={fields.is_superuser} onChange={e=>setFields(old=>({...old,is_superuser:e.target.checked}))}/> Administrator access</label><button>{selected?'Save user':'Create user'}</button>{selected&&<button type="button" onClick={()=>edit(null)}>Cancel editing</button>}</fieldset></form>}
 <p>Disabling an account or resetting its password revokes existing login sessions and unused VNC grants. Running applications and already connected desktops are not stopped.</p></section>
}
