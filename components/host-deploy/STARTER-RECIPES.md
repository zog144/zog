# Development recipes

Create one independently initialized workspace per project. The supplied host
specifications refer to this development account and us-east-1. Verify the AMI,
subnet, security group and role before using the bundle in another account.

## box-control

Use examples/systemd-host.json (t3.micro, encrypted 8 GiB, 30-minute uptime).
`provision`, then `stop` if necessary: the existing `run` command expects a stopped
host. Run the systemd recipe with `run --source SOURCE.zip --output RESULTS_DIR`.
That recipe is tailored to the previously accepted box-control archive layout
and installs its Python/test dependencies on Amazon Linux. Newer box-control
archives may require recipe changes. Keep its output manifest for `recover`.

The portable checkpoint commands introduced in 0.4.0 carry generic background
job state. Legacy `run` evidence manifests live in the chosen output directory
and must be saved separately; they are not automatically included in checkpoints.

## image-build or another compilation project

Use generic jobs with a ZIP containing the project's source and a build script:

```json
{
  "command": ["bash", "build.sh"],
  "timeout_seconds": 3600,
  "outputs": ["build"],
  "environment": {}
}
```

On Amazon Linux, the script can install prerequisites using dnf (for example
gcc, gcc-c++, make, and the project's development libraries). Generic execution
uses root on the disposable host. It does not infer dependencies or translate
Fedora package names. The source ZIP SHA-256 is recorded; dependencies downloaded
inside the job need their own version/hash recording for reproducibility.

For a one-hour command, choose a host uptime comfortably beyond one hour,
including setup, transfers and collection. A 90-minute limit is a starting
configuration, not an estimate of build completion. Adjust instance_type and
volume_gib for the actual compiler's memory and artifact needs; t3.micro is only
the small acceptance host, not a recommendation for large toolchain builds.

Run `doctor --remote` before submitting to inspect available tools, disk, RAM,
systemd, Python, uptime and timer status. Configure timeout_seconds to include
package setup if the build script does it. The job admission check reserves 120
seconds within the remaining host uptime; allow more time when collecting large
outputs. Generic jobs do not automatically stop the VM on completion.

SSM source transfer is limited to 2 MiB, results to 20 MiB. Select `--transfer s3`
for larger files using the shared bucket. See S3.md for setup and recovery.

After submission, save a checkpoint and use RECOVERY.md to transfer control.
Keep the checkpoint separate from host-deploy.zip and from credentials.
