import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type LogEntry, type LogPage, type Runtime } from '../api'
import { appendEntries, entryText, maximumEntries, priorities } from './buffer'

export function LogViewer({ runtime, readPage, title = "Application logs" }: { runtime: Runtime; readPage?: (program: string, cursor: string | null, signal: AbortSignal) => Promise<LogPage>; title?: string }) {
  const [program, setProgram] = useState(runtime.programs[0]?.name ?? '')
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [paused, setPaused] = useState(false)
  const [follow, setFollow] = useState(true)
  const [search, setSearch] = useState('')
  const [priority, setPriority] = useState(7)
  const [error, setError] = useState('')
  const [source, setSource] = useState('')
  const [loading, setLoading] = useState(true)
  const [reload, setReload] = useState(0)
  const [updated, setUpdated] = useState('')
  const cursor = useRef<string | null>(null)
  const viewport = useRef<HTMLDivElement>(null)
  // Filter changes define a new cursor scope. Pause preserves the current buffer and cursor.
  useEffect(() => {
    cursor.current = null; setEntries([]); setError(''); setSource(''); setUpdated(''); setLoading(true)
  }, [runtime.runtime_id, program, reload])
  useEffect(() => {
    if (paused) return
    let active = true
    let timer: ReturnType<typeof setTimeout>
    const controller = new AbortController()
    const poll = async () => {
      if (!active) return
      if (document.hidden) { timer = setTimeout(poll, 2000); return }
      let delay = 2000
      try {
        const page = readPage ? await readPage(program, cursor.current, controller.signal) : await api.logs(runtime.runtime_id, program, cursor.current, controller.signal)
        if (!active) return
        setEntries(current => appendEntries(current, page.entries))
        cursor.current = page.next_cursor
        setSource(page.source); setError(''); setLoading(false)
        setUpdated(new Date().toLocaleTimeString())
        if (page.has_more) delay = 100
      } catch (reason) {
        if (!active) return
        setError(reason instanceof Error ? reason.message : String(reason)); setLoading(false)
        // Explicit reload resumes errors; do not hammer a missing adapter or expired cursor.
        return
      }
      if (active) timer = setTimeout(poll, delay)
    }
    void poll()
    return () => { active = false; clearTimeout(timer); controller.abort() }
  }, [runtime.runtime_id, program, paused, reload, readPage])
  const visible = useMemo(() => entries.filter(entry => entry.priority <= priority &&
    entry.message.toLocaleLowerCase().includes(search.toLocaleLowerCase())), [entries, priority, search])
  useEffect(() => {
    if (follow && viewport.current) viewport.current.scrollTop = viewport.current.scrollHeight
  }, [visible, follow])
  const download = () => {
    const blob = new Blob([visible.map(entryText).join('\n')], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = url; link.download = 'application-logs.txt'; link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="log-viewer" aria-label={title}>
    <div className="log-heading"><div><h2>{title}</h2><p>Output and errors from this runtime</p></div>
      <span className={`log-status ${error ? 'unavailable' : ''}`}>{error ? 'Unavailable' : paused ? 'Paused' : 'Following'}</span></div>
    {source === 'fixture' && <p className="fixture-notice">Demonstration entries · these are not live journald logs.</p>}
    <div className="log-controls">
      <label>Program<select value={program} onChange={event => setProgram(event.target.value)}>
        {runtime.programs.map(item => <option key={item.name}>{item.name}</option>)}
      </select></label>
      <label>Severity<select value={priority} onChange={event => setPriority(Number(event.target.value))}>
        <option value={7}>All levels</option><option value={6}>Info and above</option><option value={4}>Warnings and errors</option><option value={3}>Errors only</option>
      </select></label>
      <label className="log-search">Search loaded entries<input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Filter messages…" /></label>
      <button onClick={() => setPaused(value => !value)}>{paused ? 'Resume' : 'Pause'}</button>
      <button onClick={() => { setPaused(false); setReload(value => value + 1) }}>Reload recent</button>
    </div>
    {error && <p role="alert" className="error log-error">{error}</p>}
    <div className="log-output" ref={viewport} tabIndex={0} aria-label="Log entries">
      {loading && !entries.length && <p className="log-empty">Loading logs…</p>}
      {!loading && !visible.length && !error && <p className="log-empty">{entries.length ? 'No loaded entries match these filters.' : 'No retained entries for this stream. It may have no output, or journal history may have expired.'}</p>}
      {visible.map(entry => <article key={entry.cursor} className={`log-row priority-${entry.priority}`}>
        <div className="log-meta"><time dateTime={entry.timestamp}>{entry.timestamp}</time><span>{entry.program}</span><span className="log-priority">{priorities[entry.priority]}</span></div>
        <pre>{entry.message}</pre>
      </article>)}
    </div>
    <footer className="log-footer"><span>{visible.length} shown · {entries.length}/{maximumEntries} buffered{updated && ` · Updated ${updated}`}</span>
      <label><input type="checkbox" checked={follow} onChange={event => setFollow(event.target.checked)} /> Follow newest</label>
      <button disabled={!visible.length} onClick={download}>Download visible</button>
    </footer>
  </section>
}
