import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type Runtime } from '../api'
import { LogViewer } from '../logs/LogViewer'

export function RuntimePage() {
  const { runtimeId = '' } = useParams()
  const [runtime, setRuntime] = useState<Runtime | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    setRuntime(null); setError('')
    api.runtime(runtimeId).then(r => { if (active) setRuntime(r.runtime) }).catch(e => { if (active) setError(String(e)) })
    return () => { active = false }
  }, [runtimeId])
  if (error) return <p className="error">{error}</p>
  if (!runtime) return <p>Loading…</p>
  return (
    <section>
      <h1>{runtime.application_name}</h1>
      <dl>
        <dt>Runtime</dt><dd>{runtime.runtime_id}</dd>
        <dt>Instance</dt><dd>{runtime.instance_id}</dd>
        <dt>State</dt><dd>{runtime.state}</dd>
        <dt>Generation</dt><dd>{runtime.generation ?? '—'}</dd>
      </dl>
      {runtime.fault && <pre className="fault">{runtime.fault}</pre>}
      <LogViewer key={runtime.runtime_id} runtime={runtime} />
      <h2>Programs</h2>
      {runtime.programs.map(program => (
        <article className="program" key={program.service_name}>
          <strong>{program.name}</strong>
          <span>{program.state}</span>
          <code>{program.service_name}</code>
        </article>
      ))}
    </section>
  )
}
