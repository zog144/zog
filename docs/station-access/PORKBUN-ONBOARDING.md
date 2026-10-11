# Porkbun onboarding and upstream Cloud credentials wiring repair

Based on unstable 62924c6432631afb95ef054b77919adee7502328. Station-access 0.4.4 adds Porkbun read-only checks to the existing Registries workflow.

Administrators select Porkbun, enter API key and Secret API key, and save into the existing encrypted vault. Blank edit fields retain both saved keys; replacing either requires both. Fields are masked and cleared after submission. An explicit Check access and list domains action checks the displayed revision, uses the existing cooldown and concurrency gate, and stores bounded sanitized results. It makes no purchase or DNS write. GET/page rendering never contacts providers. Setup readiness includes these observations.

Cloudflare selection/reconciliation remains unchanged. The API's supported flag continues to describe current DNS-controller compatibility; can_check separately enables provider read checks. Porkbun stays unavailable for automatic DNS reconciliation until a domain and explicit controller binding are implemented. Up to 50 entries are displayed; a larger first Porkbun page is marked truncated.

The Porkbun client is provided by the `zog.network_register` component shipped in the same aggregate distribution. No purchase methods or billing actions are implemented. No real key is committed or imported into a running station.

## Existing baseline defect repaired for a buildable integration

The starting commit included CloudCredential migration 0009, cloud_configuration.py, CloudsPage and tests, but omitted the corresponding model class, frontend API exports, backend view/URL bindings and navigation. This made registry test discovery fail and the frontend fail to build before Porkbun work. Restored those bindings to match the existing migration and logic; no new cloud behavior or credential application was added.

## Verification

See verification/porkbun-*.txt. Live read-only network-register checks accepted the supplied Porkbun credentials and found zero domains. Station-access UI/API verification uses local fixtures; no running host deployment was performed.
