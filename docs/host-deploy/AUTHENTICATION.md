# Authentication choices for Work development

AWS temporary credentials contain an access key ID, secret access key, session
token and expiration. They are not intrinsically tied to an originating IP.
An IAM policy can impose an IP restriction. That is a separate policy choice,
and we have not established stable or unique Work egress addresses.

An AssumeRole session normally defaults to one hour. Its requested duration is
15 minutes up to the role's configured maximum, which can be up to 12 hours;
role chaining has a one-hour limit. Different STS operations have different
limits. Expiration does not imply manually copying replacement keys: supported
SDK credential providers renew credentials while their source authorization
remains valid. A static copy of STS output alone cannot renew itself.

For this development period, retain the existing dedicated development profile
outside the distribution. Bootstrap imports a separately supplied file without
printing its values, preserves other profiles, and writes mode 0600. It does
not create AWS keys or change IAM policies. The import file supports Access key
(or Access key ID), Secret access key, and optional Session token labels.
Rotate the long-term development key when this temporary arrangement ends.
The package never uploads this file to EC2 or includes it in source transfers.
Only pass trusted source archives that do not contain secrets.

## Possible later Zog approval service (not implemented)

The user's proposed "knock" flow can avoid repeated manual key replacement:

1. The bundle contains the Zog service URL and, optionally, an enrollment code
   that can request approval but cannot provision resources.
2. A fresh workspace generates its own private/public key pair and sends an
   enrollment request with its public key and workspace description.
3. The user approves a matching request code in a trusted web UI. An email
   notification can point to that UI, but sending notifications is separate.
4. The service grants that key renewable, workspace-scoped access. It issues
   short-lived AWS role sessions through a credential provider, or performs
   narrowly scoped host operations on the workspace's behalf.
5. Renewal is automatic until approval is revoked or its overall lifetime ends.
   Previously issued AWS credentials may remain usable until their expiration;
   blocking renewal alone is not immediate revocation of those credentials.

The lasting credential would be a revocable Zog enrollment identity, rather
than an unrestricted AWS key. It still needs protected local storage: a private
key stored in plain files can be copied by anyone able to read those files.
This proves key possession, not that a requester is an authentic Work container.
An enrollment code embedded in every bundle must never itself grant cloud access.

For a two-to-four-month interim period, we recommend finishing host tooling
before building and operating this approval service. Current profile-based SDK
access leaves room for AssumeRole or a credential_process provider later, without
changing provisioning logic. The proposed broker has not been deployed or tested.

References:
- https://docs.aws.amazon.com/STS/latest/APIReference/API_AssumeRole.html
- https://docs.aws.amazon.com/boto3/latest/guide/credentials.html
- https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_condition-keys.html#condition-keys-sourceip
