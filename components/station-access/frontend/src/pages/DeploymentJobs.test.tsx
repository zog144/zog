// @vitest-environment jsdom
import {render,screen,fireEvent,waitFor,cleanup} from '@testing-library/react'
import {afterEach,expect,test,vi} from 'vitest'
import {deploymentApi,DeploymentJob} from '../api'
import {DeploymentJobs} from './DeploymentJobs'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
const row={label:'Primary',server:'https://registry.example',enabled:true,revision:1}
function job(state:string):DeploymentJob{return {id:'job',host_id:'host',host_label:'Compiler',operation:state==='succeeded'?'inspect':'apply',state,actor:'admin',message:'',created_at:new Date().toISOString(),started_at:null,finished_at:new Date().toISOString(),expires_at:new Date(Date.now()+300000).toISOString(),target:{account_id:'123456789012',region:'us-east-1',instance_id:'i-12345678'},destinations:[row],result:state==='succeeded'?{observation:{primary:row.server,destinations_sha256:'a'.repeat(64),destinations:[row],beacon_state:'active',station_state:'unknown',beacon_version:'0.3.4',station_version:null,apply_supported:true,reason:'Ready to review destination changes.'}}:{before:[{...row,label:'Previous'}],primary:row.server}}}
function list(jobs:DeploymentJob[],enabled=true){vi.spyOn(deploymentApi,'list').mockResolvedValue({enabled,hosts:[{id:'host',label:'Compiler',eligible:true}],jobs})}
test('loading and refreshing never submit a remote operation',async()=>{
 list([]);const inspect=vi.spyOn(deploymentApi,'inspect');const apply=vi.spyOn(deploymentApi,'action')
 render(<DeploymentJobs/>);await screen.findByText('No deployment jobs yet.')
 fireEvent.click(screen.getByText('Refresh job status'));expect(inspect).not.toHaveBeenCalled();expect(apply).not.toHaveBeenCalled()
})
test('inspection explicitly targets selected host with immutable action id',async()=>{
 list([]);vi.spyOn(crypto,'randomUUID').mockReturnValue('00000000-0000-4000-8000-000000000001')
 const inspect=vi.spyOn(deploymentApi,'inspect').mockResolvedValue({job:job('queued')})
 render(<DeploymentJobs/>);await screen.findByText('No deployment jobs yet.')
 fireEvent.change(screen.getByLabelText('Deployment host'),{target:{value:'host'}});fireEvent.click(screen.getByText('Inspect host deployment'))
 await waitFor(()=>expect(inspect).toHaveBeenCalledWith('host','00000000-0000-4000-8000-000000000001'))
})
test('review does not apply, confirmation sends exact displayed job',async()=>{
 list([job('review')]);const apply=vi.spyOn(deploymentApi,'action').mockResolvedValue({job:job('queued')})
 render(<DeploymentJobs/>);await screen.findByText('Proposed destination list');expect(screen.getByText('Previous')).toBeTruthy();expect(apply).not.toHaveBeenCalled()
 fireEvent.click(screen.getByText('Confirm and apply destinations'));await waitFor(()=>expect(apply).toHaveBeenCalledWith('job','apply'))
})
test('uncertain change offers only read-only outcome check',async()=>{
 list([job('uncertain')]);const action=vi.spyOn(deploymentApi,'action').mockResolvedValue({job:job('queued')})
 render(<DeploymentJobs/>);await screen.findByText('Check original outcome')
 expect(screen.queryByText('Confirm and apply destinations')).toBeNull()
 expect((screen.getByText('Inspect host deployment') as HTMLButtonElement).disabled).toBe(true)
 fireEvent.click(screen.getByText('Check original outcome'));await waitFor(()=>expect(action).toHaveBeenCalledWith('job','check-outcome'))
})
test('expired reviews and disabled worker prevent confirmation',async()=>{
 const old=job('review');old.expires_at=new Date(0).toISOString();list([old],false)
 render(<DeploymentJobs/>);await screen.findByText('Review expired')
 expect((screen.getByText('Confirm and apply destinations') as HTMLButtonElement).disabled).toBe(true)
 expect(screen.getByText(/Deployment jobs are not enabled/)).toBeTruthy()
})
test('fresh supported inspection exposes explicit review',async()=>{
 const inspected=job('succeeded');list([inspected]);const review=vi.spyOn(deploymentApi,'review').mockResolvedValue({job:job('review')})
 render(<DeploymentJobs/>);fireEvent.click(await screen.findByText('Review saved destinations'))
 await waitFor(()=>expect(review).toHaveBeenCalledWith('host','job'))
})
