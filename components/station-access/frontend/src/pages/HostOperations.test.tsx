// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { HostOperations } from './HostOperations'
import { api, type RegistryHost } from '../api'
vi.mock('../api',()=>({api:{hostLogin:vi.fn(),hostMirror:vi.fn()}}))
const host={id:'host-1',station_login:{available:true,revision:1,source_active:true},mirror_role:{selected:false,revision:0,endpoint:'',state:'unassigned',ready:false,reason:''}} as RegistryHost
afterEach(()=>{cleanup();vi.useRealTimers()})
beforeEach(()=>{vi.resetAllMocks();vi.mocked(api.hostLogin).mockResolvedValue({username:'station-admin',password:'synthetic-password',revision:1});vi.mocked(api.hostMirror).mockResolvedValue({})})
test('masks by default, reveals only on demand and hides on timeout',async()=>{
 vi.useFakeTimers();render(<HostOperations host={host} refresh={()=>{}} />)
 expect(api.hostLogin).not.toHaveBeenCalled();expect(screen.queryByText('synthetic-password')).toBeNull()
 await act(async()=>{fireEvent.click(screen.getByText('Reveal password'))})
 expect(screen.getByText('synthetic-password')).toBeTruthy();expect(api.hostLogin).toHaveBeenCalledWith('host-1',1)
 act(()=>vi.advanceTimersByTime(30000));expect(screen.queryByText('synthetic-password')).toBeNull()
})
test('does not show a late secret response after credential revision changes',async()=>{
 let resolve!:(v:{username:string;password:string;revision:number})=>void
 vi.mocked(api.hostLogin).mockReturnValue(new Promise(r=>{resolve=r}))
 const view=render(<HostOperations host={host} refresh={()=>{}} />)
 fireEvent.click(screen.getByText('Reveal password'))
 view.rerender(<HostOperations host={{...host,station_login:{available:true,revision:2}}} refresh={()=>{}} />)
 await act(async()=>{resolve({username:'station-admin',password:'synthetic-password',revision:1})})
 expect(screen.queryByText('synthetic-password')).toBeNull()
})
test('assigns an explicit HTTPS endpoint and removes role while retaining archives',async()=>{
 const refresh=vi.fn();const view=render(<HostOperations host={host} refresh={refresh} />)
 fireEvent.change(screen.getByLabelText('Mirror HTTPS address'),{target:{value:'https://mirror.example.test'}})
 fireEvent.click(screen.getByText('Assign mirror role'))
 await waitFor(()=>expect(api.hostMirror).toHaveBeenCalledWith('host-1',true,'https://mirror.example.test',0))
 view.rerender(<HostOperations host={{...host,mirror_role:{...host.mirror_role!,selected:true,revision:1,endpoint:'https://mirror.example.test'}}} refresh={refresh} />)
 await waitFor(()=>expect(refresh).toHaveBeenCalled())
 fireEvent.click(screen.getByText('Remove role; retain archives'))
 await waitFor(()=>expect(api.hostMirror).toHaveBeenCalledWith('host-1',false,'https://mirror.example.test',1))
})
test('tab hiding cancels a pending reveal',async()=>{
 let resolve!:(v:{username:string;password:string;revision:number})=>void
 vi.mocked(api.hostLogin).mockReturnValue(new Promise(r=>{resolve=r}))
 render(<HostOperations host={host} refresh={()=>{}} />)
 fireEvent.click(screen.getByText('Reveal password'))
 const hidden=vi.spyOn(document,'hidden','get').mockReturnValue(true)
 fireEvent(document,new Event('visibilitychange'))
 hidden.mockRestore()
 await act(async()=>{resolve({username:'station-admin',password:'synthetic-password',revision:1})})
 expect(screen.queryByText('synthetic-password')).toBeNull()
})
