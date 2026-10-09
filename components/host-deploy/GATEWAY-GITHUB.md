# GitHub issue dispatcher

This is implementation pass 2 of the GitHub-to-EC2 execution gateway. The workflow
and helper code are developed on `unstable`. GitHub `issues` workflows execute
from the repository default branch, which is currently `main`; therefore the
dispatcher is inert until an explicitly authorized publication to `main`.

The first publication/test must run in **validation-only mode**. Leave repository
variable `ZOG_GATEWAY_SUBMIT_ENABLED` unset or set to anything other than the
exact string `true`. A matching issue will then be checked out, parsed,
authorized, and validated, but the workflow will not invoke the AWS credential
action, request an AWS OIDC token, or send SQS.

## Issue format and authorization

The workflow reacts only to an `issues: opened` event whose body contains the
v1 marker. The body itself must consist only of the marker followed by one
`json` code fence containing the pass-1 request. Extra prose and extra code
fences are rejected.

The trusted GitHub event is authoritative for:

- repository: `zog144/host-deploy`
- issue number
- triggering actor / issue creator

A newly opened issue cannot know its assigned issue number in advance, so issue
content deliberately omits the `origin` field. After actor authorization, the
workflow constructs `origin` exclusively from the trusted event and then runs the
complete pass-1 request validator. Supplying `origin` in issue content is rejected.

Authorized actors are repository-controlled in
`.github/gateway-authorized-actors.json`. The initial list contains only
`zog144`. There are no wildcard actors and issue text cannot add an actor.
The issue marker, title, labels, and request contents are not authorization.

A duplicate request may cause another GitHub workflow invocation. The SQS FIFO
submission uses `request_id` as `MessageDeduplicationId` and `workspace_id`
as `MessageGroupId`, but the future persistent consumer must still enforce
application-level request idempotency because the FIFO deduplication window is
not a durable ledger.

## Enabling the SQS test

Only after the validation-only issue succeeds, configure these repository
variables:

- `ZOG_GITHUB_DISPATCH_ROLE_ARN`: ARN of the existing
  `zog-github-dispatch` IAM role.
- `ZOG_BUILD_REQUEST_QUEUE_URL`: exact HTTPS queue URL for
  `zog-build-requests.fifo` in `us-east-1`.
- `ZOG_GATEWAY_SUBMIT_ENABLED=true`: explicit live-dispatch gate.

The queue URL validator accepts only
`https://sqs.us-east-1.amazonaws.com/<12-digit-account>/zog-build-requests.fifo`.

The workflow uses GitHub OIDC and no stored AWS access key. Actor authorization
and request validation occur before the AWS credentials step. The configured
role must remain limited to `sqs:SendMessage` for the primary queue.

The AWS credential action is pinned to the immutable `v6.3.0` release tag.
GitHub-owned checkout/setup actions currently follow the repository's existing
major-version convention.

## SQS message binding

The SQS body is the canonical validated protocol JSON. Submission sets:

- FIFO message group: exact `workspace_id`
- FIFO deduplication ID: exact `request_id`

The helper logs only a bounded request summary and the SQS FIFO receipt. It does
not log arbitrary issue prose.

No GitHub issue completion comment is produced in pass 2; reporting is a later
gateway pass, and the issue is never the authoritative execution record.
