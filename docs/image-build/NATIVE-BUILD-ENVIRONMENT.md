# Completing the temporary native build environment

`zog.zog.image_build.build_environment.run(project, catalogue, controller, selection)` expands an accepted `native-temporary-toolchain` selection. The supplied base must explicitly be source-built. It does not change the normal-build promotion boundary or the active generation.

The reviewed LFS 13.1-systemd plan is `project/bootstrap/lfs-native-environment.py`. Recipes live in each project's `stages/native-environment` directory. The graph resolves Python's Zlib/mpdecimal inputs and Texinfo's Perl input. Other basic build tools are provided by the accepted base generation. This is a staged bootstrap graph, not a distribution dependency solver.

Each source archive is pinned to SHA-256. The catalogue preserves distribution mappings and records verified secondary GitHub repositories separately from authoritative release archives. Package outputs are staged under DESTDIR and checked against output manifests. Perl manual-page paths and extensions are explicitly configured, because a minimal root may have no existing man-directory defaults. The shared Info index is omitted so independent packages do not collide on it.

The operation snapshots all recipes and binds the base, execution policy, acceptance commands and plan to its durable record. Individual commands use the existing box-control checkpoint adapter. On an interrupted wait, resume the same operation: it inspects the existing job identity before proceeding. A changed recipe or policy fails rather than silently reusing previous work.

After all packages succeed, their outputs are merged with the base into a recorded assembly root. A separate nonroot, network-disabled box-control job performs the checks in `project/bootstrap/native-environment-checks.py`. Publication records `build_environment_complete=True`, `source_built=True`, `self_hosted=False`. Completed resume validates the published selection and performs any pending assembly cleanup without compiling again.

Package source and private root workspaces are cleaned after successful output recording and controller release. A failed workspace is retained for diagnosis. Source archives, recorded installed outputs, immutable generations and journal references remain. Generation retention is explicitly capped at 16 for this bootstrap operation; that is a safety limit, not an automatic deletion policy.

The focused acceptance tests exercise generated Bison C code, Perl, Python AST parsing, decimal arithmetic, Zlib compression, subprocess execution, Gettext catalogue generation, Texinfo and Util-linux. Python intentionally lacks optional SSL and other modules at this temporary LFS stage. A final self-hosting rebuild and comprehensive upstream test suites remain separate work.

## Verified package reuse after a recipe correction

`zog.zog.image_build.artifacts.import_completed(builder, pipeline_id)` imports only packages with validated completion records from an explicitly released pipeline. It checks the original recipe snapshot, execution policy, package identity, recorded outputs and resource release receipts. Rejected or incomplete packages are skipped. Imports are copied into a content-addressed artifact store; originals remain intact.

The engine may restore a package only when its full inputs match: recipe fingerprint, toolchain generation, dependency output identities, architecture and execution policy. It rechecks all cached file hashes. Changed recipes or policies cause a build; corrupted cached bytes are rejected. Restoration commits atomically and records the original pipeline/package in `artifact-reuse.json`, preserving the original job/log lineage.

This pass uses that path for seven accepted packages after correcting Util-linux's isolated staging directories. Util-linux is compiled again; its rejected output is never reused. The final combined acceptance runs against all eight installed packages.
