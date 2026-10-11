# Security and provenance

## Identity and signed evidence

Host-identify generates and preserves host identity. Host-discover transports authenticated evidence. Verification and enrollment trust must be independent of a mutable host display name.

## Authenticated control and ownership

Host-deploy, station-access, box-control and root-control own different authorization boundaries. A valid signature does not automatically grant deployment authority; ownership and host state are checked at the consuming boundary.

## Reviewed sources and immutable generations

Source pins and independent archive verification precede image-build output. Immutable generation references and operation preparation preserve selected inputs across recovery.

## Build evidence and verification

Build-record is the canonical provenance producer, build-trace exposes its public inspection contract, and integrate-observe presents comparisons without inferring unrecorded causality or policy.

## Attestation and reproducibility

The planned attestation network prioritizes independent source-download agreement first; reproducible build attestation is a separate later capability, not a current production guarantee.

## Licenses and source access

Preserve third-party license and patch provenance at package and application encounters, with precise references and reviewed notices; do not infer that a license review was performed merely because a source was downloaded.
