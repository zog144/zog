import type { HostInventory, RegistryHost } from '../api'

export function ageSeconds(value: string | null, now: number): number | null {
  if (!value) return null
  const stamp = Date.parse(value)
  return Number.isFinite(stamp) ? Math.max(0, (now - stamp) / 1000) : null
}
export function lastSeen(value: string | null, now: number): string {
  const age = ageSeconds(value, now)
  if (age === null) return 'Never reported'
  const seconds = Math.floor(age)
  const [count, unit] = seconds < 60 ? [seconds, 'second'] : seconds < 3600 ? [Math.floor(seconds / 60), 'minute'] : seconds < 86400 ? [Math.floor(seconds / 3600), 'hour'] : [Math.floor(seconds / 86400), 'day']
  return `Seen ${count} ${unit}${count === 1 ? '' : 's'} ago`
}
export function currentHost(host: RegistryHost, now: number): RegistryHost {
  const heartbeatAge = ageSeconds(host.last_received, now)
  const awsAge = ageSeconds(host.aws_checked_at, now)
  const fresh = host.aws_fresh && awsAge !== null && awsAge <= 600
  const roleAge=ageSeconds(host.mirror_role?.observed_at || null,now)
  const roleStale=roleAge===null || roleAge>180
  return {...host,
    mirror_role:host.mirror_role && roleStale ? {...host.mirror_role,ready:false,state:host.mirror_role.selected?'assigned':host.mirror_role.state} : host.mirror_role,
    heartbeat: heartbeatAge === null ? 'never' : heartbeatAge <= 180 ? 'recent' : 'overdue',
    aws_fresh: fresh, aws_state: fresh ? host.aws_state : 'unknown',
    tag_status: fresh ? host.tag_status : 'unknown',
    address_stale: host.address_stale || (host.address_source === 'aws' ? !fresh : heartbeatAge === null || heartbeatAge > 180),
  }
}
export function currentInventory(inventory: HostInventory, now: number): HostInventory {
  const regional = inventory.scans.filter(scan => scan.scope !== 'region-discovery')
  const recent = (stamp: string | null) => { const age = ageSeconds(stamp, now); return age !== null && age <= 600 }
  let status = inventory.inventory_status
  if (!regional.some(scan => recent(scan.last_success))) status = 'unavailable'
  else if (inventory.scans.some(scan => !recent(scan.last_success) || scan.error)) status = 'partial'
  return {...inventory, inventory_status: status, hosts: inventory.hosts.map(host => currentHost(host, now))}
}
