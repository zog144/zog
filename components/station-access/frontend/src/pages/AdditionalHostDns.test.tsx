// @vitest-environment jsdom
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {AdditionalHostDns} from './AdditionalHostDns'
import {api,type RegistryHost,type AdditionalDnsAssignment} from '../api'
vi.mock('../api',()=>({api:{dnsDestinations:vi.fn(),additionalDns:vi.fn()}}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const row={id:'assignment',binding_id:'pb',phase:'ready',provider:'porkbun',prefix:'hosts.example.org',name:'compiler.hosts.example.org',enabled:true,revision:3,status:'synchronized',observed_address:'8.8.8.8',ttl:600} as AdditionalDnsAssignment
const host={id:'host',provider:'aws',enrolled:true,additional_dns:[row]} as RegistryHost
const destinations=[{id:'pb',provider:'porkbun',prefix:'hosts.example.org'}]
test('unpublish addresses only the selected destination and revision',async()=>{
 vi.mocked(api.dnsDestinations).mockResolvedValue({destinations});vi.mocked(api.additionalDns).mockResolvedValue({dns:null})
 render(<AdditionalHostDns host={host} refresh={()=>{}}/>);fireEvent.click(screen.getByText('Unpublish porkbun DNS'))
 await waitFor(()=>expect(api.additionalDns).toHaveBeenCalledWith('host','pb','unpublish',3,undefined))
})
test('release requires an explicit review and disabled absent record',async()=>{
 vi.mocked(api.dnsDestinations).mockResolvedValue({destinations});vi.mocked(api.additionalDns).mockResolvedValue({dns:null})
 render(<AdditionalHostDns host={{...host,additional_dns:[{...row,enabled:false,desired_action:'absent',record_id:''}]}} refresh={()=>{}}/> )
 fireEvent.click(screen.getByText('Review porkbun name release'));expect(api.additionalDns).not.toHaveBeenCalled()
 fireEvent.click(screen.getByText('Confirm name release'));await waitFor(()=>expect(api.additionalDns).toHaveBeenCalledWith('host','pb','release',3,undefined))
})
test('reservation chooses a destination and a separate label',async()=>{
 vi.mocked(api.dnsDestinations).mockResolvedValue({destinations});vi.mocked(api.additionalDns).mockResolvedValue({dns:null})
 render(<AdditionalHostDns host={{...host,additional_dns:[]}} refresh={()=>{}}/> )
 await screen.findByText('Add DNS destination')
 fireEvent.change(screen.getByLabelText('Destination'),{target:{value:'pb'}});fireEvent.change(screen.getByLabelText('DNS label'),{target:{value:'compiler'}})
 fireEvent.click(screen.getByText('Reserve and publish'));await waitFor(()=>expect(api.additionalDns).toHaveBeenCalledWith('host','pb','reserve',undefined,'compiler'))
})
