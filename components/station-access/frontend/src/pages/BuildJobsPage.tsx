import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, type BuildJob, type Runtime } from '../api'
import { LogViewer } from '../logs/LogViewer'
export function BuildJobsPage() {
  const [jobs, setJobs] = useState<BuildJob[]>([])
  const [after, setAfter] = useState<string | null>(null)
  const [more, setMore] = useState(false)
  const [error, setError] = useState('')
  const load = async (append = false) => {
    setError('')
    try {
      const page = await api.buildJobs(append ? after ?? undefined : undefined)
      setJobs(current => append ? [...current.filter(j => !page.jobs.some(n => n.job_id === j.job_id)), ...page.jobs] : page.jobs)
      setAfter(page.next_after); setMore(page.has_more)
    } catch (reason) { setError(String(reason)) }
  }
  useEffect(() => { void load() }, [])
  return <section><h1>Build jobs</h1><p>Recorded build commands and their individual journal streams. Administrator access.</p>
    <button onClick={() => void load()}>Refresh from beginning</button>{error && <p role="alert" className="error">{error}</p>}
    {!jobs.length && !error && <p>No recorded build jobs yet.</p>}
    <div className="cards">{jobs.map(job => <Link className="card link-card" key={job.job_id} to={`/build-jobs/${encodeURIComponent(job.job_id)}`}><h2>{job.job_id}</h2><p>{job.state} · {job.outcome ?? 'No outcome yet'}</p><p>Exit code: {job.exit_code ?? '—'}</p><span>View command logs →</span></Link>)}</div>
    {more && <button onClick={() => void load(true)}>Load more</button>}
  </section>
}
export function BuildJobPage() {
  const { jobId = '' } = useParams()
  const [job, setJob] = useState<BuildJob | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout>
    setJob(null); setError('')
    const poll = async () => {
      if (!document.hidden) {
        try { const result = await api.buildJob(jobId); if (active) { setJob(result.job); setError('') } }
        catch (reason) { if (active) setError(String(reason)) }
      }
      if (active) timer = setTimeout(poll, 5000)
    }
    void poll()
    return () => { active = false; clearTimeout(timer) }
  }, [jobId])
  const readPage = useCallback((_program: string, cursor: string | null, signal: AbortSignal) => api.buildLogs(jobId, cursor, signal), [jobId])
  if (!job) return <p>{error || 'Loading build job…'}</p>
  const runtime: Runtime = { runtime_id: jobId, application_name: 'build-job', instance_id: jobId, state: job.state, generation: null, created_at: null, completed_at: null, request_id: null, fault: null,
    programs: [{ name: 'build-command', service_name: '', state: job.state, invocation_id: job.invocation_id ?? null, command: [], main_pid: null, control_group: null, result: job.outcome }] }
  return <section><Link to="/build-jobs">← Build jobs</Link><h1>{jobId}</h1><p>{job.state} · {job.outcome ?? 'Pending outcome'} · Exit {job.exit_code ?? '—'}</p>
    {error && <p className="error">{error}</p>}<LogViewer key={jobId} runtime={runtime} readPage={readPage} title="Build command logs" /></section>
}
