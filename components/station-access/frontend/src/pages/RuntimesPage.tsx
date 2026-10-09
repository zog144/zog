import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, type Runtime } from '../api'

export function RuntimesPage() {
  const [runtimes, setRuntimes] = useState<Runtime[]>([])
  const [error, setError] = useState('')
  useEffect(() => { api.runtimes().then(r => setRuntimes(r.runtimes)).catch(e => setError(String(e))) }, [])
  return <section><h1>Runtimes</h1>{error && <p className="error">{error}</p>}<div className="cards">{runtimes.map(runtime => <Link className="card link-card" to={`/runtimes/${encodeURIComponent(runtime.runtime_id)}`} key={runtime.runtime_id}><h2>{runtime.application_name}</h2><p>{runtime.runtime_id}</p><small>{runtime.state}</small></Link>)}</div></section>
}
