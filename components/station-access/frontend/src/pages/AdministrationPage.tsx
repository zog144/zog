import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
export function AdministrationPage() {
  const { user } = useAuth()
  return <section><h1>Administration</h1><div className="cards">
    {user?.is_superuser && <><Link className="card link-card" to="/users"><h2>Users</h2><p>Accounts, passwords and administrator access.</p></Link><Link className="card link-card" to="/hosts"><h2>Hosts</h2><p>Inventory, enrollment and host settings.</p></Link>
    <Link className="card link-card" to="/archives"><h2>Archives</h2><p>Mirror catalogs, availability and storage observations.</p></Link>
    <Link className="card link-card" to="/host-identities"><h2>Host identities</h2><p>Fingerprint approval and host permissions.</p></Link></>}
    <Link className="card link-card" to="/applications"><h2>Applications & logs</h2><p>Inspect applications and their output.</p></Link>
    <Link className="card link-card" to="/runtimes"><h2>Runtime history</h2><p>Active and completed executions.</p></Link>
    {user?.is_superuser && <><Link className="card link-card" to="/build-jobs"><h2>Build logs</h2><p>Follow build commands.</p></Link>
    <Link className="card link-card" to="/setup"><h2>Setup readiness</h2><p>Configuration, recent observations and remaining setup steps.</p></Link>
    <Link className="card link-card" to="/clouds"><h2>Cloud credentials</h2><p>AWS credentials and identity checks.</p></Link>
    <Link className="card link-card" to="/registries"><h2>Registries</h2><p>Domain provider accounts and API credentials.</p></Link>
    <Link className="card link-card" to="/deployments"><h2>Deployments</h2><p>Beacon registry destinations and TLS trust.</p></Link>
    <Link className="card link-card" to="/networks"><h2>Networks</h2><p>Workspace networking · Coming soon</p></Link></>}
  </div></section>
}
export function NetworksPage() {
  return <section><h1>Networks</h1><p>Network management is not available yet.</p><article className="card"><h2>Default — shared host network</h2><p>Every workspace and its applications share the host network. Separate or isolated networks are not supported.</p></article></section>
}
