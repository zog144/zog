// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { api, type Workspace } from '../api'
import { VncSessionProvider } from '../vnc/VncSessionProvider'
import { WorkspacesPage } from './WorkspacesPage'
const workspace: Workspace = { id:'desk-1', number:1, name:'Research', network:'default', application_name:'vnc-workspace', desired_running:false, runtime_id:null, instance_id:null, status:'stopped', runtime_state:null, endpoint_bound:false, endpoint_ready:false, last_error:null, created_at:'now', updated_at:'revision-1' }
afterEach(() => { cleanup(); vi.restoreAllMocks() })
function setup() { render(<MemoryRouter><VncSessionProvider><WorkspacesPage /></VncSessionProvider></MemoryRouter>) }
it('creates and edits without starting a desktop', async () => {
  vi.spyOn(api, 'workspaces').mockResolvedValue({workspaces:[workspace]})
  const create = vi.spyOn(api, 'createWorkspace').mockResolvedValue({workspace})
  const edit = vi.spyOn(api, 'updateWorkspace').mockResolvedValue({workspace:{...workspace,name:'Writing'}})
  const grant = vi.spyOn(api, 'vncGrant')
  const start = vi.spyOn(api, 'startWorkspace')
  setup()
  await screen.findByRole('link', {name:'Research'})
  fireEvent.click(screen.getByRole('button', {name:'Create new workspace'}))
  fireEvent.change(screen.getByLabelText('Name'), {target:{value:'New desk'}})
  expect(screen.getByLabelText('Network').textContent).toBe('Default — shared host network')
  fireEvent.click(screen.getByRole('button', {name:'Save workspace'}))
  await waitFor(() => expect(create).toHaveBeenCalledWith('New desk','default'))
  await waitFor(() => expect(screen.queryByRole('form')).toBeNull())
  fireEvent.click(screen.getByRole('button', {name:'Edit Research'}))
  fireEvent.change(screen.getByLabelText('Name'), {target:{value:'Writing'}})
  fireEvent.click(screen.getByRole('button', {name:'Save workspace'}))
  await waitFor(() => expect(edit).toHaveBeenCalledWith(workspace,'Writing','default'))
  expect(grant).not.toHaveBeenCalled(); expect(start).not.toHaveBeenCalled()
})
it('requires explicit deletion confirmation and retains the row on failure', async () => {
  vi.spyOn(api,'workspaces').mockResolvedValue({workspaces:[workspace]})
  const remove = vi.spyOn(api,'deleteWorkspace').mockRejectedValue(new Error('Desktop termination is not confirmed'))
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Delete Research'}))
  expect(remove).not.toHaveBeenCalled()
  expect(screen.getByRole('region',{name:'Confirm workspace deletion'}).textContent).toContain('disconnects viewers')
  fireEvent.click(screen.getByRole('button',{name:'Delete workspace'}))
  await screen.findByRole('alert')
  expect(screen.getByRole('link',{name:'Research'})).toBeTruthy()
})
it('shows the empty state after successful deletion', async () => {
  vi.spyOn(api,'workspaces').mockResolvedValueOnce({workspaces:[workspace]}).mockResolvedValue({workspaces:[]})
  vi.spyOn(api,'deleteWorkspace').mockResolvedValue({deleted:true})
  setup()
  fireEvent.click(await screen.findByRole('button',{name:'Delete Research'}))
  fireEvent.click(screen.getByRole('button',{name:'Delete workspace'}))
  await screen.findByText('No workspaces yet. Create a workspace to get started.')
  expect(screen.queryByRole('region',{name:'Confirm workspace deletion'})).toBeNull()
})

it('shows provenance beside workspace management actions', async () => {
  vi.spyOn(api,'workspaces').mockResolvedValue({workspaces:[workspace]})
  setup()
  const link = await screen.findByRole('link',{name:'Provenance'})
  expect(link.getAttribute('href')).toBe('/workspaces/desk-1/provenance')
  expect(screen.getByRole('button',{name:'Edit Research'})).toBeTruthy()
  expect(screen.getByRole('button',{name:'Delete Research'})).toBeTruthy()
})
