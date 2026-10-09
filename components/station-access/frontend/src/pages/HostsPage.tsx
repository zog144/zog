import { useEffect, useState } from 'react'
import { api, type RegistryHost, type HostInventory } from '../api'
import { currentInventory, lastSeen } from './hostFreshness'
import { HostDns } from './HostDns'
import { HostOperations } from './HostOperations'
import { useAuth } from '../auth/AuthProvider'

const time = (value: string | null) => value ? new Date(value).toLocaleString() : 'Never'
function HostCard({host, refresh, now, suffix, writer}: {host: RegistryHost; refresh: () => void; now: number; suffix: string; writer?:string}) {
  const [label, setLabel] = useState(host.label)
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  useEffect(() => { if (!editing) setLabel(host.label) }, [host.label, editing])
  const address = host.public_address
  async function save() {
    setSaving(true); setError('')
    try { await api.hostLabel(host.id,label); setEditing(false); refresh() }
    catch (e) { setError(String(e)) }
    finally { setSaving(false) }
  }
  return <article className="host-pane"><div className="host-pane-heading">{editing ? <form onSubmit={e => {e.preventDefault(); void save()}}>
    <input aria-label="Host label" maxLength={200} value={label} onChange={e => setLabel(e.target.value)} />
    <button disabled={saving}>Save</button><button type="button" onClick={() => setEditing(false)}>Cancel</button>
  </form> : <><strong>{host.label || 'Unlabelled host'}</strong> <button disabled={!!host.archived_at} onClick={() => setEditing(true)}>Edit</button></>}
    {error && <p role="alert">{error}</p>}
    <div>{host.instance_id || host.id}</div><small>{host.region || 'Local / other host'} {host.aws.instance_type}</small>
    <a href={`/hosts/${host.id}`}>Host details and removal</a>
    {host.archived_at && <p>Archived record — inventory observations retained</p>}
    {host.provider==='generic' && !host.last_received && <p>Non-cloud record with no heartbeat. Review if unexpected; its UUID is a registry identifier, not an AWS instance ID.</p>}
    {!!host.duplicate_candidates?.length && <p>Possible duplicate — review alongside {host.duplicate_candidates.map(h=>h.label || h.id).join(", ")}. Matching hints only.</p>}
    <details><summary>Host details & tags</summary>
      <dl className="host-details">
        <dt>Registry ID</dt><dd>{host.id}</dd>
        <dt>Account</dt><dd>{host.account_id || 'Not AWS'}</dd>
        <dt>Workspace</dt><dd>{host.workspace_id || 'Not assigned'}</dd>
        <dt>First seen</dt><dd>{time(host.first_seen)}</dd>
        <dt>Last heartbeat</dt><dd>{time(host.last_received)}</dd>
        <dt>Enrollment</dt><dd>{host.enrolled ? 'Enrolled' : 'Not enrolled / revoked'}</dd>
        <dt>Reported hostname</dt><dd>{host.report.hostname || 'Not reported'}</dd>
        <dt>Daemon version</dt><dd>{host.report.daemon_version || 'Not reported'}</dd>
        <dt>Boot identity</dt><dd><code>{host.report.boot_id || 'Not reported'}</code></dd>
        <dt>Reported public DNS</dt><dd>{host.report.public_dns || 'Not reported'}</dd>
        <dt>Reported public IP</dt><dd>{host.report.public_ip || 'Not reported'}</dd>
        <dt>Reported private IP</dt><dd>{host.report.private_ip || 'Not reported'}</dd>
      </dl>
      {host.last_received && <p>Reported details are from the last heartbeat{host.heartbeat === 'overdue' ? ' and are overdue' : ''}.</p>}
      {host.provider === 'aws' && <><h3>AWS observation</h3><p>{host.aws_fresh ? 'Current' : 'Unavailable or stale'} · {time(host.aws_checked_at)}</p>
        <dl className="host-details"><dt>Public DNS</dt><dd>{host.aws.public_dns || 'Not observed'}</dd><dt>Public IP</dt><dd>{host.aws.public_ip || 'Not observed'}</dd><dt>Private IP</dt><dd>{host.aws.private_ip || 'Not observed'}</dd></dl>
        {host.tag_status === 'unknown' && <p>Current AWS tags unknown. Any tags below are from the last observation.</p>}<pre>{JSON.stringify(host.aws.tags || {}, null, 2)}</pre></>}
    </details></div>
    <section className="host-pane-field">{host.provider === 'aws' ? host.tag_status === 'unknown' ? 'Tags unknown' : host.tag_status === 'zog' ? 'Zog-tagged' : 'Untagged for Zog' : 'Not AWS'}</section>
    <section className="host-pane-field"><code>{address || (host.address_source === 'aws' ? 'No public address in AWS observation' : 'Public address not reported')}</code>{address && <button onClick={() => navigator.clipboard.writeText(address).catch(() => setError('Copy failed; select the address to copy it.'))}>Copy</button>}
      {address && <div>{host.address_source === 'heartbeat' ? 'Reported by daemon' : 'Observed by AWS'}{host.address_stale ? ' · stale; may have changed' : ''}</div>}<HostDns host={host} writer={writer} suffix={suffix} refresh={refresh}/></section>
    <section className="host-pane-field"><strong>{host.provider === 'aws' ? host.aws_state : 'Not AWS'}</strong>
      {!host.aws_fresh && host.aws.state && <div>Last observed: {host.aws.state}</div>}
      {host.aws_missing_since && <div>Missing from latest inventory</div>}
      <small>{host.aws_checked_at ? time(host.aws_checked_at) : "AWS has not been observed"}</small>
      {host.aws.state === 'stopped' && !!host.aws.volume_ids?.length && <p>Retained EBS storage</p>}</section>
    <section className="host-pane-field"><strong className={`host-status ${host.heartbeat}`}>{host.heartbeat === 'never' ? 'Never reported' : host.heartbeat === 'recent' ? 'Reporting' : 'Overdue'}</strong>{host.last_received && <div title={time(host.last_received)}>{lastSeen(host.last_received, now)}</div>}<small>{time(host.last_received)}</small>
      {host.aws_state === 'running' && host.heartbeat !== 'recent' && <p>Running without a recent heartbeat</p>}</section>{!host.archived_at && <HostOperations host={host} refresh={refresh}/>}</article>
}
export function HostsPage() {
  const {user} = useAuth()
  const [snapshot, setSnapshot] = useState<{value: HostInventory; received: number} | null>(null)
  const [clock, setClock] = useState(() => performance.now())
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [records,setRecords]=useState('active')
  const [heartbeatFilter, setHeartbeatFilter] = useState('all')
  const [sort, setSort] = useState('label')
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const timer = setInterval(() => setClock(performance.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => {
    if (!user?.is_superuser) return
    let active = true
    let timeout: ReturnType<typeof setTimeout>
    const load = async () => {
      try { const value = await api.hosts(); if (active) {const received = performance.now();setSnapshot({value,received});setClock(received);setError('')} }
      catch (e) {if (active) setError(String(e))}
      finally {if (active) timeout = setTimeout(load,15000)}
    }
    void load()
    return () => {active=false;clearTimeout(timeout)}
  }, [user?.is_superuser, revision])
  if (!user?.is_superuser) return <p>Administrator access required.</p>
  const now = snapshot ? Date.parse(snapshot.value.server_time) + Math.max(0, clock - snapshot.received) : 0
  const inventory = snapshot ? currentInventory(snapshot.value, now) : null
  const hosts = (inventory?.hosts || []).filter(host =>
    (records==='all' || (records==='archived' ? !!host.archived_at : !host.archived_at)) &&
    (filter === 'all' || (filter === 'zog' ? host.tag_status === 'zog' : filter === 'unknown-tags' ? host.provider === 'aws' && host.tag_status === 'unknown' : filter === 'running' ? host.aws_state === 'running' : host.provider === 'aws' && host.tag_status === 'untagged')) &&
    (heartbeatFilter === 'all' || host.heartbeat === heartbeatFilter) &&
    JSON.stringify([host.label,host.instance_id,host.region,host.public_address,host.report.hostname,host.dns?.name,host.report.public_ip,host.report.private_ip,host.aws.private_ip]).toLowerCase().includes(query.toLowerCase())
  ).sort((a,b) => (sort === 'label' ? a.label.localeCompare(b.label) : sort === 'state' ? a.aws_state.localeCompare(b.aws_state) : (b.last_received || '').localeCompare(a.last_received || '')) || a.id.localeCompare(b.id))
  return <section className="host-registry"><h1>Hosts</h1><p>Enrolled hosts and available AWS inventory. Heartbeats arrive every minute.</p>
    {error && <p role="alert">Refresh failed; displayed information may be stale. {error}</p>}
    {!inventory && !error && <p>Loading inventory…</p>}
    {inventory && <><div className="host-counts" aria-label="Host summary">
      <div className="card"><strong>{inventory.hosts.length}</strong><span>Known records including archived</span></div>
      <div className="card"><strong>{inventory.hosts.filter(h => h.heartbeat === 'recent').length}</strong><span>Reporting</span></div>
      <div className="card"><strong>{inventory.hosts.filter(h => h.heartbeat === 'overdue').length}</strong><span>Overdue</span></div>
      <div className="card"><strong>{inventory.hosts.filter(h => h.heartbeat === 'never').length}</strong><span>Never reported</span></div>
      <div className="card">{inventory.inventory_status === 'unavailable' ? <strong>AWS counts unavailable</strong> : <><strong>{inventory.hosts.filter(h => h.aws_state === 'running').length} AWS running observed</strong><span>{inventory.hosts.filter(h => h.aws_state === 'stopped').length} stopped observed{inventory.inventory_status === 'partial' && ' · incomplete inventory'}</span></>}</div>
    </div><p>Reporting means a heartbeat within 3 minutes; overdue does not prove a host is stopped. Never reported includes hosts found only by AWS inventory.</p>
    <p>Last refresh: {time(inventory.server_time)} · refreshes every 15 seconds.</p></>}

    {inventory && inventory.inventory_status !== 'complete' && <p role="status">AWS inventory is {inventory.inventory_status}. Heartbeats remain available; missing inventory does not mean zero running instances.</p>}
    {inventory?.scans.some(scan => ['UnauthorizedOperation','AccessDenied','AccessDeniedException'].includes(scan.error)) && <p role="alert">AWS inventory access denied. The command center’s EC2 role needs ec2:DescribeRegions and ec2:DescribeInstances. An AWS administrator must grant the read-only inventory policy; enrolling hosts does not grant these permissions.</p>}
    {inventory?.dns?.configured && <p>Managed DNS: <strong>{inventory.dns.suffix}</strong>. {inventory.dns.writer === 'shared' ? 'Review and confirm names to add enrolled hosts.' : inventory.dns.auto_publish_enrolled ? 'Verified enrolled hosts receive a stable name automatically.' : 'Assign names to opt in.'} Reconciliation runs on the controller schedule; display-label changes do not rename DNS.</p>}
    {inventory?.dns?.error && <p role="alert">{inventory.dns.error}</p>}
    <p>Stopped hosts can retain billable storage. AWS counts include archived records. This is an inventory, not a billing total.</p>
    <div className="host-controls"><label>Search <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Label, hostname, IP, instance or region" /></label>{' '}
    <label>Records <select value={records} onChange={e=>setRecords(e.target.value)}><option value="active">Active records</option><option value="archived">Archived records</option><option value="all">All records including archived</option></select></label>
    <label>Show <select value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All hosts</option><option value="zog">Zog-tagged</option><option value="untagged">AWS confirmed without Zog tags</option><option value="unknown-tags">AWS tags unknown</option><option value="running">AWS running</option></select></label>{' '}
    <label>Heartbeat <select value={heartbeatFilter} onChange={e => setHeartbeatFilter(e.target.value)}><option value="all">All heartbeats</option><option value="recent">Reporting recently</option><option value="overdue">Overdue</option><option value="never">Never reported</option></select></label>{' '}
    <label>Sort <select value={sort} onChange={e => setSort(e.target.value)}><option value="label">Label</option><option value="state">AWS state</option><option value="heartbeat">Last heartbeat</option></select></label>{' '}
    <button onClick={() => setRevision(value => value+1)}>Refresh</button></div>
    {inventory && <p>{hosts.length} of {inventory.hosts.length} hosts shown</p>}
    <div className="host-pane-grid">{hosts.map(host => <HostCard key={host.id} host={host} now={now} writer={inventory?.dns?.writer} suffix={inventory?.dns?.configured ? inventory.dns.suffix : ''} refresh={() => setRevision(value => value+1)} />)}</div>
    {inventory && !hosts.length && <p>No hosts match.</p>}
    <h2>Inventory coverage</h2>
    {inventory && <p>AWS inventory: <strong>{inventory.inventory_status}</strong>. Scans cover all enabled regions, including instances without Zog tags, and retry approximately every two minutes.</p>}
    {inventory && inventory.inventory_status !== 'complete' && !inventory?.scans.some(scan => ['UnauthorizedOperation','AccessDenied','AccessDeniedException'].includes(scan.error)) && <p>If coverage stays incomplete, check the command center’s AWS credentials, network connectivity, and inventory service. Successful observations are retained, but expire after 10 minutes.</p>}
    {!inventory?.scans.length && <p>No AWS inventory scan has completed yet.</p>}
    <ul>{inventory?.scans.map(scan => <li key={scan.scope}><strong>{scan.scope}</strong>: {scan.error ? `Failed: ${scan.error}` : !scan.last_success ? 'Pending' : now-new Date(scan.last_success).getTime()>600000 ? 'Stale' : 'OK'} · last success {time(scan.last_success)} {scan.scope !== 'region-discovery' && <>· {scan.last_success ? `${scan.instance_count} instances at last success` : "Instance count unavailable"}</>}</li>)}</ul>
  </section>
}
