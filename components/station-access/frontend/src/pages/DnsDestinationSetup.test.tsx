// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {beforeEach,afterEach,it,expect,vi} from 'vitest'
import {api,dnsSetupApi,type ProviderAccount} from '../api'
import {DnsDestinationSetup} from './DnsDestinationSetup'
const account:ProviderAccount={id:'saved',label:'Porkbun test',provider:'porkbun',account_id:'',revision:2,configured:true,supported:false}
afterEach(cleanup)
beforeEach(()=>{vi.restoreAllMocks();vi.spyOn(api,'dnsDestinations').mockResolvedValue({destinations:[]})})
it('requires review and explicit confirmation, clearing review on changed inputs',async()=>{
 vi.spyOn(dnsSetupApi,'zones').mockResolvedValue({zones:[{id:'example.org',name:'example.org'}],cursor:null})
 const review=vi.spyOn(dnsSetupApi,'review').mockResolvedValue({review_id:'review',expires_at:2000000000,domain:'example.org',prefix:'hosts.example.org',nameservers:['ns.example.net'],provider:'porkbun',provider_writes:0,write_permission:'unverified',ready:true})
 const commit=vi.spyOn(dnsSetupApi,'commit').mockResolvedValue({binding_id:'saved',provider_writes:0,replayed:false})
 render(<DnsDestinationSetup accounts={[account]}/>);fireEvent.change(screen.getByLabelText('Saved provider account'),{target:{value:'saved'}})
 fireEvent.click(screen.getByText('Load domains'));await screen.findByText('example.org');fireEvent.change(screen.getByLabelText('Domain'),{target:{value:'example.org'}})
 fireEvent.click(screen.getByText('Review DNS destination'));await screen.findByText('Confirm DNS destination');expect(review).toHaveBeenCalledWith('saved',2,'example.org','hosts');expect(commit).not.toHaveBeenCalled()
 fireEvent.change(screen.getByLabelText('Host-name prefix'),{target:{value:'lab'}});expect(screen.queryByText('Confirm DNS destination')).toBeNull()
 fireEvent.click(screen.getByText('Review DNS destination'));await screen.findByText('Confirm DNS destination');fireEvent.click(screen.getByText('Confirm DNS destination'))
 await waitFor(()=>expect(commit).toHaveBeenCalledWith('review'));await screen.findByText('DNS destination saved. Assign hosts from the Hosts page.')
})
it('shows a safe provider error without offering confirmation',async()=>{
 vi.spyOn(dnsSetupApi,'zones').mockRejectedValue(new Error('Provider authentication failed.'))
 render(<DnsDestinationSetup accounts={[account]}/>);fireEvent.change(screen.getByLabelText('Saved provider account'),{target:{value:'saved'}});fireEvent.click(screen.getByText('Load domains'))
 expect((await screen.findByRole('alert')).textContent).toContain('Provider authentication failed.');expect(screen.queryByText('Confirm DNS destination')).toBeNull()
})
it('shows pending recovery and stale host evidence',async()=>{
 vi.spyOn(dnsSetupApi,'inspect').mockResolvedValue({ready:false,authority:'verified',provider_reads:'verified',write_permission:'unverified',operations:[{state:'uncertain',host_id:'host',code:null}],hosts:[{host_id:'host',stage:'host-evidence',code:'stale-evidence',message:'Wait for fresh evidence.'}]})
 render(<DnsDestinationSetup accounts={[account]}/>);fireEvent.click(screen.getByText('Check primary DNS destination'))
 await screen.findByText(/Pending recovery: uncertain/);expect(screen.getByText(/stale-evidence/)).toBeTruthy()
})
