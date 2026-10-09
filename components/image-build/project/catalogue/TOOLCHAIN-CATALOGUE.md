# Toolchain catalogue pass 3

The `project/package/<name>/` directories record 39 source projects: 30 from the LFS 13.1 cross-toolchain/temporary tools sequence and nine native compiler/test-support additions. This is the beginning of the Zog package catalogue, not a completed self-hosting build recipe set.

Each file is one Python literal parsed with `ast.literal_eval`; no metadata module is imported or evaluated as executable Python.

| File | Meaning |
|---|---|
| `package.py` | Stable project name, role, catalogue status and reference |
| `upstream.py` | Source version, homepage, release archive URL, repository URL where recorded, verification status |
| `distribution.py` | Per-distribution package mapping, independently selected seed prerequisites, host minimum version |
| `recipe-plan.py` | Stage identities and explicit unknown recipe/dependency/output fields |

Release archives and source repositories are distinct. Use an upstream release tarball as a source input when appropriate; Git checkouts can need extra bootstrap tools. A repository URL is not necessarily GitHub. `None` means unrecorded or not yet reviewed, never “no dependency” or a fictitious digest. Fedora Rawhide has an explicit unreviewed profile and cannot generate an install plan yet. Amazon Linux observations came from the September 16 inventory; validate repository availability again on each new target.

From `image-build-source/`:

```sh
python3.11 -m image_build.developer.catalogue --package-dir project/package
python3.11 -m image_build.developer.catalogue --package-dir project/package --list
```

The default command prints a DNF host-prerequisite plan and the package responsible for each entry. It does not run DNF. It excludes unrelated development RPMs: GCC's initial GMP/MPFR/MPC dependencies are compiled from source. This command does not resolve RPM dependency closure or generate a file-copy inventory. `developer.host` also now includes Bison, M4 and Texinfo in its existing default preparation list.

The ordinary source loader explicitly refuses `catalogue-only` packages. To promote a package, author its stage-specific executable metadata (`sources.py`, `dependencies.py`, `build.py`, `produce-manifest.py`), verify SHA-256 inputs, review outputs and update its catalogue status. Multiple compiler passes must remain distinct build nodes even though they share project sources. Dependency cycles must be broken by those stages, not by allowing arbitrary cycles in the resolver.

## Seed generation

Image-build should own assembly of the distribution seed root. It may be displayed as **generation 1 — distribution seed**, but persistent identity remains content-based and its existing manifest kind remains `host-bootstrap`. A display ordinal must never imply source provenance or replace the generation digest.

The sequence is:

1. Record the host release, architecture, exact RPM inputs and selected host file inventory.
2. Assemble their required files into a new root: executables, dynamic loader, libraries, C/C++ headers, compiler support programs, shell utilities and required data/configuration. Do not copy all of `/etc`, `/root` or host credentials.
3. Verify the seed inside box-control's build-job environment, then publish/import it through `import-bootstrap` with provenance. The existing `developer.host.assemble` accepts a reviewed file list and follows symlink targets; it does not yet discover the complete compiler/runtime closure automatically.
4. Build the source toolchain and temporary utilities inside that seed, then compose a clean root from their outputs.
5. Rebuild and test the native toolchain in the clean root before marking it as the source-built toolchain generation used for ordinary builds.

There is no newly assembled seed or source-built compiler in this pass. The catalogue establishes inputs for that next implementation. Build execution continues through box-control/systemd. The host package installation is explicit developer/bootstrap preparation; ordinary source builds do not gain a dependency on RPM tooling.

## References

- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter02/hostreqs.html
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter03/packages.html
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/chapter03/patches.html
- https://www.linuxfromscratch.org/lfs/view/13.1-systemd/appendices/dependencies.html

Source URLs are recorded from LFS references; archives have not been downloaded or independently hash-verified. Recipe promotion must also review applicable errata and patches.

## Amazon Linux yacc alias

The Bison RPM does not install `/usr/bin/yacc`. The new host has a wrapper at that path executing `/usr/bin/bison -y "$@"`. This requirement is recorded in Bison distribution metadata and returned by the host planner. It is not an extra RPM dependency. Preserve it in the seed root and verify it invokes Bison; do not install Berkeley Yacc as a substitute. The planner reports alias requirements but does not create them.
