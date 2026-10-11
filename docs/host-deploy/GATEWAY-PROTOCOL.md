# GitHub-to-EC2 gateway protocol v1

This document defines the side-effect-free request and durable state contract used
by the planned GitHub-to-EC2 execution gateway. It does **not** enable AWS access,
SQS consumption, EC2 mutation, or GitHub issue reporting by itself.

The implementation is `zog.host_deploy.gateway.protocol`. Both the GitHub
dispatcher and the persistent command-center consumer must validate the same
contract. The command-center side validates again even after GitHub validation.

## Trust boundary

A request is JSON with a closed schema. Unknown fields and operations are rejected.
Duplicate JSON object keys and non-finite numbers are rejected. The maximum encoded
request size is 16 KiB.

Protocol validation is not authorization. In particular, `origin.trigger_actor`
is audit metadata. The GitHub Actions pass must compare it with the trusted GitHub
event actor and authorize that actor **before** assuming the AWS OIDC role. A label,
issue body, or syntactically valid request never grants authority.

The v1 origin repository is fixed to the private `zog144/host-deploy` repository.

## Request envelope

Every request contains:

- `schema`: integer `1`.
- `request_id`: canonical lowercase 32-hex UUID identity. This is the durable
  external request identity and is not an image-build pipeline ID.
- `workspace_id`: the existing host-deploy workspace identity from
  `workspace.json`.
- `operation`: one of the operations below.
- `origin`: exactly `repository`, positive bounded `issue_number`, and
  `trigger_actor`.
- `parameters`: operation-specific closed parameters.
- `source`: present only for `build.submit`.

`build.submit` source identity is exactly repository `zog144/image-build` plus
a lowercase 40-hex Git commit. Branches, tags and symbolic revisions are not
accepted.

### Operations

| Operation | Parameters | Source |
| --- | --- | --- |
| `build.submit` | `{"lane": LANE, "task": NAME}` | Required exact image-build commit |
| `build.status` | `{"lane": LANE, "pipeline_id": ID}` | Forbidden |
| `build.resume` | `{"lane": LANE, "pipeline_id": ID}` | Forbidden |
| `build.cancel` | `{"lane": LANE, "pipeline_id": ID}` | Forbidden |
| `diagnostic.submit` | fixed diagnostic selection | Forbidden |
| `host.status` | `{}` | Forbidden |

Pipeline IDs use image-build's existing canonical lowercase 32-hex pipeline
identity. Every image-build operation also carries a canonical lane name because
pipeline IDs are scoped to an independent box-control/image-build Project. Resume
and cancel deliberately do not accept source replacements.

The initially selectable maintained build tasks are:

- `stages`
- `native-stage`
- `glibc-final`
- `glibc-publish`
- `final-math`
- `final-compiler`

The future execution adapter owns the actual argv, paths, controller configuration,
timeouts, environment and server-side build profile. Request JSON cannot supply
shell commands, argv, filesystem paths or environment variables.

The v1 diagnostics are `host.runtime` and `build.pipeline`. The latter requires
the exact existing `lane` and `pipeline_id`. Additional diagnostics require an explicit
protocol change; arbitrary commands are not a diagnostic interface.

Example submission:

```json
{
  "schema": 1,
  "request_id": "0123456789abcdef0123456789abcdef",
  "workspace_id": "fedcba9876543210fedcba9876543210",
  "operation": "build.submit",
  "origin": {
    "repository": "zog144/host-deploy",
    "issue_number": 123,
    "trigger_actor": "zog144"
  },
  "source": {
    "repository": "zog144/image-build",
    "commit": "2222222222222222222222222222222222222222"
  },
  "parameters": {
    "lane": "rebuild-oct1",
    "task": "final-compiler"
  }
}
```

## Durable request state

`new_state(request)` binds the validated request and its canonical SHA-256 digest
into a durable state record. The request bytes are immutable for the lifetime of
that request ID. Reconciliation must never replace source, workspace, operation,
pipeline identity or parameters.

Five state dimensions remain separate:

1. `acceptance`: `received`, `accepted`, `rejected`
2. `admission`: `not_started`, `pending`, `admitted`, `blocked`
3. `dispatch`: `not_started`, `prepared`, `submitted`,
   `submission_uncertain`
4. `completion`: `not_started`, `pending`, `running`, `completed`,
   `failed`, `timed_out`, `cancelled`, `recovery_blocked`
5. `reporting`: `not_started`, `pending`, `published`, `failed`

Transitions are append-only history entries with RFC3339 UTC timestamps. State
validation replays the complete history and rejects a snapshot that does not match
the replayed result.

Admission cannot start until acceptance. Dispatch cannot prepare until admission.
Completion cannot become pending until dispatch is confirmed `submitted`.
A `submission_uncertain` request therefore cannot be treated as executed; it must
first reconcile the existing remote request. `recovery_blocked` is explicit and
may later reconcile without altering the immutable request binding.

Reporting is deliberately independent. A rejection or admission block may be
reported without dispatch. A running request may be reported and then reported
again after completion. GitHub issue reporting is never the authoritative
execution record.

## Pass-1 scope

This protocol module performs no I/O other than parsing caller-supplied JSON.
It does not create an SQS client, assume AWS roles, run subprocesses, mutate a
workspace, access EC2, or write GitHub issues. Those capabilities are later passes
and must preserve this request binding and transition model.


## Shared-host lane routing

A lane name is lowercase ASCII with hyphens and identifies one independent
box-control Project/image-build state universe on the shared EC2 host. The gateway
must resolve the lane through host-deploy's durable lane registry; request JSON
never supplies project paths, controller sockets, UID/GID values or resource limits.

This prevents a request for one lane from observing or resuming a project-local
pipeline with the same 32-hex ID in another lane. Host-level diagnostics remain
lane-independent.
