import { useEffect, useState } from 'react'
import { api, type Application, type Runtime } from '../api'
import { Link } from 'react-router-dom'
import { ApplicationSourceLicense } from '../provenance/SoftwareProvenance'

export function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([])
  const [error, setError] = useState('')
  const [runtimes, setRuntimes] = useState<Runtime[]>([])
  useEffect(() => { api.applications().then(r => setApplications(r.applications)).catch(e => setError(String(e))) }, [])
  useEffect(() => { api.runtimes().then(r => setRuntimes(r.runtimes)).catch(e => setError(String(e))) }, [])
  return (
    <section>
      <h1>Applications</h1>
      {error && <p className="error">{error}</p>}
      <div className="cards">
        {applications.map(app => (
          <article className="card" key={app.name}>
            <h2>{app.name}</h2>
            {runtimes.filter(runtime => runtime.application_name === app.name).map(runtime => (
              <p key={runtime.runtime_id}><Link to={`/runtimes/${encodeURIComponent(runtime.runtime_id)}`}>View logs · {runtime.instance_id}</Link> <span>{runtime.state}</span></p>
            ))}
            {!runtimes.some(runtime => runtime.application_name === app.name) && <p>No recorded runtimes yet.</p>}
            <p>{app.description ?? 'No description'}</p>
            <small>{app.multi_instance ? 'Multiple runtimes allowed' : 'Single runtime'} · {app.start_policy ?? 'no policy'}</small>
            <div className="provenance-actions"><ApplicationSourceLicense application={app} /></div>
          </article>
        ))}
      </div>
    </section>
  )
}
