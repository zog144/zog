// @vitest-environment jsdom
import {fireEvent,render,screen,waitFor,within,cleanup} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {api,IdentityAdministration} from '../api'
import {IdentitiesPage} from './IdentitiesPage'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
const fingerprint='a'.repeat(64)
const host={id:'existing',label:'Compiler',provider:'aws',account_id:'123456789012',region:'us-east-1',instance_id:'i-0123456789abcdef0',archived:false}
const data:IdentityAdministration={pending:[{fingerprint,public_key:'public',status:'pending',claimed_host_id:'existing',claims:{hostname:'untrusted-name'},expires_at:'tomorrow',match:{status:'existing',host,cloud:{account_id:host.account_id,region:host.region,instance_id:host.instance_id},reason:'Exact AWS identity; migration UUID agrees.',candidates:[host]}}],identities:[],policies:[],hosts:[{...host,legacy_until:null}],audit:[]}
const approveName='Approve this fingerprint for this host'
test('unique match is automatic but independent fingerprint confirmation is mandatory',async()=>{
 vi.spyOn(api,'identities').mockResolvedValue(data)
 const decide=vi.spyOn(api,'identityDecision').mockResolvedValue({saved:true})
 render(<IdentitiesPage/>);await screen.findByText('untrusted-name')
 const approve=screen.getByRole('button',{name:approveName}) as HTMLButtonElement
 expect(approve.disabled).toBe(true);expect(screen.getByText(/Automatically selected existing host/)).toBeTruthy()
 expect(screen.getByText(fingerprint)).toBeTruthy();expect(screen.getByText(/Reported AWS identity: 123456789012/)).toBeTruthy()
 fireEvent.change(screen.getByLabelText('Fingerprint from trusted channel'),{target:{value:fingerprint}})
 expect(approve.disabled).toBe(false);fireEvent.click(approve)
 await waitFor(()=>expect(decide).toHaveBeenCalledWith({action:'approve',fingerprint,confirmed_fingerprint:fingerprint,host_id:'existing'}))
})
test('full fingerprint copy',async()=>{
 const writeText=vi.fn().mockResolvedValue(undefined);Object.defineProperty(navigator,'clipboard',{value:{writeText},configurable:true})
 vi.spyOn(api,'identities').mockResolvedValue(data);render(<IdentitiesPage/>);await screen.findByText('untrusted-name')
 fireEvent.click(screen.getByRole('button',{name:'Copy fingerprint'}));expect(writeText).toHaveBeenCalledWith(fingerprint)
})
test('conflicts cannot be approved or switched to new-record creation',async()=>{
 vi.spyOn(api,'identities').mockResolvedValue({...data,pending:[{...data.pending[0],match:{...data.pending[0].match,status:'conflict',reason:'Registry UUID conflicts with AWS identity'}}]})
 const decide=vi.spyOn(api,'identityDecision');render(<IdentitiesPage/>);await screen.findByText('untrusted-name')
 fireEvent.change(screen.getByLabelText('Fingerprint from trusted channel'),{target:{value:fingerprint}})
 expect(screen.getByRole('alert').textContent).toContain('conflicts');expect((screen.getByRole('button',{name:approveName}) as HTMLButtonElement).disabled).toBe(true)
 expect(decide).not.toHaveBeenCalled();expect(screen.queryByText(/Approval will create/)).toBeNull()
})
test('new AWS enrollment clearly describes creation and isolates confirmation per request',async()=>{
 const fresh={...data.pending[0],fingerprint:'b'.repeat(64),claimed_host_id:'',claims:{hostname:'New machine'},match:{...data.pending[0].match,status:'new' as const,host:null,candidates:[],reason:'No existing AWS match'}}
 vi.spyOn(api,'identities').mockResolvedValue({...data,pending:[data.pending[0],fresh]})
 const decide=vi.spyOn(api,'identityDecision').mockResolvedValue({saved:true})
 render(<IdentitiesPage/>);await screen.findByText('New machine')
 const existing=within(screen.getByText('untrusted-name').closest('article')!)
 const newborn=within(screen.getByText('New machine').closest('article')!)
 expect(newborn.getByText('Approval will create a new AWS record.')).toBeTruthy()
 fireEvent.change(newborn.getByLabelText('Fingerprint from trusted channel'),{target:{value:fresh.fingerprint}})
 expect((existing.getByRole('button',{name:approveName}) as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(newborn.getByRole('button',{name:approveName}))
 await waitFor(()=>expect(decide).toHaveBeenCalledWith({action:'approve',fingerprint:fresh.fingerprint,confirmed_fingerprint:fresh.fingerprint,host_id:''}))
})
test('changed match resets trusted-channel confirmation',async()=>{
 const read=vi.spyOn(api,'identities').mockResolvedValue(data)
 render(<IdentitiesPage/>);await screen.findByText('untrusted-name')
 fireEvent.change(screen.getByLabelText('Fingerprint from trusted channel'),{target:{value:fingerprint}})
 read.mockResolvedValue({...data,pending:[{...data.pending[0],match:{...data.pending[0].match,reason:'Updated proposed record'}}]})
 fireEvent.click(screen.getByRole('button',{name:'Refresh'}));await screen.findByText('Updated proposed record')
 expect((screen.getByRole('button',{name:approveName}) as HTMLButtonElement).disabled).toBe(true)
})
test('archive policy remains separate and defaults to no grant',async()=>{
 vi.spyOn(api,'identities').mockResolvedValue(data);const decide=vi.spyOn(api,'identityDecision').mockResolvedValue({saved:true})
 render(<IdentitiesPage/>);await screen.findByText('untrusted-name')
 fireEvent.change(screen.getByLabelText('Host'),{target:{value:'existing'}});fireEvent.click(screen.getByRole('button',{name:'Save archive permissions'}))
 await waitFor(()=>expect(decide).toHaveBeenCalledWith({action:'policy',host_id:'existing',operations:[],collections:[]}))
})
