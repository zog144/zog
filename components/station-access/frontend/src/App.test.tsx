// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { api } from './api'
import { AuthProvider } from './auth/AuthProvider'
import { App } from './App'
afterEach(() => { cleanup(); vi.restoreAllMocks(); window.history.replaceState(null, '', '/') })
it('shows login, signs in, exposes workspace/application/build links and signs out', async () => {
  vi.spyOn(api, 'session').mockResolvedValue({ authenticated: false })
  const login = vi.spyOn(api, 'login').mockResolvedValue({ authenticated: true, user: { id: 1, username: 'station-admin', is_superuser: true } })
  vi.spyOn(api, 'logout').mockResolvedValue({ authenticated: false })
  render(<AuthProvider><App /></AuthProvider>)
  await screen.findByRole('button', { name: 'Sign in' })
  expect(screen.getByRole('link', {name:'Licenses'}).getAttribute('href')).toBe('/licenses/')
  fireEvent.change(screen.getByLabelText('Username'), { target: { value: 'station-admin' } })
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'only-a-component-test-value' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign in' }))
  await screen.findByRole('heading', { name: 'Home' })
  expect(screen.getByRole('link', {name:'Licenses'}).getAttribute('target')).toBe('_blank')
  expect(login).toHaveBeenCalledWith('station-admin', 'only-a-component-test-value')
  expect(screen.getAllByRole('link', { name: /Workspaces/ }).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('link', { name: /Administration/ }))
  await screen.findByRole('heading', { name: 'Administration' })
  expect(screen.getAllByRole('link', { name: /Applications & logs/ }).length).toBeGreaterThan(0)
  expect(screen.getAllByRole('link', { name: /Build logs/ }).length).toBeGreaterThan(0)
  fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
  await screen.findByRole('button', { name: 'Sign in' })
})
it('does not show administrator build links to ordinary users', async () => {
  vi.spyOn(api, 'session').mockResolvedValue({ authenticated: true, user: { id: 2, username: 'reader', is_superuser: false } })
  render(<AuthProvider><App /></AuthProvider>)
  await screen.findByRole('heading', { name: 'Home' })
  fireEvent.click(screen.getByRole('link', { name: /Administration/ }))
  await screen.findByRole('heading', { name: 'Administration' })
  expect(screen.queryByRole('link', { name: /Build logs/ })).toBeNull()
  expect(screen.getByRole('link', { name: /Applications & logs/ })).toBeTruthy()
})

it('navigates to Networks with clickable breadcrumb ancestors', async () => {
  vi.spyOn(api, 'session').mockResolvedValue({ authenticated: true, user: { id: 1, username: 'admin', is_superuser: true } })
  render(<AuthProvider><App /></AuthProvider>)
  fireEvent.click(await screen.findByRole('link', { name: /Administration/ }))
  fireEvent.click(await screen.findByRole('link', { name: /Networks/ }))
  await screen.findByRole('heading', { name: 'Networks' })
  const breadcrumb = screen.getByRole('navigation', { name: 'Breadcrumb' })
  expect(breadcrumb.textContent).toBe('Home→Administration→Networks')
  fireEvent.click(screen.getByRole('link', { name: 'Home' }))
  await screen.findByRole('heading', { name: 'Home' })
})

it('shows the workspace name on direct viewer navigation', async () => {
  window.history.replaceState(null, '', '/vnc/desk-one')
  vi.spyOn(api, 'session').mockResolvedValue({ authenticated:true, user:{id:1,username:'admin',is_superuser:true} })
  vi.spyOn(api, 'workspace').mockResolvedValue({workspace:{name:'Research'} as import('./api').Workspace})
  vi.spyOn(api, 'vncGrant').mockRejectedValue(new Error('Display not available in this test'))
  render(<AuthProvider><App /></AuthProvider>)
  await screen.findByText('Research')
  expect(screen.getByRole('navigation',{name:'Breadcrumb'}).textContent).toBe('Home→Workspaces→Research')
})


it('shows the workspace provenance breadcrumb on direct navigation', async () => {
  window.history.replaceState(null, '', '/workspaces/desk-one/provenance')
  vi.spyOn(api, 'session').mockResolvedValue({ authenticated:true, user:{id:1,username:'admin',is_superuser:true} })
  vi.spyOn(api, 'workspace').mockResolvedValue({workspace:{name:'Research'} as import('./api').Workspace})
  vi.spyOn(api, 'workspaceProvenance').mockResolvedValue({
    schema:1, basis:'immutable-runtime-history', administrator_generation_details:true,
    workspace:{id:'desk-one',number:1,name:'Research'}, runtimes:[],
  })
  render(<AuthProvider><App /></AuthProvider>)
  await screen.findByRole('heading',{name:'Research · Provenance'})
  await screen.findByText('Research provenance')
  expect(screen.getByRole('navigation',{name:'Breadcrumb'}).textContent).toBe('Home→Workspaces→Research provenance')
})
