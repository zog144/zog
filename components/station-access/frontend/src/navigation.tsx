import {LicenseLink} from './LicenseLink'
import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth/AuthProvider'

export function Navigation() {
  const { pathname } = useLocation()
  const { user, logout } = useAuth()
  const header = useRef<HTMLElement>(null)
  const [workspaceName, setWorkspaceName] = useState('Workspace')
  useLayoutEffect(() => {
    const measure = () => document.documentElement.style.setProperty('--navigation-height', `${header.current?.getBoundingClientRect().height ?? 56}px`)
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const observer = new ResizeObserver(measure)
    if (header.current) observer.observe(header.current)
    return () => observer.disconnect()
  }, [])
  useEffect(() => {
    let active = true
    setWorkspaceName('Workspace')
    const provenance = pathname.match(/^\/workspaces\/([^/]+)\/provenance$/)
    const workspaceId = pathname.startsWith('/vnc/') ? pathname.split('/')[2] : provenance?.[1]
    if (workspaceId) api.workspace(workspaceId).then(result => { if (active) setWorkspaceName(result.workspace.name) }).catch(() => undefined)
    return () => { active = false }
  }, [pathname])
  const crumbs: { name: string; path: string }[] = [{ name: 'Home', path: '/' }]
  const workspaceProvenance = pathname.match(/^\/workspaces\/([^/]+)\/provenance$/)
  if (pathname === '/workspaces' || pathname.startsWith('/vnc/') || workspaceProvenance) {
    crumbs.push({ name: 'Workspaces', path: '/workspaces' })
    if (pathname.startsWith('/vnc/')) crumbs.push({ name: workspaceName, path: pathname })
    if (workspaceProvenance) crumbs.push({ name: `${workspaceName} provenance`, path: pathname })
  } else if (pathname !== '/') {
    crumbs.push({ name: 'Administration', path: '/administration' })
    const section = pathname.split('/')[1]
    const names: Record<string, string> = { users: 'Users', archives: 'Archives', hosts: 'Hosts', 'host-identities': 'Host identities', applications: 'Applications & logs', runtimes: 'Runtime history', 'build-jobs': 'Build logs', networks: 'Networks', setup: 'Setup readiness', clouds: 'Cloud credentials', registries: 'Registries', deployments: 'Deployments' }
    if (names[section]) crumbs.push({ name: names[section], path: `/${section}` })
    if (pathname.split('/')[2]) crumbs.push({ name: section === 'hosts' ? 'Host details' : decodeURIComponent(pathname.split('/')[2]), path: pathname })
  }
  return <header ref={header} className="station-navigation">
    <nav aria-label="Breadcrumb"><ol>{crumbs.map((crumb, index) => <li key={crumb.path}>
      {index > 0 && <span className="breadcrumb-separator" aria-hidden="true">→</span>}
      {index === crumbs.length - 1 ? <span aria-current="page">{crumb.name}</span> : <Link to={crumb.path}>{crumb.name}</Link>}
    </li>)}</ol></nav>
    <div className="account-controls"><LicenseLink /><span>{user?.username}</span><button onClick={logout}>Sign out</button></div>
  </header>
}
