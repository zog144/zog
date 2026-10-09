// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type Runtime, type WorkspaceApplications } from '../api'
import { WorkspaceApplicationsPanel } from './WorkspaceApplicationsPanel'
const runtime = { runtime_id:'runtime-one', application_name:'editor', instance_id:'editor-one', state:'running' } as Runtime
const page = { workspace:{name:'Research'}, applications:[{name:'editor',description:'Write documents'},{name:'browser',description:'Browse websites'}], runtimes:[runtime], launch:{available:false,code:'workspace_launch_not_supported',reason:'Awaiting shared networking and desktop access.'}, membership:{source:'recorded_launch_parameters',authoritative:false}, state_source:'recorded' } as WorkspaceApplications
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function setup(onClose = vi.fn()) { return render(<MemoryRouter><WorkspaceApplicationsPanel workspaceId="desk-one" onClose={onClose} /></MemoryRouter>) }
it('searches descriptions, explains launch block and links exact-runtime logs', async () => {
  vi.spyOn(api,'workspaceApplications').mockResolvedValue(page)
  const start = vi.spyOn(api,'startWorkspace')
  setup()
  await screen.findByText('Workspace: Research')
  expect((screen.getByRole('button',{name:'Launch editor'}) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.change(screen.getByLabelText('Search applications'),{target:{value:'websites'}})
  expect(screen.queryByRole('button',{name:'Launch editor'})).toBeNull()
  expect(screen.getByRole('button',{name:'Launch browser'})).toBeTruthy()
  expect(screen.getByRole('link',{name:'View logs'}).getAttribute('href')).toBe('/runtimes/runtime-one')
  expect(start).not.toHaveBeenCalled()
})
it('confirms before stopping and preserves the exact runtime target', async () => {
  vi.spyOn(api,'workspaceApplications').mockResolvedValue(page)
  const stop = vi.spyOn(api,'stopWorkspaceApplication').mockResolvedValue({runtime:{...runtime,state:'terminated'},stopped:true})
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Stop editor-one'}))
  expect(stop).not.toHaveBeenCalled()
  expect(screen.getByRole('region',{name:'Confirm application stop'}).textContent).toContain('workspace desktop stays running')
  fireEvent.click(screen.getByRole('button',{name:'Confirm stop'}))
  await screen.findByText('Application stopped.')
  expect(stop).toHaveBeenCalledWith('desk-one','runtime-one')
})
it('does not claim termination for a pending stop', async () => {
  vi.spyOn(api,'workspaceApplications').mockResolvedValue(page)
  vi.spyOn(api,'stopWorkspaceApplication').mockResolvedValue({runtime,stopped:false})
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Stop editor-one'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm stop'}))
  await screen.findByText('Stop requested; termination is not yet confirmed.')
})
it('keeps stop errors visible after a successful list refresh', async () => {
  const read = vi.spyOn(api,'workspaceApplications').mockResolvedValue(page)
  vi.spyOn(api,'stopWorkspaceApplication').mockRejectedValue(new Error('Stop status uncertain'))
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Stop editor-one'}))
  fireEvent.click(screen.getByRole('button',{name:'Confirm stop'}))
  await waitFor(() => expect(read.mock.calls.length).toBeGreaterThan(1))
  expect(screen.getByRole('alert').textContent).toBe('Stop status uncertain')
})
it('disables stale stop controls and cancels pending reads on close', async () => {
  const read = vi.spyOn(api,'workspaceApplications').mockResolvedValueOnce(page).mockRejectedValueOnce(new Error('Controller unavailable'))
  const close = vi.fn()
  const view = setup(close)
  await screen.findByRole('button',{name:'Stop editor-one'})
  fireEvent.click(screen.getByRole('button',{name:'Refresh applications'}))
  await screen.findByRole('alert')
  expect((screen.getByRole('button',{name:'Stop editor-one'}) as HTMLButtonElement).disabled).toBe(true)
  fireEvent.keyDown(screen.getByLabelText('Search applications'),{key:'Escape'})
  expect(close).toHaveBeenCalledOnce()
  view.unmount()
  expect(read.mock.calls.at(-1)?.[1]?.aborted).toBe(true)
})
it('retries a lost launch reply with the same action identity', async () => {
  const enabled = { ...page, applications: [{ ...page.applications[0], eligible: true }], launch: { available: true, code: 'ready', reason: 'Shared host network' }, membership: { source: 'controller', authoritative: true, pending_count: 1, cleanup_count: 0 } }
  vi.spyOn(api,'workspaceApplications').mockResolvedValue(enabled)
  const launch = vi.spyOn(api,'launchWorkspaceApplication').mockRejectedValueOnce(new Error('Reply lost')).mockResolvedValueOnce({action_id:'result',runtime})
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Launch editor'}))
  await screen.findByText('Reply lost')
  await waitFor(() => expect((screen.getByRole('button',{name:'Retry same launch'}) as HTMLButtonElement).disabled).toBe(false))
  const identifier = launch.mock.calls[0][2]
  fireEvent.click(screen.getByRole('button',{name:'Retry same launch'}))
  await screen.findByText('Launch recorded. Runtime status and logs are available below.')
  expect(launch).toHaveBeenNthCalledWith(2,'desk-one','editor',identifier)
  expect(screen.getByText(/1 pending ownership claims/)).toBeTruthy()
})
it('does not describe accepted cancellation as a stopped application', async () => {
  vi.spyOn(api,'workspaceApplications').mockResolvedValue({...page, launch_actions:[{id:'action',application:'editor',state:'uncertain',runtime_id:null}]})
  const cancel = vi.spyOn(api,'cancelWorkspaceLaunch').mockResolvedValue({state:'accepted'})
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Cancel pending launch'}))
  await screen.findByText('Launch was already accepted. Use Stop application to terminate its runtime.')
  expect(cancel).toHaveBeenCalledWith('desk-one','action')
})
it('checks application readiness without launching it', async () => {
  vi.spyOn(api,'workspaceApplications').mockResolvedValue(page)
  const launch = vi.spyOn(api,'launchWorkspaceApplication')
  const check = vi.spyOn(api,'workspacePreflight').mockResolvedValue({status:'blocked',advisory:true,checks:[{code:'image-inputs',title:'Root filesystem',status:'blocked',detail:'Publish a usable filesystem.'}]})
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Check editor'}))
  await screen.findByText('Root filesystem')
  expect(check.mock.calls[0].slice(0,2)).toEqual(['desk-one','editor'])
  expect(launch).not.toHaveBeenCalled()
})
