# Retained compiler acceptance

`python -m zog.zog.image_build.retained_compiler` finishes an explicitly identified,
retained GCC 15.3.0 bootstrap after its corrected full test suite has passed.
It is a recovery continuation, not a replacement for normal recipe pipelines.

Supply `--project`, `--catalogue`, `--controller`, `--retained`, `--ownership`,
`--work`, `--test-job`, and `--install-job`. The retained workspace must contain
the original root inventory and registration, bootstrap comparison/byte-swap
results, passing full-suite report, and a separate staged installation bound to
that report. Both controller jobs must have exited zero and completed cleanup.
The caller must retain the workspace until this operation has completed.

The operation records its inputs before composition. Only the hash-checked old
GCC ownership record authorizes replacing files. Installed C/C++ compilation,
threads, exceptions, LTO, dynamic loader paths and compiler search paths are
checked through box-control in a fresh read-only root. M4 is then rebuilt using
the pinned native-verification recipe and its installed binary is exercised.
Only after these checks does image-build publish and activate a self-hosted
stage-2 toolchain. A failed check prevents promotion and preserves evidence.
This does not declare the rootfs bootable or publicly releasable.

Run this operation under a durable host-deploy supervisor. Compilation and
verification commands use the normal box-control runner, so their output remains
in journald and is available to station-access. Do not modify a failed pipeline
checkpoint to make it appear successful. Resume with identical recorded inputs;
inspect failures before changing the operation or selecting a new work directory.
