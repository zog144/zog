# Two-phase normal-reboot tests — host-deploy 0.5.0

Box-control owns scenarios and assertions. Host-deploy supplies a persistent
working directory, bounded phase execution, one normal reboot, changed-boot
verification, reconnection, receipts, evidence transport and host expiry checks.
This workflow does not test abrupt power loss or implement request retention.

## Interface for box-control

Supply a source ZIP and a recipe such as examples/reboot-recipe.json:

```json
{
  "preparation": {"command": ["bash", "prepare-reboot-tests.sh"], "timeout_seconds": 300},
  "verification": {"command": ["bash", "verify-reboot-tests.sh"], "timeout_seconds": 300},
  "reboot_timeout_seconds": 600,
  "outputs": ["."],
  "environment": {}
}
```

Each command is argv, not an implicitly interpreted shell string. Both phases
run as root with the same extracted source directory as their working directory.
Preparation may install dependencies; they persist on the same EC2 disk.
Use Python/bash explicitly for scripts because ZIP extraction does not preserve
executable permissions. Phase scripts must not issue their own reboot.

The following variables are supplied to both phases (reserved values override
recipe environment entries):

| Variable | Meaning |
|---|---|
| HOST_DEPLOY_STATE_DIRECTORY | Persistent directory for application checkpoints, assertions and outputs |
| HOST_DEPLOY_BEFORE_BOOT_ID | Boot ID captured before preparation |
| HOST_DEPLOY_AFTER_BOOT_ID | Empty during preparation; verified new boot ID during verification |
| HOST_DEPLOY_PHASE | preparation or verification |

Both the extracted source and state directory survive the normal reboot.
`outputs` selects relative paths within the state directory. `.` captures all of
it. Host-deploy snapshots the selected state separately after each phase, so
verification does not overwrite the captured preparation evidence. Application
scripts remain responsible for their own authoritative records and fsync rules.
Host-deploy synchronizes its receipts and requests a normal, orderly reboot.

Preparation exit 0 authorizes reboot. Verification exit 0 means the test passed.
Nonzero exit or timeout preserves the phase result and prevents later phases.
Do not signal a prepared-but-ambiguous box-control scenario by failing the
preparation command: preparation should return 0 after constructing that test
fixture; verification should assert the expected ambiguity after reboot.

## Run and reconnect

Use a workspace-owned, running, SSM-online host created with `provision` and
made ready using `start`. Existing IAM SSM command permissions suffice; this
workflow does not require an EC2 RebootInstances permission or a new role.

```sh
host-deploy reboot-submit --workspace ./box-workspace --name recovery-one \
  --source ./box-control-reboot-tests.zip --recipe ./reboot-recipe.json
host-deploy checkpoint-export --workspace ./box-workspace \
  --output ./recovery-checkpoint.zip
host-deploy reboot-resume --workspace ./box-workspace --name recovery-one \
  --wait-seconds 900
host-deploy reboot-status --workspace ./box-workspace --name recovery-one
host-deploy reboot-collect --workspace ./box-workspace --name recovery-one \
  --output ./reboot-results.tar.gz
host-deploy stop --workspace ./box-workspace
```

Submit starts preparation. Repeated matching submission inspects the same
workflow and never initiates its reboot. Resume advances through preparation,
reboot and verification. `--wait-seconds 0` makes one bounded advance attempt.
Status only observes/reconciles; it never initiates a phase or reboot.

Resume's wait budget is 0..3600 seconds. It may exceed that polling budget by one
in-flight, bounded SSM command and SDK transport retries. Exhausting the polling
budget leaves the workflow resumable; inspect `observed.phase` and any
`connection_error` instead of treating CLI exit 0 as proof of test success.
Only observed.phase=succeeded denotes a passed two-phase test.

During reboot, SSM may be unavailable. A subsequent resume reconnects and reads
remote durable receipts. SSM Online alone is insufficient: a different Linux
boot ID and an active, enabled host expiry timer are required before verification.
The reboot deadline is 60..1800 seconds. A controller returning late can accept a
boot that actually began within that window (using host time and uptime). A
late boot or unchanged boot beyond the deadline blocks automatic progress.

Keep checkpoints outside transient scratch storage when moving to a new Work
container. `checkpoint-export --handoff` retires the original workspace; restore
as described in RECOVERY.md. Reboot records are now included. Once submission is
acknowledged, resume requires neither the original ZIP nor the recipe. If source
staging itself was interrupted, repeat reboot-submit with identical inputs.
Do not concurrently operate cloned/restored copies of one workspace.

## Failure, uncertainty and cleanup

Progress is recorded before phase or reboot dispatch. A lost dispatch response
cannot authorize another dispatch. Remote receipts govern even if the local
checkpoint is older. If a phase disappears without a terminal receipt or a
reboot outcome remains uncertain, the workflow enters `uncertain` and prevents
further automatic mutation. `reboot-status` and `reboot-collect` remain available
once phase services are inactive.

`reboot-abandon --workspace ... --name ...` stops active phase services, retains
evidence, and releases the workflow. It refuses abandonment while a reboot may
still be queued on the original boot. In that case, use explicit `stop --force`,
then `start` and inspect/abandon on the changed boot. A force-stop is recovery
cleanup and is not reported as a successful normal-reboot test.

Each reboot workflow has exclusive use of its host. Version 0.5.0 generic job
dispatch and routine stop/terminate refuse a nonterminal reboot workflow, even
across reboot. Independently initialized workspaces with separate EC2 hosts
continue to work concurrently. Do not use older clients or direct AWS commands
to operate a host assigned to a live workflow.

No automatic stop occurs at workflow completion: collect evidence, then stop.
The enabled guest timer protects every boot and is checked before and after
reboot. Its maximum uptime starts again at each boot; it is not a total workflow
cost cap or an AWS-side deadline. Each phase also needs its timeout plus a
120-second reserve within the current host uptime allowance. After abandoning
or failing a workflow before reboot, use start to reopen generic job admission.

The results archive contains the recipe/source identity, orchestration receipts,
before/after boot facts, separate phase logs, phase service journal excerpts,
and the two state snapshots. Uncertain/abandoned workflows also capture the
remaining selected state in recovery-state.tar.gz when available. No source tree is included automatically. SSM
limits remain 2 MiB source / 20 MiB results; the optional S3 path is still subject
to the previously documented IAM blocker.

## Included smoke test

Generate the payload outside this checkout from the readable fixture sources:

```sh
python3 examples/build-reboot-smoke.py --output /work/acceptance/reboot-smoke.zip
```

Use that generated ZIP with `examples/reboot-recipe.json` to check the
harness independently of box-control. The generator does not run the fixture. Preparation writes a checkpoint and starts
a transient systemd witness service. Verification asserts a changed boot,
preserved checkpoint, absent transient witness, and one execution of each phase.
The four box-control recovery scenarios belong in box-control's own phase scripts.
