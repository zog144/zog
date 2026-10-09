// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {MemoryRouter,Routes,Route} from 'react-router-dom'
import {afterEach,expect,test,vi} from 'vitest'
import {api,RemovalPreview} from '../api'
import {HostDetailPage} from './HostDetailPage'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
const preview:RemovalPreview={host:{id:'host-uuid',label:'Duplicate',provider:'generic',account_id:'',region:'',instance_id:'',archived:false},archived_at:null,archived_by:'',revision:'snapshot',can_archive:true,blockers:[],explanation:'Archival does not stop or terminate EC2.',identities:[],station_credential:null,legacy_credential_active:false,archive_policy:null,possible_token_expiry:null,mirror_role:null,dns:[],pending_fingerprints:[],host_generation:null}
function show(){render(<MemoryRouter initialEntries={['/hosts/host-uuid']}><Routes><Route path="/hosts/:hostId" element={<HostDetailPage/>}/></Routes></MemoryRouter>)}
test('removal previews dependencies and requires exact UUID confirmation',async()=>{
 vi.spyOn(api,'hostRemovalPreview').mockResolvedValue(preview);const remove=vi.spyOn(api,'hostRemoval').mockResolvedValue({saved:true});show()
 await screen.findByText('Duplicate');expect(screen.getByText(/does not stop or terminate EC2/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Remove record (archive)'}));const button=screen.getByRole('button',{name:'Confirm archival'}) as HTMLButtonElement
 expect(button.disabled).toBe(true);fireEvent.change(screen.getByLabelText('Confirm registry UUID'),{target:{value:'host-uuid'}});fireEvent.click(button)
 await waitFor(()=>expect(remove).toHaveBeenCalledWith('host-uuid','archive','snapshot','host-uuid'))
})
test('dependencies block removal and explain resolution without exposing credentials',async()=>{
 vi.spyOn(api,'hostRemovalPreview').mockResolvedValue({...preview,can_archive:false,blockers:['Explicitly revoke the approved identity first'],station_credential:{revision:3,source_fingerprint:'key',received_at:'today'}})
 show();await screen.findByText('Duplicate');expect(screen.getByRole('alert').textContent).toContain('revoke')
 expect((screen.getByRole('button',{name:'Remove record (archive)'}) as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByText('Station login credential: stored, revision 3')).toBeTruthy()
})
test('changed dependencies report conflict and reset confirmation',async()=>{
 vi.spyOn(api,'hostRemovalPreview').mockResolvedValue(preview);vi.spyOn(api,'hostRemoval').mockRejectedValue(new Error('Host or dependencies changed. Reload preview.'));show()
 await screen.findByText('Duplicate');fireEvent.click(screen.getByRole('button',{name:'Remove record (archive)'}));fireEvent.change(screen.getByLabelText('Confirm registry UUID'),{target:{value:'host-uuid'}});fireEvent.click(screen.getByRole('button',{name:'Confirm archival'}))
 await waitFor(()=>expect(screen.getByRole('alert').textContent).toContain('dependencies changed'))
 expect((screen.getByRole('button',{name:'Confirm archival'}) as HTMLButtonElement).disabled).toBe(true)
})
test('archived record exposes explicit restoration without approval',async()=>{
 vi.spyOn(api,'hostRemovalPreview').mockResolvedValue({...preview,archived_at:'today',archived_by:'admin',can_archive:false});const remove=vi.spyOn(api,'hostRemoval').mockResolvedValue({saved:true});show()
 await screen.findByText('Duplicate');fireEvent.click(screen.getByRole('button',{name:'Review restoration'}));fireEvent.change(screen.getByLabelText('Confirm registry UUID'),{target:{value:'host-uuid'}});fireEvent.click(screen.getByRole('button',{name:'Confirm restoration'}))
 await waitFor(()=>expect(remove).toHaveBeenCalledWith('host-uuid','restore','snapshot','host-uuid'))
})

test('renders signed host slot provenance and exact generation link',async()=>{
 const generation={
  schema:1 as const,source:'verified-host-install-state-v1' as const,received_at:'2026-10-07T12:00:00Z',
  installation:{installation_id:'00000001-0001-4001-8001-000000000001',record_id:'00000005-0005-4005-8005-000000000005',record_schema:1,operation:'fresh'},
  selected_slot:'HOST-A' as const,booted_slot:'HOST-A' as const,
  slots:{
   'HOST-A':{generation:'generation-a',root_partuuid:'00000009-0009-4009-8009-000000000009',resolution:'resolved' as const,digest:'a'.repeat(64),candidate_count:1,archive:{mirror:'11111111-1111-1111-1111-111111111111',snapshot:'22222222-2222-2222-2222-222222222222',collection:'root-filesystems',digest:'a'.repeat(64),observed_at:'2026-10-07T11:00:00Z'}},
   'HOST-B':null
  },
  transitional_boot_bundle:{kind:'foreign' as const,provider:'amazon-linux-2023',record_reference:'00000007-0007-4007-8007-000000000007',record_sha256:'b'.repeat(64)}
 }
 vi.spyOn(api,'hostRemovalPreview').mockResolvedValue({...preview,host_generation:generation});show()
 await screen.findByText('HOST-A · Booted · Selected')
 expect(screen.getByText('generation-a')).toBeTruthy()
 expect(screen.getByText('amazon-linux-2023')).toBeTruthy()
 expect(screen.getByText('Generation identity unknown.')).toBeTruthy()
 const link=screen.getByRole('link',{name:'Generation provenance'})
 expect(link.getAttribute('href')).toContain('/generations/generation-a?')
 expect(link.getAttribute('href')).toContain('snapshot=22222222-2222-2222-2222-222222222222')
 expect(link.getAttribute('href')).toContain('digest='+'a'.repeat(64))
})
test('does not equate selected slot with booted slot when boot is transitional',async()=>{
 const generation={
  schema:1 as const,source:'verified-host-install-state-v1' as const,received_at:'now',
  installation:{installation_id:'00000001-0001-4001-8001-000000000001',record_id:'00000005-0005-4005-8005-000000000005',record_schema:1,operation:'fresh'},
  selected_slot:'HOST-A' as const,booted_slot:null,
  slots:{'HOST-A':{generation:'generation-a',root_partuuid:'00000009-0009-4009-8009-000000000009',resolution:'unresolved' as const,digest:null,candidate_count:0,archive:null},'HOST-B':null},
  transitional_boot_bundle:null
 }
 vi.spyOn(api,'hostRemovalPreview').mockResolvedValue({...preview,host_generation:generation});show()
 await screen.findByText('Not proved — transitional/non-HOST root')
 expect(screen.getByText('HOST-A · Selected')).toBeTruthy()
 expect(screen.queryByText('HOST-A · Booted · Selected')).toBeNull()
})
