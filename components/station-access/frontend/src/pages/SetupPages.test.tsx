// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {beforeEach,afterEach,expect,test,vi} from 'vitest'
import {api,setupApi,deploymentApi} from '../api'
import {RegistriesPage,DeploymentsPage} from './SetupPages'
const session=vi.hoisted(()=>({user:{is_superuser:true}}))
vi.mock('../auth/AuthProvider',()=>({useAuth:()=>session}))
afterEach(()=>{cleanup();vi.restoreAllMocks();session.user.is_superuser=true})
beforeEach(()=>{vi.spyOn(api,"dnsDestinations").mockResolvedValue({destinations:[]});vi.spyOn(deploymentApi,'list').mockResolvedValue({enabled:false,hosts:[],jobs:[]})})
const registry={registries:[],vault_ready:true,dns_selection:{credential_id:'',revision:0}}
test('provider passwords are masked and erased after saving; Porkbun limitation explicit',async()=>{
 vi.spyOn(setupApi,'registries').mockResolvedValue(registry)
 const save=vi.spyOn(setupApi,'saveRegistry').mockResolvedValue(registry)
 render(<RegistriesPage/>);await waitFor(()=>expect((screen.getByRole('button',{name:'Save provider account'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.change(screen.getByLabelText('Label'),{target:{value:'DNS'}})
 fireEvent.change(screen.getByLabelText('Cloudflare account ID'),{target:{value:'a'.repeat(32)}})
 const token=screen.getByLabelText('API token') as HTMLInputElement;expect(token.type).toBe('password')
 fireEvent.change(token,{target:{value:'private-token'}});fireEvent.submit(token.closest('form')!)
 await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({secrets:{api_token:'private-token'}})))
 await screen.findByRole('status');expect(token.value).toBe('')
 fireEvent.change(screen.getByLabelText('Provider'),{target:{value:'porkbun'}})
 expect(screen.getByText(/Enter both keys/)).toBeTruthy();expect((screen.getByLabelText('Secret API key') as HTMLInputElement).type).toBe('password')
})
test('no administrative setup fetch for ordinary users',()=>{
 session.user.is_superuser=false;const get=vi.spyOn(setupApi,'registries');render(<RegistriesPage/>);expect(screen.getByText('Administrator access required.')).toBeTruthy();expect(get).not.toHaveBeenCalled()
})
test('destination save carries revision and clearly separates save from installation',async()=>{
 const row={id:'id',label:'Central',server:'https://registry.test',enabled:true,ca_certificate:'',revision:3}
 vi.spyOn(setupApi,'deployments').mockResolvedValue({version:1,destinations:[row]})
 const save=vi.spyOn(setupApi,'saveDestination').mockResolvedValue({version:1,destinations:[{...row,enabled:false,revision:4}]})
 render(<DeploymentsPage/>);await screen.findByText('Central')
 expect(screen.getByText(/Installation status unknown/)).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Edit destination'}));expect((screen.getByLabelText('Registry HTTPS URL') as HTMLInputElement).disabled).toBe(true)
 fireEvent.click(screen.getByLabelText('Enable beaconing to this registry'))
 fireEvent.submit(screen.getByLabelText('Label').closest('form')!)
 await waitFor(()=>expect(save).toHaveBeenCalledWith({...row,enabled:false}))
 await screen.findByText('List saved. Review a host deployment below to apply it, or download the file for manual installation.')
 expect(screen.getByRole('link',{name:'Download beacon destination list'}).getAttribute('href')).toBe('/api/setup/deployments/?download=1')
})
test('save conflicts are visible',async()=>{
 vi.spyOn(setupApi,'deployments').mockResolvedValue({version:1,destinations:[]})
 vi.spyOn(setupApi,'saveDestination').mockRejectedValue(new Error('Configuration changed; refresh before saving'))
 render(<DeploymentsPage/>);fireEvent.submit(screen.getByLabelText('Label').closest('form')!)
 expect((await screen.findByRole('alert')).textContent).toContain('refresh before saving')
})

test('Porkbun saves both keys and allows explicit checks without DNS selection',async()=>{
 const account={id:'porkbun',label:'Porkbun account',provider:'porkbun' as const,account_id:'',revision:1,configured:true,supported:false,can_check:true}
 vi.spyOn(setupApi,'registries').mockResolvedValue({...registry,registries:[account]})
 const save=vi.spyOn(setupApi,'saveRegistry').mockResolvedValue(registry)
 const check=vi.spyOn(setupApi,'checkProvider').mockResolvedValue({} as never)
 render(<RegistriesPage/>);await screen.findByText('Porkbun account')
 expect(screen.queryByRole('button',{name:'Use for DNS reconciliation'})).toBeNull()
 fireEvent.click(screen.getByRole('button',{name:'Check access and list domains'}))
 await waitFor(()=>expect(check).toHaveBeenCalledWith('porkbun',1))
 await screen.findByText('Read-only check finished. Review the account result below.')
 fireEvent.change(screen.getByLabelText('Provider'),{target:{value:'porkbun'}})
 fireEvent.change(screen.getByLabelText('Label'),{target:{value:'Second Porkbun'}})
 const key=screen.getByLabelText('API key') as HTMLInputElement
 const secret=screen.getByLabelText('Secret API key') as HTMLInputElement
 expect(key.type).toBe('password');expect(secret.type).toBe('password')
 fireEvent.change(key,{target:{value:'public-fixture'}});fireEvent.change(secret,{target:{value:'secret-fixture'}})
 fireEvent.submit(key.closest('form')!)
 await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({provider:'porkbun',secrets:{api_key:'public-fixture',secret_key:'secret-fixture'}})))
 await screen.findByText('Credentials saved. API keys are never returned to the browser.')
 expect((screen.getByLabelText('API token') as HTMLInputElement).value).toBe('')
})
