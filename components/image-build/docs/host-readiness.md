# Host readiness continuation

The accepted Python generation is the starting point, not yet a bootable host.
The sequence is public CA trust, pinned Python application dependency closure,
boot-support packages, and a host-install candidate with foreign AL2023 boot provenance.
Disk installation or root replacement is not part of these source builds.

## Public CA trust

`project/bootstrap/host-trust.py` builds `ca-certificates-final` from the October
monthly pin. Four files are downloaded and SHA-256 checked: Mozilla NSS certdata,
NSS COPYING, curl mk-ca-bundle and curl COPYING. Exact Git revisions and file hashes
are in the package's source/provenance metadata. No upstream code or bundle is
vendored into this repository. The converter runs offline with explicit
SERVER_AUTH:TRUSTED_DELEGATOR selection. It evaluates expiry at build time; full
byte reproducibility is not claimed. The PEM export does not carry every browser
constraint. It does not include machine-local CAs or private keys.

The trust recipe installs `/etc/ssl/cert.pem` and a compatibility bundle symlink.
Python's default SSL context must load at least 100 anchors with hostname checking
and certificate verification enabled. A separately captured public certificate
chain for www.python.org is frozen into the acceptance command; the target OpenSSL
must validate it through the default trust store and reject a wrong hostname.
This is offline public-chain verification, not a live target HTTPS handshake.
The previously accepted Python check independently verifies live local TLS and
rejects untrusted certificates. `public_https_handshake_verified` remains false
until a network-enabled application acceptance proves that path.

## Required canonical provenance

`python -m zog.zog.image_build.host_trust` accepts project, catalogue, controller, selection,
work, chain and source-revision arguments. It captures exact monthly-pin bytes with
the committed source revision before new preparation and constructs the existing
Provenance producer with generation contract rootfs-v1. Recovery checks frozen
configuration and inputs. Package source selections, recipe bytes, no-patch
declaration, declared environment and dependencies are captured before commands.
Package outputs/results are connected to both the package-only generation and
final composed generation. The accepted Python base is explicitly represented as
a legacy output with no captured producing attempt; it is not retroactively
attested. The existing canonical assembly adapter freezes the composition before
merging and retains a normalized archive and content manifest.

Canonical records: `<project>/state/image-build/build-record/records`.
Retained inputs and archive artifacts: sibling `artifacts` directory.
`<work>/canonical-generation.json` is a canonical closed-graph export after successful
publication. Execution and journal evidence remain controller/trace references.
Installed acceptance jobs remain image-build verification execution references;
this pass does not fabricate separate canonical verification records for them.
Controller/runtime/kernel capture and legacy-base producing history remain explicit
gaps. A closed graph does not imply complete historical provenance.

Raw, non-archive license notices are supported by requiring their evidence path to
match the source destination basename and verifying both source-cache and staged
bytes. Archive evidence retains its existing validation path.

### Assembly of accepted outputs with host labels

`python -m zog.zog.image_build.host_trust_assembly --project PROJECT --previous-work WORK
--package-attempt ATTEMPT --work NEW_WORK` creates a separate assembly from an
accepted CA package output and the exact previously selected Python base. It
reuses the frozen pin and installed verification command; it never executes the
package recipe again or updates the old pipeline. The new assembly captures its
own implementation, input output references and host-label omission evidence.

The `omit-host-security-selinux-v1` composition policy records the paths, sizes
and hashes of source `security.selinux` labels and omits only these host labels
when copying into fresh staging. Accepted inputs are never relabelled. Other
attributes, including capabilities and ACLs, are rejected. The final serializer
still requires no extended attributes. A host which labels new output trees
must be configured appropriately before using this policy.

Successful package reuse does not repair historical provenance of the Python
base. The final generation includes an explicit legacy output for that base.
