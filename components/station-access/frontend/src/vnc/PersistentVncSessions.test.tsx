// @vitest-environment jsdom
import { VncPage } from '../pages/VncPage'
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Link, Routes, Route } from 'react-router-dom'
import { api } from '../api'
import { VncSessionProvider, useVncSessions } from './VncSessionProvider'
import { PersistentVncSessions } from './PersistentVncSessions'
function Controls() {
  const { open, close } = useVncSessions()
  return <><button onClick={() => { void open('one'); void open('one') }}>Open</button><button onClick={() => close('one')}>Close</button><Link to="/applications">Applications</Link></>
}
afterEach(() => { cleanup(); vi.restoreAllMocks() })
it('keeps the same iframe during navigation and coalesces simultaneous opens', async () => {
  const grant = vi.spyOn(api, 'vncGrant').mockResolvedValue({ token: 'fixture', expires_at: 'later', novnc_url: 'about:blank' })
  const view = render(<MemoryRouter initialEntries={['/vnc/one']}><VncSessionProvider><Controls/><PersistentVncSessions/></VncSessionProvider></MemoryRouter>)
  fireEvent.click(screen.getByText('Open'))
  await waitFor(() => expect(view.container.querySelectorAll('iframe')).toHaveLength(1))
  expect(grant).toHaveBeenCalledTimes(1)
  const frame = view.container.querySelector('iframe')
  fireEvent.click(screen.getByText('Applications'))
  expect(view.container.querySelector('iframe')).toBe(frame)
  expect(frame?.classList.contains('active')).toBe(false)
  fireEvent.click(screen.getByText('Close'))
  expect(view.container.querySelector('iframe')).toBeNull()
})

it('opening and closing the application panel preserves the desktop iframe', async () => {
  const grant = vi.spyOn(api, 'vncGrant').mockResolvedValue({ token:'fixture',expires_at:'later',novnc_url:'about:blank' })
  vi.spyOn(api, 'workspaceApplications').mockResolvedValue({workspace:{id:'one',number:1,name:'Research',network:'default',application_name:'vnc-workspace',desired_running:true,runtime_id:'desktop-one',instance_id:'desktop-one',status:'running',runtime_state:'running',endpoint_ready:true,endpoint_bound:true,last_error:null,created_at:'now',updated_at:'now'},applications:[],runtimes:[],launch:{available:false,code:'pending',reason:'Controller support pending'},membership:{source:'recorded_launch_parameters',authoritative:false},state_source:'recorded'} as import('../api').WorkspaceApplications)
  const view = render(<MemoryRouter initialEntries={['/vnc/one']}><VncSessionProvider><Routes><Route path="/vnc/:workspaceId" element={<VncPage />} /></Routes><PersistentVncSessions /></VncSessionProvider></MemoryRouter>)
  await waitFor(() => expect(view.container.querySelectorAll('iframe')).toHaveLength(1))
  const frame = view.container.querySelector('iframe')
  fireEvent.click(screen.getByRole('button',{name:'Applications'}))
  await screen.findByText('Workspace: Research')
  fireEvent.click(screen.getByRole('button',{name:'Close application panel'}))
  expect(view.container.querySelector('iframe')).toBe(frame)
  expect(grant).toHaveBeenCalledTimes(1)
})
