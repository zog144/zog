import {UsersPage} from './pages/UsersPage'
import { ArchivesPage } from './pages/ArchivesPage'
import { GenerationPage } from './pages/GenerationPage'
import { CloudsPage } from './pages/CloudsPage'
import { RegistriesPage, DeploymentsPage } from './pages/SetupPages'
import { ReadinessPage } from './pages/ReadinessPage'
import { Navigation } from './navigation'
import { AdministrationPage, NetworksPage } from './pages/AdministrationPage'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth/AuthProvider'
import { VncSessionProvider } from './vnc/VncSessionProvider'
import { PersistentVncSessions } from './vnc/PersistentVncSessions'
import { ApplicationsPage } from './pages/ApplicationsPage'
import { LoginPage } from './pages/LoginPage'
import { RuntimesPage } from './pages/RuntimesPage'
import { RuntimePage } from './pages/RuntimePage'
import { VncPage } from './pages/VncPage'
import { DashboardPage } from './pages/DashboardPage'
import { BuildJobsPage, BuildJobPage } from './pages/BuildJobsPage'
import { IdentitiesPage } from './pages/IdentitiesPage'
import { HostDetailPage } from './pages/HostDetailPage'
import { HostsPage } from './pages/HostsPage'
import { WorkspacesPage } from './pages/WorkspacesPage'
import { WorkspaceProvenancePage } from './pages/WorkspaceProvenancePage'

export function App() {
  const { loading, user } = useAuth()
  if (loading) return <main>Loading…</main>
  if (!user) return <LoginPage />
  return (
    <BrowserRouter>
      <VncSessionProvider>
        <div className="shell">
          <Navigation />
          <main className="content">
            <Routes>
              <Route path="/" element={<DashboardPage />} />
              <Route path="/archives" element={user.is_superuser ? <ArchivesPage /> : <Navigate to="/administration" replace />} />
              <Route path="/generations/:generation" element={user.is_superuser ? <GenerationPage /> : <Navigate to="/administration" replace />} />
              <Route path="/users" element={<UsersPage />} />
              <Route path="/administration" element={<AdministrationPage />} />
              <Route path="/networks" element={user.is_superuser ? <NetworksPage /> : <Navigate to="/administration" replace />} />
              <Route path="/setup" element={<ReadinessPage />} />
              <Route path="/clouds" element={<CloudsPage />} />
              <Route path="/registries" element={<RegistriesPage />} />
              <Route path="/deployments" element={<DeploymentsPage />} />
              <Route path="/hosts" element={<HostsPage />} />
              <Route path="/hosts/:hostId" element={<HostDetailPage />} />
              <Route path="/host-identities" element={<IdentitiesPage />} />
              <Route path="/build-jobs" element={<BuildJobsPage />} />
              <Route path="/build-jobs/:jobId" element={<BuildJobPage />} />
              <Route path="/workspaces" element={<WorkspacesPage />} />
              <Route path="/workspaces/:workspaceId/provenance" element={<WorkspaceProvenancePage />} />
              <Route path="/applications" element={<ApplicationsPage />} />
              <Route path="/runtimes" element={<RuntimesPage />} />
              <Route path="/runtimes/:runtimeId" element={<RuntimePage />} />
              <Route path="/vnc/:workspaceId" element={<VncPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </main>
          <PersistentVncSessions />
        </div>
      </VncSessionProvider>
    </BrowserRouter>
  )
}
