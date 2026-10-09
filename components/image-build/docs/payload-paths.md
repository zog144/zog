# POSIX payload paths

Rootfs and foreign-boot USTAR member paths are relative POSIX paths. A backslash
is a literal filename character, including systemd unit names containing `\x2d`.
Export, inventory comparison and archive verification preserve these bytes;
consumers must not unescape them or use Windows path-separator semantics.

Absolute paths, NULs, empty components, `.` and `..` components remain forbidden.
Duplicate members and missing or symlink parents remain rejected. Ownership,
mode, xattr, hardlink and before/after/decoded inventory checks are unchanged.
Interchange metadata names (payload filenames and kernel release) retain the
stricter no-backslash contract.

When correcting the exporter after an assembly failure, retain the frozen
assembly evidence. Release the failed pipeline through its supported API, import
its completed outputs with `artifacts.import_completed`, then start a fresh
pipeline with the same recipes and execution policy. Cache restoration verifies
inventories and retains canonical package result/output references. The new
assembly captures the corrected implementation; do not rewrite old bindings.
