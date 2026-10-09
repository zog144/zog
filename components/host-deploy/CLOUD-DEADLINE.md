# AWS-side shutdown deadline: investigated, not enabled

The VM's systemd uptime timer remains the implemented deadline. It is independent
of the controlling Work process but depends on a functioning guest and successful
first-boot installation. It is not a guaranteed cost ceiling.

A suitable next mechanism is an EventBridge Scheduler one-time universal target
calling EC2 StopInstances. It would use a separate execution role trusted by
scheduler.amazonaws.com, with ec2:StopInstances restricted to the development
instance. The caller needs schedule management permissions and iam:PassRole for
that specific execution role. The EC2 SSM role is not that role.

A future implementation should durably record its schedule name and request
before creating it, verify the target and deadline before acknowledging the
protection, and reconcile lost responses. Start must create a fresh deadline
for the new boot; stop/terminate must reconcile schedule cleanup. A late retry
from a previous boot must not stop a newly restarted workload: a boot/lease-aware
intermediary or a verified schedule retirement barrier is required before restart.
A bare recurring stop schedule does not solve these ownership and retry issues.

On 2026-09-13, scheduler:ListSchedules returned AccessDeniedException for the
development profile. This does not prove CreateSchedule is denied, but the
required execution role and its permissions have not been established. No role,
schedule, or IAM policy was created or modified. This release deliberately does
not claim cloud-side expiry.

AWS references:
- [Universal targets](https://docs.aws.amazon.com/scheduler/latest/UserGuide/managing-targets-universal.html)
- [Execution role setup](https://docs.aws.amazon.com/scheduler/latest/UserGuide/setting-up.html)
- [CreateSchedule API](https://docs.aws.amazon.com/scheduler/latest/APIReference/API_CreateSchedule.html)
