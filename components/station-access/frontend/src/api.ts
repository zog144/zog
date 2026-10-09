export type SessionUser = { id: number; username: string; is_superuser: boolean }
export type Session = { authenticated: false } | { authenticated: true; user: SessionUser }
export type Application = {
  name: string
  description: string | null
  multi_instance: boolean
  start_policy: string | null
  eligible?: boolean
  reason?: string
  workspace_role?: string | null
  source_license?: { state: 'available'|'unavailable'; reason: string; href?: string }
}
export type Program = {
  name: string
  service_name: string
  state: string
  invocation_id: string | null
  command: string[]
  main_pid: number | null
  control_group: string | null
  result: string | null
}
export type Runtime = {
  runtime_id: string
  application_name: string
  instance_id: string
  state: string
  generation: string | null
  created_at: number | null
  completed_at: number | null
  request_id: string | null
  fault: string | null
  cleanup_pending?: boolean
  programs: Program[]
}
export type Workspace = {
  number: number
  endpoint_ready: boolean
  id: string
  name: string
  application_name: string
  desired_running: boolean
  runtime_id: string | null
  instance_id: string | null
  status: string
  runtime_state: string | null
  network: string
  endpoint_bound: boolean
  last_error: string | null
  created_at: string
  updated_at: string
}
export type WorkspaceGenerationArchive = {
  mirror:string; snapshot:string; collection:string; digest:string; observed_at:string
}
export type WorkspaceProvenanceRuntime = {
  runtime_id:string; application:string; instance_id:string; role:'desktop'|'application'; state:string;
  generation:string|null; created_at:number|null; completed_at:number|null;
  generation_resolution:'resolved'|'unresolved'|'conflict'|'ambiguous'|'unknown';
  generation_digest:string|null; generation_archive:WorkspaceGenerationArchive|null;
  generation_candidate_count:number;
}
export type WorkspaceProvenance = {
  schema:number; basis:'immutable-runtime-history';
  administrator_generation_details:boolean;
  workspace:{id:string;number:number;name:string};
  runtimes:WorkspaceProvenanceRuntime[];
}

export type WorkspaceApplications = {
  workspace: Workspace
  applications: Application[]
  runtimes: Runtime[]
  launch: { available: boolean; code: string; reason: string }
  membership: { source: string; authoritative: boolean; pending_count?: number; cleanup_count?: number }
  launch_actions?: { id: string; application: string; state: string; runtime_id: string | null }[]
  state_source: 'recorded'
}
export type BuildJob = { job_id: string; state: string; outcome: string | null; exit_code: number | null; signal: number | null; process_cleanup_complete: boolean; resources_released: boolean; invocation_id?: string | null }
export type LogEntry = { cursor: string; timestamp: string; program: string; priority: number; message: string; invocation_id: string | null }
export type LogPage = { entries: LogEntry[]; next_cursor: string | null; has_more: boolean; source: 'journald' | 'fixture'; status?: string }
export type VncGrant = { token: string; expires_at: string; novnc_url: string }

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ''
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) {
    headers.set('X-CSRFToken', csrfToken())
    if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
  }
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' })
  const body = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(body.detail ?? body.error ?? `HTTP ${response.status}`)
  return body as T
}

export type HostDnsAssignment = {
  name: string; enabled: boolean; revision: number; desired_action: string; desired_address: string;
  applied_revision: number | null; status: string; record_id: string; observed_address: string;
  last_attempt: string | null; last_success: string | null; last_change: string | null; next_attempt: string | null;
  error_code: string; error: string; last_action: string;
}
export type HostMatchSummary = {id:string;label:string;provider:string;account_id:string;region:string;instance_id:string;archived:boolean}
export type EnrollmentMatch = {status:'existing'|'new'|'conflict';host:HostMatchSummary|null;cloud:Record<string,string>|null;reason:string;candidates:HostMatchSummary[]}
export type HostGenerationSlot = {
  generation:string; root_partuuid:string;
  resolution:'resolved'|'unresolved'|'conflict'|'unknown';
  digest:string|null; candidate_count:number; archive:WorkspaceGenerationArchive|null;
}
export type HostGenerationPreview =
  | {state:'invalid-retained-evidence';received_at:string|null}
  | {
      schema:1;source:'verified-host-install-state-v1';received_at:string|null;
      installation:{installation_id:string;record_id:string;record_schema:number;operation:string};
      selected_slot:'HOST-A'|'HOST-B';booted_slot:'HOST-A'|'HOST-B'|null;
      slots:{'HOST-A':HostGenerationSlot|null;'HOST-B':HostGenerationSlot|null};
      transitional_boot_bundle:{kind:'foreign';provider:string;record_reference:string;record_sha256:string}|null;
    }

export type RemovalPreview = {
 host:HostMatchSummary;archived_at:string|null;archived_by:string;revision:string;can_archive:boolean;blockers:string[];explanation:string;
 identities:{fingerprint:string;status:string;approved_by:string;approved_at:string;revoked_at:string|null}[];
 station_credential:{revision:number;source_fingerprint:string;received_at:string}|null;legacy_credential_active:boolean;
 archive_policy:{operations:string[];collections:string[]}|null;possible_token_expiry:string|null;
 mirror_role:{selected:boolean;endpoint:string;revision:number;acknowledged_revision:number;reported_state:string;runtime_id:string}|null;
 dns:{name:string;enabled:boolean;status:string;record_id:string}[];pending_fingerprints:string[];
 host_generation:HostGenerationPreview|null;
}
export type AdditionalDnsAssignment = HostDnsAssignment & {id:string;binding_id:string;phase:string;prefix:string;provider:string;ttl:number}
export type DnsDestination = {id:string;prefix:string;provider:string}
export type RegistryHost = {
  archived_at?:string|null;archived_by?:string;duplicate_candidates?:HostMatchSummary[];
  station_login?: {available:boolean;username?:string;revision?:number;source_active?:boolean};
  mirror_role?: {selected:boolean;revision:number;endpoint:string;state:string;ready:boolean;reason:string;observed_at?:string|null};
  dns?: HostDnsAssignment | null;
  additional_dns?: AdditionalDnsAssignment[];
  id: string; label: string; provider: string; account_id: string; region: string; instance_id: string;
  workspace_id: string; first_seen: string; heartbeat: string; last_received: string | null; aws_checked_at: string | null;
  tag_status: "zog" | "untagged" | "unknown"; public_address: string; address_source: "aws" | "heartbeat" | "unknown"; address_stale: boolean;
  aws_missing_since: string | null; aws_fresh: boolean; aws_state: string; zog_tagged: boolean; enrolled: boolean;
  report: {daemon_version?: string; boot_id?: string; hostname?: string; public_dns?: string; public_ip?: string; private_ip?: string};
  aws: {state?: string; public_dns?: string; public_ip?: string; private_ip?: string; instance_type?: string; tags?: Record<string,string>; volume_ids?: string[]};
}
export type DnsMembershipReview = {review_id:string;action:"reserve"|"release";name:string;resource_id:string}
export type HostInventory = {dns?: {writer?:string;configured: boolean; suffix: string; auto_publish_enrolled: boolean; error: string}; inventory_status: "complete" | "partial" | "unavailable"; hosts: RegistryHost[]; server_time: string; scans: {scope: string; last_attempt: string | null; last_success: string | null; error: string; instance_count: number}[]}
export type IdentityAdministration = {
  pending: {fingerprint:string; public_key:string; status:string; claimed_host_id:string; claims:Record<string,unknown>; expires_at:string;match:EnrollmentMatch}[];
  identities: {fingerprint:string;host_id:string;status:string;approved_by:string;approved_at:string}[];
  policies: {host_id:string;operations:string[];collections:string[]}[];
  hosts: {id:string;label:string;instance_id:string;legacy_until:string|null}[];
  audit: {id:number;actor:string;action:string;fingerprint:string;created_at:string}[];
}
export const api = {
  workspaceReadiness: (id: string, signal?: AbortSignal) => request<WorkspaceReadiness>(`/api/workspaces/${encodeURIComponent(id)}/readiness/`, { signal }),
  workspacePreflight: (id: string, application: string, signal?: AbortSignal) => request<WorkspacePreflight>(`/api/workspaces/${encodeURIComponent(id)}/readiness/?application=${encodeURIComponent(application)}`, { signal }),
  hostRemovalPreview: (id:string) => request<RemovalPreview>(`/api/hosts/${id}/removal-preview/`),
  hostRemoval: (id:string,action:'archive'|'restore',revision:string,confirmed_host_id:string) => request<{saved:boolean}>(`/api/hosts/${id}/removal/`,{method:'POST',body:JSON.stringify({action,revision,confirmed_host_id})}),
  hostLogin: (id:string,revision:number) => request<{username:string;password:string;revision:number}>(`/api/hosts/${id}/station-login/reveal/`,{method:'POST',body:JSON.stringify({revision})}),
  hostMirror: (id:string,selected:boolean,endpoint:string,revision:number) => request(`/api/hosts/${id}/mirror-role/`,{method:'POST',body:JSON.stringify({selected,endpoint,revision})}),
  identities: () => request<IdentityAdministration>('/api/hosts/identities/'),
  identityDecision: (decision: Record<string,unknown>) => request<{saved:boolean}>('/api/hosts/identities/decision/', {method:'POST',body:JSON.stringify(decision)}),
  hosts: () => request<HostInventory>('/api/hosts/'),
  reviewHostDns: (id:string, action:'reserve'|'release', label?:string) => request<DnsMembershipReview>(`/api/hosts/${id}/dns-membership/`, {method:'POST',body:JSON.stringify({action,...(label === undefined ? {} : {label})})}),
  commitHostDns: (id:string, review_id:string) => request<DnsMembershipReview>(`/api/hosts/${id}/dns-membership/`, {method:'POST',body:JSON.stringify({review_id})}),
  dnsDestinations: () => request<{destinations:DnsDestination[]}>('/api/hosts/dns-destinations/'),
  additionalDns: (host:string,binding:string,action:string,revision?:number,label?:string) => request<{dns:AdditionalDnsAssignment|null}>(`/api/hosts/${host}/dns-destinations/${encodeURIComponent(binding)}/`,{method:'POST',body:JSON.stringify({action,...(revision===undefined?{}:{revision}),...(label===undefined?{}:{label})})}),
  hostDns: (id: string, enabled: boolean, label?: string) => request<{dns: HostDnsAssignment}>(`/api/hosts/${id}/dns/`, {method:'POST',body:JSON.stringify({enabled,...(label === undefined ? {} : {label})})}),
  hostLabel: (id: string, label: string) => request<{saved: boolean}>(`/api/hosts/${id}/label/`, {method:'POST', body:JSON.stringify({label})}),
  buildJobs: (after?: string) => request<{ jobs: BuildJob[]; next_after: string | null; has_more: boolean }>(`/api/build-jobs/${after ? `?after=${encodeURIComponent(after)}` : ''}`),
  buildJob: (jobId: string) => request<{ job: BuildJob }>(`/api/build-jobs/${encodeURIComponent(jobId)}/`),
  buildLogs: (jobId: string, cursor: string | null, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: '50' })
    if (cursor) query.set('cursor', cursor)
    return request<LogPage>(`/api/build-jobs/${encodeURIComponent(jobId)}/logs/?${query}`, { signal })
  },
  session: () => request<Session>('/api/session/'),
  login: (username: string, password: string) => request<Session>('/api/login/', { method: 'POST', body: JSON.stringify({ username, password }) }),
  logout: () => request<Session>('/api/logout/', { method: 'POST' }),
  applications: () => request<{ applications: Application[] }>('/api/applications/'),
  runtimes: () => request<{ runtimes: Runtime[] }>('/api/runtimes/'),
  runtime: (runtimeId: string) => request<{ runtime: Runtime }>(`/api/runtimes/${encodeURIComponent(runtimeId)}/`),
  logs: (runtimeId: string, program: string, cursor: string | null, signal?: AbortSignal) => {
    const query = new URLSearchParams({ limit: '50' })
    if (program) query.set('program', program)
    if (cursor) query.set('cursor', cursor)
    return request<LogPage>(`/api/runtimes/${encodeURIComponent(runtimeId)}/logs/?${query}`, { signal })
  },
  workspaceApplications: (id: string, signal?: AbortSignal) => request<WorkspaceApplications>(`/api/workspaces/${encodeURIComponent(id)}/applications/`, { signal }),
  workspaceProvenance: (id: string, signal?: AbortSignal) => request<WorkspaceProvenance>(`/api/workspaces/${encodeURIComponent(id)}/provenance/`, { signal }),
  cancelWorkspaceLaunch: (workspaceId: string, actionId: string) => request<{ state: string }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/applications/launches/${encodeURIComponent(actionId)}/cancel/`, { method: 'POST', body: JSON.stringify({ confirmed_action_id: actionId }) }),
  launchWorkspaceApplication: (workspaceId: string, application: string, actionId: string) => request<{ action_id: string; runtime: Runtime }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/applications/launch/`, { method: 'POST', body: JSON.stringify({ application, action_id: actionId }) }),
  stopWorkspaceApplication: (workspaceId: string, runtimeId: string) => request<{ runtime: Runtime; stopped: boolean }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/applications/${encodeURIComponent(runtimeId)}/stop/`, { method: 'POST', body: JSON.stringify({ confirmed_runtime_id: runtimeId }) }),
  workspaces: () => request<{ workspaces: Workspace[] }>('/api/workspaces/'),
  workspace: (id: string) => request<{ workspace: Workspace }>(`/api/workspaces/${encodeURIComponent(id)}/`),
  updateWorkspace: (workspace: Workspace, name: string, network: string) => request<{ workspace: Workspace }>(`/api/workspaces/${workspace.id}/update/`, { method: 'POST', body: JSON.stringify({ name, network, revision: workspace.updated_at }) }),
  deleteWorkspace: (workspace: Workspace) => request<{ deleted: boolean }>(`/api/workspaces/${workspace.id}/delete/`, { method: 'POST', body: JSON.stringify({ confirmed_workspace_id: workspace.id, revision: workspace.updated_at }) }),
  createWorkspace: (name: string, network = 'default') => request<{ workspace: Workspace }>('/api/workspaces/create/', { method: 'POST', body: JSON.stringify({ name, network }) }),
  startWorkspace: (workspaceId: string) => request<{ workspace: Workspace; runtime: Runtime }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/start/`, { method: 'POST' }),
  stopWorkspace: (workspaceId: string) => request<{ workspace: Workspace }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/stop/`, { method: 'POST' }),
  reconcileWorkspace: (workspaceId: string) => request<{ workspace: Workspace }>(`/api/workspaces/${encodeURIComponent(workspaceId)}/reconcile/`, { method: 'POST' }),
  vncGrant: (workspaceId: string) => request<VncGrant>(`/api/workspaces/${encodeURIComponent(workspaceId)}/vnc-grant/`, { method: 'POST' }),
}

export type ProviderAccount = {id:string;label:string;provider:'cloudflare'|'porkbun';account_id:string;revision:number;configured:boolean;supported:boolean;can_check?:boolean;access_check?:ProviderAccessCheck}
export type RegistrySetup = {registries:ProviderAccount[];vault_ready:boolean;dns_selection:{credential_id:string;revision:number}}
export type BeaconDestination = {id:string;label:string;server:string;enabled:boolean;ca_certificate:string;revision:number}
export type DeploymentSetup = {version:number;destinations:BeaconDestination[]}
export const setupApi = {
 readiness:()=>request<SetupReadiness>('/api/setup/readiness/'),
 checkProvider:(id:string,revision:number)=>request<{access_check:ProviderAccessCheck}>(`/api/setup/registries/${encodeURIComponent(id)}/check/`,{method:'POST',body:JSON.stringify({revision})}),
 registries:()=>request<RegistrySetup>('/api/setup/registries/'),
 saveRegistry:(data:unknown)=>request<RegistrySetup>('/api/setup/registries/',{method:'POST',body:JSON.stringify(data)}),
 deployments:()=>request<DeploymentSetup>('/api/setup/deployments/'),
 saveDestination:(data:unknown)=>request<DeploymentSetup>('/api/setup/deployments/',{method:'POST',body:JSON.stringify(data)}),
}

export type ProviderAccessCheck = {
 status:string;message:string;fresh:boolean;domains:{id:string;name:string;status:string}[];more_available:boolean;
 started_at:string|null;finished_at:string|null;retry_after_seconds:number
}
export type SetupReadiness = {
 server_time:string;read_only:true;
 checks:{id:string;title:string;area:string;status:'observed'|'configured'|'needs_attention'|'not_configured'|'not_checked'|'blocked';detail:string;link:string;observed_at:string|null}[]
}

export type ArchiveFilesystem = { id: string; stores: string[]; total_bytes: number | null; used_bytes: number | null; available_bytes: number | null; allocated_object_bytes: number | null }
export type ArchiveMirror = { preparation: {state: string; attempt_id: string | null; fresh: boolean}; host_id: string; name: string; selected: boolean; role_revision: number; state: string; reason: string; observation_state: string; observed_at: string | null; last_attempt_at: string | null; observation_revision: number | null; role_observed_at: string | null; snapshot: string | null; archive_count: number | null; summary: { collections: string[]; logical_bytes: number | null; unique_content_bytes: number | null; allocated_object_bytes: number | null; accounting_complete: boolean; filesystems: ArchiveFilesystem[] } | null }
export type ArchiveItem = { licenses?: LicenseSummary; collection: string; digest: string; kind: string; name: string | null; version: string | null; size_bytes: number | null; availability: string; filesystem_id: string | null; provenance: string; approval: string }
export const archivesApi = {
  mirrors: (after?: string) => request<{version: number; mirrors: ArchiveMirror[]; next_cursor: string | null}>('/api/archives/mirrors/?limit=25'+(after ? '&after='+encodeURIComponent(after) : '')),
  items: (mirror: string, snapshot: string, collection: string, after: number | null) => request<{items: ArchiveItem[]; next_cursor: number | null; mirror: ArchiveMirror}>('/api/archives/items/?'+new URLSearchParams({mirror, snapshot, limit: '25', ...(collection ? {collection} : {}), ...(after !== null ? {after: String(after)} : {})})),
}

export type GenerationCoverage = { state: 'complete'|'incomplete'|'unknown'; complete: number|null; total: number|null }
export type GenerationPackage = {
  package:string; version:string|null; revision:string|null; stage:string|null; scope:string;
  source_digest:string|null; origin:string|null; expression:string|null; review:string;
  exceptions:{scope:string;expression:string|null;review:string;notes:string|null}[];
  issues:string[]; notice_count:number; receipt_digest:string|null;
  source_complete:boolean; license_complete:boolean;
  patches:{state:'available'|'unknown'|'not-integrated';count:number|null;items:{name:string;digest:string;origin:string|null;reason:string|null}[]};
}
export type GenerationProvenance = {
  schema:number; generation:string; evidence_state:string; source_material:string;
  archive:{mirror:string;snapshot:string;collection:string;digest:string;name:string|null;size_bytes:number|null;availability:string;provenance:string;approval:string;observed_at:string};
  license_summary:LicenseSummary;
  coverage:{source_provenance:GenerationCoverage;license_evidence:GenerationCoverage;unresolved_provenance:number|null};
  packages:GenerationPackage[];
  patches:{state:'available'|'unknown'|'not-integrated';count:number|null;items:{name:string;digest:string;origin:string|null;reason:string|null}[]};
  build_evidence:{state:string};
}
export const generationApi = {
  detail: (generation:string, query:NoticeQuery) => request<GenerationProvenance>(
    '/api/archives/generations/'+encodeURIComponent(generation)+'/?'+new URLSearchParams(query)
  ),
  exportUrl: (generation:string, query:NoticeQuery) =>
    '/api/archives/generations/'+encodeURIComponent(generation)+'/export/?'+new URLSearchParams(query),
}

export type CloudAccount = {id:string;provider:'aws';label:string;account_id:string;mode:'default'|'keys';region:string;enabled:boolean;expires_at:string|null;expired:boolean;revision:number;updated_at:string;check:{status:string;message:string;fresh:boolean;finished_at:string|null}}
export type CloudSetup = {accounts:CloudAccount[];vault_ready:boolean}
export const cloudApi = {
 list:()=>request<CloudSetup>('/api/setup/clouds/'),
 save:(data:unknown)=>request<CloudSetup>('/api/setup/clouds/',{method:'POST',body:JSON.stringify(data)}),
 check:(id:string,revision:number)=>request<CloudAccount>(`/api/setup/clouds/${encodeURIComponent(id)}/check/`,{method:'POST',body:JSON.stringify({revision})}),
}

export type WorkspacePreflight = { status: string; advisory: true; checks: { code: string; title: string; status: string; detail: string }[] }
export type WorkspaceReadiness = {
  observed_at: string; read_only: true; advisory: true; controller: string; desktop: string;
  desktop_runtime_id: string | null; launch_pending: boolean; cleanup_pending: boolean | null;
  registration: string; pending_count: number | null; cleanup_count: number | null;
  launch_actions: NonNullable<WorkspaceApplications['launch_actions']>; preflight: WorkspacePreflight | null;
}

export type DestinationSummary = {label:string;server:string;enabled:boolean;revision:number;custom_ca?:boolean;ca_sha256?:string|null}
export type DeploymentObservation = {primary:string;destinations_sha256:string|null;destinations:DestinationSummary[];beacon_state:string;station_state:string;beacon_version:string|null;station_version:string|null;apply_supported:boolean;reason:string}
export type DeploymentJob = {id:string;host_id:string;host_label:string;operation:'inspect'|'apply';state:string;actor:string;message:string;created_at:string;started_at:string|null;finished_at:string|null;expires_at:string|null;target:{account_id:string;region:string;instance_id:string};destinations:DestinationSummary[];result:{observation?:DeploymentObservation;before?:DestinationSummary[];primary?:string;sha256?:string}}
export type DeploymentJobsData = {enabled:boolean;hosts:{id:string;label:string;eligible:boolean}[];jobs:DeploymentJob[]}
export const deploymentApi = {
 list:()=>request<DeploymentJobsData>('/api/setup/deployment-jobs/'),
 inspect:(host_id:string,action_id:string)=>request<{job:DeploymentJob}>('/api/setup/deployment-jobs/',{method:'POST',body:JSON.stringify({action:'inspect',host_id,action_id})}),
 review:(host_id:string,inspection_id:string)=>request<{job:DeploymentJob}>('/api/setup/deployment-jobs/',{method:'POST',body:JSON.stringify({action:'review',host_id,inspection_id})}),
 action:(id:string,action:'apply'|'check-outcome')=>request<{job:DeploymentJob}>(`/api/setup/deployment-jobs/${encodeURIComponent(id)}/`,{method:'POST',body:JSON.stringify({action,confirmed_job_id:id})}),
}

export type UserFields={username:string;email:string;first_name:string;last_name:string;is_active:boolean;is_superuser:boolean;password:string}
export type ManagedUser=Omit<UserFields,'password'>&{id:number;revision:string;date_joined:string;last_login:string|null;workspace_count:number;application_count:number}
export type UserList={users:ManagedUser[];page:number;pages:number;total:number}
export const usersApi={
 list:(q='',page=1)=>request<UserList>(`/api/users/?q=${encodeURIComponent(q)}&page=${page}`),
 create:(data:UserFields)=>request<{user:ManagedUser}>('/api/users/',{method:'POST',body:JSON.stringify(data)}),
 update:(id:number,data:UserFields&{revision:string})=>request<{user:ManagedUser}>(`/api/users/${id}/`,{method:'PATCH',body:JSON.stringify(data)}),
 remove:(id:number,revision:string,confirm_username:string)=>request<{deleted:boolean}>(`/api/users/${id}/`,{method:'DELETE',body:JSON.stringify({revision,confirm_username})}),
}

export type LicenseSummary = {state: 'available'|'unavailable'|'missing'|'broken'; review: string; bundle_digest: string|null; notice_digest: string|null; notice_bytes: number|null; package_count: number|null; issue_count: number|null; coverage: string; source_material: string}
export type LicenseRecord = {stage:string|null;source_digest:string|null;package: string; version: string|null; revision: string|null; origin: string|null; expression: string|null; review: string; scope: string; exceptions: {scope:string; expression:string|null; review:string; notes:string|null}[]; issues:string[]; texts:string[]; receipt_digest:string|null}
export type NoticeQuery = {mirror:string; snapshot:string; collection:string; digest:string}
export function noticeUrl(query:NoticeQuery, format='metadata', offset=0) {
  return '/api/archives/notices/?'+new URLSearchParams({...query, format, offset:String(offset), limit:'25'})
}
export const noticesApi = {
  metadata: (query:NoticeQuery, offset=0) => request<{schema:number;summary:LicenseSummary;generation:string|null;source_identity:{kind:string;digest:string;revision:string|null};records:LicenseRecord[];next_offset:number|null}>(noticeUrl(query,'metadata',offset)),
  text: async (query:NoticeQuery) => {
    const response=await fetch(noticeUrl(query,'text'),{credentials:'same-origin',redirect:'error'})
    if (!response.ok || !response.headers.get('Content-Type')?.startsWith('text/plain')) throw new Error('Notice unavailable')
    const body=await response.text()
    if (new TextEncoder().encode(body).length>1048576) throw new Error('Notice too large')
    return body
  },
}

export type DnsSetupReview={review_id:string;expires_at:number;domain:string;prefix:string;nameservers:string[];provider:string;provider_writes:number;write_permission:string;ready:boolean}
export type DnsInspection={ready:boolean;authority:string;provider_reads:string;write_permission:string;operations:{state:string;host_id:string;code:string|null}[];hosts:{host_id:string;label?:string;stage:string;code:string;message:string}[]}
export const dnsSetupApi={
 zones:(credential_id:string,revision:number,cursor?:string)=>request<{zones:{id:string;name:string}[];cursor:string|null}>('/api/hosts/dns-setup/',{method:'POST',body:JSON.stringify({action:'zones',credential_id,revision,cursor})}),
 review:(credential_id:string,revision:number,zone_id:string,label:string)=>request<DnsSetupReview>('/api/hosts/dns-setup/',{method:'POST',body:JSON.stringify({action:'review',credential_id,revision,zone_id,label})}),
 commit:(review_id:string)=>request<{binding_id:string;provider_writes:number;replayed:boolean}>('/api/hosts/dns-setup/',{method:'POST',body:JSON.stringify({action:'commit',review_id})}),
 inspect:(binding_id:string)=>request<DnsInspection>('/api/hosts/dns-setup/',{method:'POST',body:JSON.stringify({action:'inspect',binding_id})}),
}
