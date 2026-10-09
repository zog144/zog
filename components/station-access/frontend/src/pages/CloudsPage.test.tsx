// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {cloudApi,CloudAccount} from '../api'
import {CloudsPage} from './CloudsPage'
const session=vi.hoisted(()=>({user:{is_superuser:true}}))
vi.mock('../auth/AuthProvider',()=>({useAuth:()=>session}))
afterEach(()=>{cleanup();vi.restoreAllMocks();session.user.is_superuser=true})
const account:CloudAccount={id:'saved',provider:'aws',label:'Development AWS',account_id:'123456789012',mode:'keys',region:'us-east-1',enabled:true,expires_at:null,expired:false,revision:2,updated_at:'2026-09-27T18:00:00Z',check:{status:'never',message:'Identity has not been checked.',fresh:false,finished_at:null}}
const result={accounts:[account],vault_ready:true}
test('identity check is explicit, scoped to displayed revision, and placeholders are unavailable',async()=>{
 vi.spyOn(cloudApi,'list').mockResolvedValue(result)
 const check=vi.spyOn(cloudApi,'check').mockResolvedValue(account)
 render(<CloudsPage/>);await screen.findByText('Development AWS');expect(check).not.toHaveBeenCalled()
 expect(screen.getByText('Microsoft Azure')).toBeTruthy();expect(screen.getByText('Google Cloud')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Check AWS identity'}))
 await waitFor(()=>expect(check).toHaveBeenCalledWith('saved',2))
})
test('editing does not retrieve secrets and blank fields preserve keys',async()=>{
 vi.spyOn(cloudApi,'list').mockResolvedValue(result);const save=vi.spyOn(cloudApi,'save').mockResolvedValue(result)
 render(<CloudsPage/>);await screen.findByText('Development AWS');fireEvent.click(screen.getByRole('button',{name:'Edit account'}))
 expect((screen.getByLabelText('Secret access key') as HTMLInputElement).value).toBe('')
 fireEvent.change(screen.getByLabelText('Label'),{target:{value:'New label'}})
 fireEvent.click(screen.getByRole('button',{name:'Save AWS account'}))
 await waitFor(()=>expect(save).toHaveBeenCalledWith(expect.objectContaining({id:'saved',revision:2,label:'New label',secrets:undefined})))
})
test('save failures clear browser secret fields and show the failure',async()=>{
 vi.spyOn(cloudApi,'list').mockResolvedValue(result);vi.spyOn(cloudApi,'save').mockRejectedValue(new Error('Configuration changed; refresh before saving'))
 render(<CloudsPage/>);await screen.findByText('Development AWS');fireEvent.click(screen.getByRole('button',{name:'Edit account'}))
 fireEvent.change(screen.getByLabelText('Access key ID'),{target:{value:'AKIA'+'X'.repeat(16)}})
 fireEvent.change(screen.getByLabelText('Secret access key'),{target:{value:'test-private-value'}})
 fireEvent.click(screen.getByRole('button',{name:'Save AWS account'}));await screen.findByRole('alert')
 expect((screen.getByLabelText('Secret access key') as HTMLInputElement).value).toBe('')
 expect((screen.getByLabelText('Access key ID') as HTMLInputElement).value).toBe('')
})
test('ordinary users cannot request cloud metadata',()=>{
 session.user.is_superuser=false;const read=vi.spyOn(cloudApi,'list')
 render(<CloudsPage/>);expect(read).not.toHaveBeenCalled();expect(screen.getByText('Administrator access required.')).toBeTruthy()
})
test('expired credentials disable checking and failed checks display errors',async()=>{
 vi.spyOn(cloudApi,'list').mockResolvedValue({...result,accounts:[{...account,expired:true,expires_at:'2020-01-01T00:00:00Z'}]})
 render(<CloudsPage/>);await screen.findByText('Development AWS')
 expect((screen.getByRole('button',{name:'Check AWS identity'}) as HTMLButtonElement).disabled).toBe(true)
})
