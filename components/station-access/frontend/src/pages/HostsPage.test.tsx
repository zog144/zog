// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import { HostsPage } from './HostsPage'
import type { HostInventory } from '../api'
import { api } from '../api'
vi.mock('../api', () => ({api:{hosts:vi.fn(),hostLabel:vi.fn()}}))
vi.mock('../auth/AuthProvider', () => ({useAuth:()=>({user:{is_superuser:true}})}))
const inventory: HostInventory={inventory_status:'complete' as const,server_time:'2026-09-19T00:00:00Z',scans:[{scope:'region-discovery',last_attempt:null,last_success:'2026-09-19T00:00:00Z',error:'',instance_count:0},{scope:'123/us-east-1',last_attempt:null,last_success:'2026-09-19T00:00:00Z',error:'',instance_count:1}],hosts:[{id:'host-one',label:'Compiler',provider:'aws',account_id:'123',region:'us-east-1',instance_id:'i-example',workspace_id:'workspace',first_seen:'2026-09-18T00:00:00Z',heartbeat:'overdue',last_received:null,aws_checked_at:'2026-09-19T00:00:00Z',aws_missing_since:null,aws_fresh:true,aws_state:'running',zog_tagged:true,tag_status:'zog' as const,public_address:'example.test',address_source:'aws' as const,address_stale:false,enrolled:true,report:{},aws:{state:'running',public_dns:'example.test',tags:{Project:'Zog'}}}]}
afterEach(() => cleanup())
beforeEach(()=>{vi.clearAllMocks();vi.mocked(api.hosts).mockResolvedValue(inventory);vi.mocked(api.hostLabel).mockResolvedValue({saved:true})})
test('shows missing heartbeat separately from running state and saves a label',async()=>{
 render(<HostsPage />)
 expect(await screen.findByText('Compiler')).toBeTruthy()
 expect(screen.getByText('Running without a recent heartbeat')).toBeTruthy()
 expect(screen.getAllByText('example.test')[0]).toBeTruthy()
 fireEvent.click(screen.getByText('Edit'))
 fireEvent.change(screen.getByLabelText('Host label'),{target:{value:'Toolchain build'}})
 fireEvent.click(screen.getByText('Save'))
 await waitFor(()=>expect(api.hostLabel).toHaveBeenCalledWith('host-one','Toolchain build'))
})
test('retains last inventory and reports refresh failure',async()=>{
 render(<HostsPage />)
 await screen.findByText('Compiler')
 vi.mocked(api.hosts).mockRejectedValue(new Error('Connection lost'))
 fireEvent.click(screen.getByText('Refresh'))
 expect((await screen.findByRole('alert')).textContent).toContain('displayed information may be stale')
 expect(screen.getByText('Compiler')).toBeTruthy()
})

test('unavailable inventory shows reported DNS and never classifies unknown tags as untagged',async()=>{
 vi.mocked(api.hosts).mockResolvedValue({...inventory,inventory_status:'unavailable',hosts:[{...inventory.hosts[0],last_received:inventory.server_time,tag_status:'unknown',aws_state:'unknown',aws_fresh:false,aws:{},address_source:'heartbeat'}]})
 render(<HostsPage />)
 await screen.findByText('AWS counts unavailable')
 expect(screen.getAllByText('example.test')[0]).toBeTruthy()
 expect(screen.getByText('Reported by daemon')).toBeTruthy()
 expect(screen.getByText('Tags unknown')).toBeTruthy()
 expect(screen.queryByText(/0 AWS running/)).toBeNull()
 fireEvent.change(screen.getByLabelText('Show'),{target:{value:'untagged'}})
 expect(screen.getByText('No hosts match.')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('Show'),{target:{value:'unknown-tags'}})
 expect(screen.getByText('Compiler')).toBeTruthy()
})

test('shows reported details and composes heartbeat, classification and search filters', async()=>{
 const reporting={...inventory.hosts[0],last_received:'2026-09-18T23:59:25Z',report:{hostname:'compiler.internal',private_ip:'10.0.0.8',daemon_version:'0.1.0',boot_id:'boot-example'}}
 vi.mocked(api.hosts).mockResolvedValue({...inventory,hosts:[reporting,{...reporting,id:'old',label:'Old compiler',last_received:'2026-09-18T23:50:00Z'},{...reporting,id:'never',label:'Inventory only',last_received:null,report:{},enrolled:false}]})
 render(<HostsPage />)
 await screen.findByText('Seen 35 seconds ago')
 expect(screen.getAllByText('compiler.internal')[0]).toBeTruthy()
 expect(screen.getAllByText('boot-example')).toHaveLength(2)
 expect(screen.getAllByText('0.1.0')).toHaveLength(2)
 fireEvent.change(screen.getByLabelText('Heartbeat'),{target:{value:'overdue'}})
 expect(screen.getByText('Old compiler')).toBeTruthy()
 expect(screen.queryByText('Compiler')).toBeNull()
 fireEvent.change(screen.getByLabelText('Heartbeat'),{target:{value:'never'}})
 expect(screen.getByText('Inventory only')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('Heartbeat'),{target:{value:'recent'}})
 fireEvent.change(screen.getByLabelText('Search'),{target:{value:'10.0.0.8'}})
 expect(screen.getByText('Compiler')).toBeTruthy()
 expect(screen.getByText('1 of 3 hosts shown')).toBeTruthy()
 fireEvent.change(screen.getByLabelText('Show'),{target:{value:'untagged'}})
 expect(screen.getByText('No hosts match.')).toBeTruthy()
})

test('archived records remain in AWS counts and have an explicit list filter',async()=>{
 vi.mocked(api.hosts).mockResolvedValue({...inventory,hosts:[{...inventory.hosts[0],archived_at:'2026-09-18T23:00:00Z'}]})
 render(<HostsPage/>);await screen.findByText('1 AWS running observed')
 expect(screen.queryByText('Compiler')).toBeNull()
 fireEvent.change(screen.getByLabelText('Records'),{target:{value:'archived'}})
 expect(screen.getByText('Compiler')).toBeTruthy();expect(screen.getByRole('link',{name:'Host details and removal'}).getAttribute('href')).toBe('/hosts/host-one')
})
