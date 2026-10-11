# Installer-local fixture plan schema 1

This is a test harness contract, separate from `host-install-artifact` schema 1.
Generate an exact example with `tests/rehearse.py`; its `artifacts/manifest.json`
contains the UUIDs and SHA-256 hashes of the actual generated input images.

The top-level keys are exactly `schema`, `generation`, `architecture`, `boot`,
`artifacts`, `layout`, `runtime`. Unknown fields and duplicate JSON keys fail.
The initial architecture is x86_64; sector size is 512 bytes for regular files.

`boot` has kind `foreign`, provider `amazon-linux-2023`, release, kernel_release,
components, root_partuuid, root_argument and root_read_only. Components contains
nonempty provenance descriptions for kernel/initramfs/modules/efi/configuration.
These strings are declarations, not proof of their presence in the images.
The root argument must be `root=PARTUUID=<HOST-A UUID>`, with read-only root true.

`artifacts` has rootfs and esp descriptors: path (normalized relative path),
bytes, sha256, format. Formats are ext4 and fat32 respectively. Both images must
exactly fill their corresponding partitions. Integrity and filesystem geometry
are checked, but their boot contents are not validated in this pass.

`layout` has disk_guid and partitions. Each partition has role, mib, partuuid,
filesystem_uuid. Order is ESP, HOST-A, HOST-B, STATE, APPLICATIONS. ESP has null
filesystem_uuid; FAT identity belongs to the prebuilt ESP. Other UUIDs are
explicit; HOST-A's ext4 superblock UUID must match. All UUIDs are nonzero,
canonical and distinct. Host slots are equal in size, each partition at least
64 MiB. Disk minimum is the sum plus 2 MiB. Extra capacity remains unallocated.

The initial layout reserves a 1 MiB aligned start, primary GPT, protective MBR,
128 entries of 128 bytes, a backup entry table and backup header. ESP uses the
EFI system partition GUID; all other roles use the generic Linux filesystem
GUID. No BIOS boot partition, verity hash placement, encryption or boot-slot
selection metadata is implemented. Keeping five roles does not settle those
later boot/security design details.

`runtime` is fixed to state_mount=/state, applications_mount=/applications and
host_specific_identity=first-boot **for the fixture only**. Nothing writes fstab
or mount units; real mapping remains a coordinated decision.

The GPT encoder was checked against the UEFI GPT layout specification:
https://uefi.org/specs/UEFI/2.11/05_GUID_Partition_Table_Format.html
Local external verification uses util-linux `partx` against actual disk bytes.
