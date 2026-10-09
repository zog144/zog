// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, test, vi } from 'vitest'
import { archivesApi, ArchiveMirror, ArchiveItem } from '../api'
import { ArchivesPage, megabytes } from './ArchivesPage'
const session=vi.hoisted(()=>({user:{is_superuser:true}}))
vi.mock('../auth/AuthProvider',()=>({useAuth:()=>session}))
afterEach(()=>{cleanup();vi.restoreAllMocks();session.user.is_superuser=true})
const mirror:ArchiveMirror={preparation:{state:'unknown',attempt_id:null,fresh:false},host_id:'mirror-a',name:'Mirror A',selected:true,role_revision:1,state:'serving',reason:'',observation_state:'observed',observed_at:'2026-09-27T18:00:00Z',last_attempt_at:'2026-09-27T18:00:00Z',observation_revision:1,role_observed_at:null,snapshot:'snapshot',archive_count:2,summary:{collections:['sources','root-filesystems'],logical_bytes:2000000,unique_content_bytes:1000000,allocated_object_bytes:4096,accounting_complete:true,filesystems:[{id:'1',stores:['objects'],total_bytes:10000000,used_bytes:5000000,available_bytes:null,allocated_object_bytes:4096}]}}
const source:ArchiveItem={collection:'sources',digest:'a'.repeat(64),kind:'source',name:'Example',version:'a'.repeat(40),size_bytes:1000000,availability:'present',filesystem_id:'1',provenance:'source-export',approval:'unknown'}
const root:ArchiveItem={...source,collection:'root-filesystems',kind:'root-filesystem',name:null,version:null,approval:'unapproved'}
function mocks(row=mirror,items=[source,root]) {
 vi.spyOn(archivesApi,'mirrors').mockResolvedValue({version:1,mirrors:[row],next_cursor:null})
 return vi.spyOn(archivesApi,'items').mockResolvedValue({items,next_cursor:null,mirror:row})
}
test('decimal MB preserves unknown and small nonzero measurements',()=>{
 expect(megabytes(1000000)).toBe('1 MB');expect(megabytes(null)).toBe('Unknown');expect(megabytes(0)).toBe('0 MB');expect(megabytes(1)).toBe('0.000001 MB')
})
test('source/rootfs panes, digest, provenance and storage distinctions',async()=>{
 mocks();render(<ArchivesPage/>);await screen.findByText('Example')
 expect(screen.getByText('Root filesystem')).toBeTruthy();expect(screen.getByText('unapproved')).toBeTruthy()
 expect(screen.getByText('Logical archive sizes')).toBeTruthy();expect(screen.getByText('Distinct content size')).toBeTruthy()
 expect(screen.getByText('Filesystem used')).toBeTruthy();expect(screen.getAllByText('Unknown').length).toBeGreaterThan(0)
 expect(screen.queryByRole('link',{name:/download/i})).toBeNull();expect(screen.queryByRole('button',{name:/delete|approve|import/i})).toBeNull()
})
test('collection and bounded next/previous pages reset correctly',async()=>{
 const get=mocks();get.mockResolvedValueOnce({items:[source],next_cursor:24,mirror})
 render(<ArchivesPage/>);await screen.findByText('Example')
 fireEvent.click(screen.getByRole('button',{name:'Next archives'}))
 await waitFor(()=>expect(get).toHaveBeenLastCalledWith('mirror-a','snapshot','',24))
 await waitFor(()=>expect((screen.getByRole('button',{name:'Previous archives'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'Previous archives'}))
 await waitFor(()=>expect(get).toHaveBeenLastCalledWith('mirror-a','snapshot','',null))
 fireEvent.change(screen.getByLabelText('Collection'),{target:{value:'root-filesystems'}})
 await waitFor(()=>expect(get).toHaveBeenLastCalledWith('mirror-a','snapshot','root-filesystems',null))
})
test('stale and unavailable mirrors never claim an empty current store',async()=>{
 mocks({...mirror,observation_state:'stale',state:'stale'},[]);render(<ArchivesPage/>)
 await screen.findByText('Last known catalog retained. Current archive availability is unknown.')
 expect(await screen.findByText(/current contents are unknown/)).toBeTruthy()
 expect(screen.queryByText('This complete catalog observation is empty.')).toBeNull()
})
test('unobserved mirror shows unknown and performs no item query',async()=>{
 const get=mocks({...mirror,snapshot:null,summary:null,archive_count:null,observation_state:'unavailable',state:'assigned'})
 render(<ArchivesPage/>);await screen.findByText(/not known to be empty/);expect(get).not.toHaveBeenCalled()
})
test('fresh complete empty catalog is identified',async()=>{
 mocks({...mirror,archive_count:0},[]);render(<ArchivesPage/>);await screen.findByText('This complete catalog observation is empty.')
})
test('ordinary users make no metadata requests',()=>{
 session.user.is_superuser=false;const get=vi.spyOn(archivesApi,'mirrors');render(<ArchivesPage/>)
 expect(screen.getByText('Administrator access required.')).toBeTruthy();expect(get).not.toHaveBeenCalled()
})
test('network errors use generic text, never exception credentials',async()=>{
 vi.spyOn(archivesApi,'mirrors').mockRejectedValue(new Error('https://user:private-secret@example.test'))
 render(<ArchivesPage/>);await screen.findByRole('alert');expect(document.body.textContent).not.toContain('private-secret')
 expect(screen.queryByText(/complete catalog observation is empty/)).toBeNull()
})

test('license details preserve hostile text, package terms, pagination and same-origin downloads',async()=>{
 const {noticesApi}=await import('../api')
 const licenses={state:'available' as const,review:'unresolved',bundle_digest:'b'.repeat(64),notice_digest:'c'.repeat(64),notice_bytes:200,package_count:2,issue_count:1,coverage:'unresolved',source_material:'unknown'}
 const record={package:'upstream-example',version:'1.0',revision:null,stage:null,source_digest:'a'.repeat(64),origin:'https://example.org/source',expression:'MIT',review:'declared',scope:'package',exceptions:[{scope:'font',expression:null,review:'unresolved',notes:'Needs review'}],issues:['Inherited seed files unresolved'],texts:['d'.repeat(64)],receipt_digest:null}
 const metadata=vi.spyOn(noticesApi,'metadata').mockResolvedValue({schema:1,summary:licenses,generation:'generation-1',source_identity:{kind:'root-filesystem',digest:'a'.repeat(64),revision:null},records:[record],next_offset:1})
 vi.spyOn(noticesApi,'text').mockResolvedValue('<script>window.evil=true</script>\nExact notice terms')
 mocks(mirror,[{...root,licenses}]);render(<ArchivesPage/>);
 fireEvent.click(await screen.findByRole('button',{name:'Source & license'}))
 expect(await screen.findByText('upstream-example 1.0')).toBeTruthy();expect(screen.getByText(/font.*unresolved/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Next license records'}));await waitFor(()=>expect(metadata).toHaveBeenLastCalledWith(expect.any(Object),1))
 fireEvent.click(screen.getByRole('button',{name:'Read full notice document'}))
 expect(await screen.findByText(/<script>window.evil=true<\/script>/)).toBeTruthy();expect(document.querySelector('.archive-notice-text script')).toBeNull()
 expect(screen.getByRole('link',{name:'Download notices (.txt)'}).getAttribute('href')).toMatch(/^\/api\/archives\/notices\/\?/)
 expect(screen.getByText(/does not mean release approval/)).toBeTruthy()
})
