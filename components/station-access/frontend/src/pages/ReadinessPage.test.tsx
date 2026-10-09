// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {MemoryRouter} from 'react-router-dom'
import {beforeEach,afterEach,expect,test,vi} from 'vitest'
import {api,setupApi,SetupReadiness,ProviderAccount,ProviderAccessCheck} from '../api'
import {ReadinessPage} from './ReadinessPage'
import {RegistriesPage} from './SetupPages'
const session=vi.hoisted(()=>({user:{is_superuser:true}}))
vi.mock('../auth/AuthProvider',()=>({useAuth:()=>session}))
beforeEach(()=>{vi.spyOn(api,"dnsDestinations").mockResolvedValue({destinations:[]})})
afterEach(()=>{cleanup();vi.restoreAllMocks();session.user.is_superuser=true})
const snapshot:SetupReadiness={read_only:true,server_time:'2026-09-27T18:00:00Z',checks:[
 {id:'destinations',title:'Beacon destination deployment',area:'Central registry',status:'configured',detail:'Saved intent; installation acknowledgement unavailable.',link:'/deployments',observed_at:null},
 {id:'beacons',title:'Signed host observations',area:'Central registry',status:'observed',detail:'One recent signed report.',link:'/hosts',observed_at:'2026-09-27T17:59:50Z'},
 {id:'workspaces',title:'Graphical workspace launch',area:'Local station',status:'blocked',detail:'Controller contract pending.',link:'/workspaces',observed_at:null},
]}
test('readiness distinguishes configuration, observation and blocked capability',async()=>{
 vi.spyOn(setupApi,'readiness').mockResolvedValue(snapshot)
 render(<MemoryRouter><ReadinessPage/></MemoryRouter>)
 await screen.findByText('Signed host observations')
 expect(screen.getByText('Configured')).toBeTruthy();expect(screen.getByText('Recently observed')).toBeTruthy();expect(screen.getByText('Blocked')).toBeTruthy()
 expect(screen.getByText(/installation acknowledgement unavailable/)).toBeTruthy();expect(screen.getByText(/Snapshot:/)).toBeTruthy()
 expect(screen.getAllByRole('link',{name:'Open related settings'})[0].getAttribute('href')).toBe('/deployments')
})
test('failed refresh removes stale observations',async()=>{
 vi.spyOn(setupApi,'readiness').mockResolvedValueOnce(snapshot).mockRejectedValueOnce(new Error('Observations unavailable'))
 render(<MemoryRouter><ReadinessPage/></MemoryRouter>);await screen.findByText('Signed host observations')
 fireEvent.click(screen.getByRole('button',{name:'Refresh observations'}));await screen.findByRole('alert')
 expect(screen.queryByText('Recently observed')).toBeNull()
})
test('ordinary users cannot load readiness',()=>{
 session.user.is_superuser=false;const read=vi.spyOn(setupApi,'readiness')
 render(<MemoryRouter><ReadinessPage/></MemoryRouter>);expect(read).not.toHaveBeenCalled();expect(screen.getByText('Administrator access required.')).toBeTruthy()
})
const checked:ProviderAccessCheck={status:'passed',message:'Domain listing succeeded. This does not verify DNS-write permission.',fresh:false,domains:[{id:'zone',name:'example.test',status:'active'}],more_available:true,started_at:'2026-09-27T18:00:00Z',finished_at:'2026-09-27T18:00:01Z',retry_after_seconds:0}
const account:ProviderAccount={id:'credential',label:'Cloudflare account',provider:'cloudflare',account_id:'a'.repeat(32),revision:4,configured:true,supported:true}
test('Cloudflare access check is explicit and shows partial stale evidence honestly',async()=>{
 const response={registries:[account],vault_ready:true,dns_selection:{credential_id:'',revision:0}}
 vi.spyOn(setupApi,'registries').mockResolvedValueOnce(response).mockResolvedValueOnce({...response,registries:[{...account,access_check:checked}]})
 const check=vi.spyOn(setupApi,'checkProvider').mockResolvedValue({access_check:checked})
 render(<RegistriesPage/>);await screen.findByText('Cloudflare account');expect(check).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Check access and list domains'}))
 await waitFor(()=>expect(check).toHaveBeenCalledWith('credential',4))
 await screen.findByText('example.test — active')
 expect(screen.getByText(/up to 50 domains/)).toBeTruthy();expect(screen.getByText(/Not a current verification/)).toBeTruthy()
 expect(screen.getByText(checked.message)).toBeTruthy()
})
test('check throttling is presented to the operator',async()=>{
 vi.spyOn(setupApi,'registries').mockResolvedValue({registries:[account],vault_ready:true,dns_selection:{credential_id:'',revision:0}})
 vi.spyOn(setupApi,'checkProvider').mockRejectedValue(new Error('Wait one minute between checks for this account'))
 render(<RegistriesPage/>);await screen.findByText('Cloudflare account');fireEvent.click(screen.getByRole('button',{name:'Check access and list domains'}))
 expect((await screen.findByRole('alert')).textContent).toContain('Wait one minute')
})
