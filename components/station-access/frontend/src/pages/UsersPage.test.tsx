// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {afterEach,beforeEach,expect,test,vi} from 'vitest'
import {usersApi,ManagedUser} from '../api'
import {UsersPage} from './UsersPage'
const session=vi.hoisted(()=>({user:{id:1,username:'admin',is_superuser:true},refresh:vi.fn()}))
vi.mock('../auth/AuthProvider',()=>({useAuth:()=>session}))
const member:ManagedUser={id:2,username:'member',email:'',first_name:'',last_name:'',is_active:true,is_superuser:false,revision:'revision',date_joined:'2026-09-29T12:00:00Z',last_login:null,workspace_count:0,application_count:0}
beforeEach(()=>{vi.spyOn(usersApi,'list').mockResolvedValue({users:[member],page:1,pages:1,total:1})})
afterEach(()=>{cleanup();vi.restoreAllMocks();session.user.is_superuser=true})
test('ordinary users cannot load account data',()=>{session.user.is_superuser=false;render(<UsersPage/>);expect(screen.getByText('Administrator access required.')).toBeTruthy();expect(usersApi.list).not.toHaveBeenCalled()})
test('create uses masked password and clears it after save',async()=>{
 const create=vi.spyOn(usersApi,'create').mockResolvedValue({user:member});render(<UsersPage/>);await screen.findByText('member')
 fireEvent.change(screen.getByLabelText('Username'),{target:{value:'new-user'}})
 const password=screen.getByLabelText('Password') as HTMLInputElement;expect(password.type).toBe('password')
 fireEvent.change(password,{target:{value:'Unique-fixture-password-92!'}});fireEvent.submit(password.closest('form')!)
 await screen.findByText('User saved.');expect(create).toHaveBeenCalledWith(expect.objectContaining({username:'new-user',is_superuser:false,password:'Unique-fixture-password-92!'}));expect(password.value).toBe('')
})
test('edit sends revision and blank password keeps existing credentials',async()=>{
 const update=vi.spyOn(usersApi,'update').mockResolvedValue({user:member});render(<UsersPage/>);fireEvent.click(await screen.findByText('Edit member'))
 fireEvent.change(screen.getByLabelText('Email'),{target:{value:'member@example.test'}});fireEvent.click(screen.getByLabelText('Active account'));fireEvent.click(screen.getByText('Save user'))
 await waitFor(()=>expect(update).toHaveBeenCalledWith(2,expect.objectContaining({revision:'revision',email:'member@example.test',is_active:false,password:''})))
})
test('deletion requires exact displayed username confirmation',async()=>{
 const remove=vi.spyOn(usersApi,'remove').mockResolvedValue({deleted:true});render(<UsersPage/>);fireEvent.click(await screen.findByText('Delete member'))
 expect((screen.getByText('Confirm deletion') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.change(screen.getByLabelText('Type the username to confirm'),{target:{value:'member'}});fireEvent.click(screen.getByText('Confirm deletion'))
 await waitFor(()=>expect(remove).toHaveBeenCalledWith(2,'revision','member'));await screen.findByText('User deleted.')
})
test('self and owned accounts have deletion guards',async()=>{
 vi.mocked(usersApi.list).mockResolvedValue({users:[{...member,id:1,username:'admin'}, {...member,workspace_count:1}],page:1,pages:1,total:2})
 render(<UsersPage/>);await screen.findByText('admin (you)')
 expect((screen.getByText('Delete admin') as HTMLButtonElement).disabled).toBe(true);expect((screen.getByText('Delete member') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByText('Edit admin'));expect((screen.getByLabelText('Administrator access') as HTMLInputElement).disabled).toBe(true);expect((screen.getByLabelText('Active account') as HTMLInputElement).disabled).toBe(true)
})
test('stale edit error is visible and password cleared on failure',async()=>{
 vi.spyOn(usersApi,'update').mockRejectedValue(new Error('Account changed. Refresh before saving.'))
 render(<UsersPage/>);fireEvent.click(await screen.findByText('Edit member'));const password=screen.getByLabelText('New password (optional)') as HTMLInputElement
 fireEvent.change(password,{target:{value:'Unique-fixture-password-92!'}});fireEvent.submit(password.closest('form')!)
 await screen.findByText('Account changed. Refresh before saving.');expect(password.value).toBe('')
})
