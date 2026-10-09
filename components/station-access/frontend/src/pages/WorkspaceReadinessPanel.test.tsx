// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type WorkspaceReadiness } from '../api'
import { WorkspaceReadinessPanel } from './WorkspaceReadinessPanel'
const value: WorkspaceReadiness = { observed_at:'2026-09-28T12:00:00Z',read_only:true,advisory:true,controller:'available',desktop:'running',desktop_runtime_id:'desktop-one',launch_pending:true,cleanup_pending:false,registration:'recorded',pending_count:1,cleanup_count:0,launch_actions:[{id:'action-one',application:'editor',state:'uncertain',runtime_id:null}],preflight:{status:'blocked',advisory:true,checks:[{code:'image-inputs',title:'Root filesystem',status:'blocked',detail:'Publish and activate a usable image-build generation, then refresh.'}]} }
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function setup() {
  const connect = vi.fn(), applications = vi.fn()
  const view = render(<MemoryRouter><WorkspaceReadinessPanel workspaceId="one" onConnect={connect} onApplications={applications} onClose={vi.fn()} /></MemoryRouter>)
  return { ...view, connect, applications }
}
it('shows loading without starting a desktop', () => {
  vi.spyOn(api,'workspaceReadiness').mockReturnValue(new Promise(() => {}))
  const launch = vi.spyOn(api,'startWorkspace')
  setup()
  expect(screen.getByRole('status').textContent).toContain('Checking controller')
  expect(launch).not.toHaveBeenCalled()
})
it('explains blocked preparation and preserves access to logs and recovery', async () => {
  vi.spyOn(api,'workspaceReadiness').mockResolvedValue(value)
  const { applications, connect } = setup()
  await screen.findByText('Root filesystem')
  expect(screen.getByText(/process is running; display access has not been verified/)).toBeTruthy()
  expect(screen.getByRole('link',{name:'View desktop logs'}).getAttribute('href')).toBe('/runtimes/desktop-one')
  expect(screen.getByLabelText('Recorded launch recovery').textContent).toContain('uncertain')
  fireEvent.click(screen.getByRole('button',{name:'Applications and logs'})); expect(applications).toHaveBeenCalledOnce()
  fireEvent.click(screen.getByRole('button',{name:'Connect desktop'})); expect(connect).toHaveBeenCalledOnce()
})
it('disables stale recovery controls and aborts reads on unmount', async () => {
  const read = vi.spyOn(api,'workspaceReadiness').mockResolvedValueOnce(value).mockRejectedValue(new Error('offline'))
  const view = setup()
  await screen.findByText('Root filesystem')
  fireEvent.click(screen.getByRole('button',{name:'Refresh status'}))
  await screen.findByRole('alert')
  expect((screen.getByRole('button',{name:'Connect desktop'}) as HTMLButtonElement).disabled).toBe(true)
  view.unmount()
  expect(read.mock.calls.at(-1)?.[1]?.aborted).toBe(true)
})
it('requires confirmation for cancellation and keeps uncertainty visible', async () => {
  vi.spyOn(api,'workspaceReadiness').mockResolvedValue(value)
  const stop = vi.spyOn(api,'stopWorkspace').mockRejectedValue(new Error('unresolved'))
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Stop or cancel desktop'}))
  expect(stop).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button',{name:'Confirm desktop stop'}))
  await screen.findByText(/Stop or cancellation is unresolved/)
  expect(stop).toHaveBeenCalledWith('one')
})
it('distinguishes controller readiness from browser acceptance', async () => {
  vi.spyOn(api,'workspaceReadiness').mockResolvedValue({...value,desktop:'ready'})
  setup()
  await screen.findByText(/Browser connectivity is verified only by connecting/)
})
it('keeps recorded recovery visible while the controller is offline', async () => {
  vi.spyOn(api,'workspaceReadiness').mockResolvedValue({...value,controller:'unavailable',preflight:null,pending_count:null,cleanup_count:null})
  setup()
  await screen.findByText('unavailable')
  expect((screen.getByRole('button',{name:'Stop or cancel desktop'}) as HTMLButtonElement).disabled).toBe(true)
  expect(screen.getByLabelText('Recorded launch recovery').textContent).toContain('editor')
  await waitFor(() => expect(screen.getByText(/Pending controller claims: Not verified/)).toBeTruthy())
})

it('shows ended desktop cleanup without claiming resources are released', async () => {
  vi.spyOn(api,'workspaceReadiness').mockResolvedValue({...value,desktop:'terminated',cleanup_pending:true,cleanup_count:1})
  setup()
  await screen.findByText(/Desktop cleanup is pending/)
  expect(screen.queryByText(/Controller display probes passed/)).toBeNull()
})

it('does not close another viewer when a stop finishes after navigation', async () => {
  vi.spyOn(api,'workspaceReadiness').mockResolvedValue(value)
  let finish!: (value: Awaited<ReturnType<typeof api.stopWorkspace>>) => void
  vi.spyOn(api,'stopWorkspace').mockReturnValue(new Promise(resolve => { finish = resolve }))
  const stopped = vi.fn()
  const view = render(<MemoryRouter><WorkspaceReadinessPanel workspaceId="one" onConnect={vi.fn()} onApplications={vi.fn()} onClose={vi.fn()} onStopped={stopped} /></MemoryRouter>)
  fireEvent.click(await screen.findByRole('button',{name:'Stop or cancel desktop'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm desktop stop'}))
  view.unmount()
  finish({workspace:{id:'one'} as import('../api').Workspace})
  await Promise.resolve()
  expect(stopped).not.toHaveBeenCalled()
})
