import { Link } from 'react-router-dom'
export function DashboardPage() {
  return <section><h1>Home</h1><div className="cards home-menu">
    <Link className="card link-card" to="/workspaces"><h2>Workspaces</h2><p>Your desktops and the applications you use in them.</p><span>Choose a workspace →</span></Link>
    <Link className="card link-card" to="/administration"><h2>Administration</h2><p>Manage your station and inspect applications and logs.</p><span>Open administration →</span></Link>
  </div></section>
}
