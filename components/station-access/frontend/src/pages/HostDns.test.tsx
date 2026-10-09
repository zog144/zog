// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {HostDns} from './HostDns'
import {api,type RegistryHost,type HostDnsAssignment} from '../api'
vi.mock('../api',()=>({api:{hostDns:vi.fn(),reviewHostDns:vi.fn(),commitHostDns:vi.fn()}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const assignment: HostDnsAssignment={name:'compiler.hosts.example.uk',enabled:true,revision:2,desired_action:'present',desired_address:'8.8.8.8',applied_revision:2,status:'synchronized',record_id:'record',observed_address:'8.8.8.8',last_attempt:null,last_success:null,last_change:null,next_attempt:null,error_code:'',error:'',last_action:'created'}
const host={id:'one',label:'New display label',provider:'aws',enrolled:true,dns:assignment} as RegistryHost
test('reserved name stays independent of label and unpublish sends only intent',async()=>{
 const refresh=vi.fn();vi.mocked(api.hostDns).mockResolvedValue({dns:{...assignment,enabled:false,status:'pending'}})
 render(<HostDns host={host} suffix="hosts.example.uk" refresh={refresh}/>)
 expect(screen.getByText('compiler.hosts.example.uk')).toBeTruthy()
 expect(screen.getByText('Synchronized')).toBeTruthy()
 fireEvent.click(screen.getByText('Unpublish DNS'))
 await waitFor(()=>expect(api.hostDns).toHaveBeenCalledWith('one',false,undefined))
 expect(refresh).toHaveBeenCalledOnce()
})
test('displays provider conflict and failed configuration request',async()=>{
 vi.mocked(api.hostDns).mockRejectedValue(new Error('DNS controller busy'))
 render(<HostDns host={{...host,dns:{...assignment,status:'conflict',error:'Existing record is not owned by this assignment'}}} suffix="hosts.example.uk" refresh={()=>{}}/>)
 expect(screen.getByText('Conflict')).toBeTruthy()
 expect(screen.getByText('Existing record is not owned by this assignment')).toBeTruthy()
 fireEvent.click(screen.getByText('Unpublish DNS'))
 expect((await screen.findByRole('alert')).textContent).toContain('DNS controller busy')
})
test('shared reservation requires review and confirmation',async()=>{
 const reviewed={review_id:'review-one',action:'reserve' as const,name:'new.hosts.example.uk',resource_id:'one'}
 vi.mocked(api.reviewHostDns).mockResolvedValue(reviewed);vi.mocked(api.commitHostDns).mockResolvedValue(reviewed)
 const refresh=vi.fn()
 render(<HostDns host={{...host,dns:null}} writer="shared" suffix="hosts.example.uk" refresh={refresh}/>)
 fireEvent.change(screen.getByLabelText('DNS label'),{target:{value:'new'}})
 fireEvent.click(screen.getByText('Review DNS reservation'))
 await screen.findByText('Confirm DNS change')
 expect(api.commitHostDns).not.toHaveBeenCalled();expect(api.hostDns).not.toHaveBeenCalled()
 fireEvent.click(screen.getByText('Confirm DNS change'))
 await waitFor(()=>expect(api.commitHostDns).toHaveBeenCalledWith('one','review-one'))
 expect(refresh).toHaveBeenCalledOnce()
})
test('failed release keeps same review for resumption',async()=>{
 const reviewed={review_id:'release-one',action:'release' as const,name:assignment.name,resource_id:'one'}
 vi.mocked(api.reviewHostDns).mockResolvedValue(reviewed);vi.mocked(api.commitHostDns).mockRejectedValueOnce(new Error('Interrupted')).mockResolvedValueOnce(reviewed)
 render(<HostDns host={{...host,dns:{...assignment,enabled:false,desired_action:'absent',record_id:''}}} writer="shared" suffix="hosts.example.uk" refresh={()=>{}}/>)
 fireEvent.click(screen.getByText('Review name release'));fireEvent.click(await screen.findByText('Confirm DNS change'))
 await screen.findByRole('alert');expect(screen.queryByText('Dismiss review')).toBeNull()
 fireEvent.click(screen.getByText('Resume DNS change'))
 await waitFor(()=>expect(api.commitHostDns).toHaveBeenCalledTimes(2))
 expect(vi.mocked(api.commitHostDns).mock.calls).toEqual([['one','release-one'],['one','release-one']])
})
