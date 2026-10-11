# Concurrent image-build lanes

Host-deploy can reserve multiple independent image-build/box-control projects on one
development host. A lane is an execution namespace, not a compiler stage.

Each lane binds:

- a unique lane/project basename;
- an exact authorized source repository and immutable commit;
- the exact raw SHA-256 of the deployed `project/package/commit-pin.py`;
- explicit provenance host/project scopes;
- per-build MemoryMax, TasksMax and CPUWeight;
- a disk reservation;
- the root-control socket and finite-build deadlines.

Before remote execution, image-build captures those exact pin bytes into build-record provenance and rejects a digest mismatch. A lane has its own project root and state:

```text
/var/lib/zog/image-build-lanes/<lane>/
    controller.json
    source/
    state/
        image-build/
        build-job/
        build-resource/
```

Mutable pipeline, attempt, generation and controller state is never shared between
lanes. The host/root-control daemon, archive-mirror and underlying EC2 hardware may be
shared.

## Existing Work lane

An already-running Work-owned project can be represented without host-deploy
modifying it. Use lane `mode: "reservation"` with that project's actual absolute
root and reserve the memory/disk budget that leading-edge work may need.

Activating a reservation-only lane performs admission accounting only: it does not
create directories, upload `controller.json`, change the Work source checkout, or
enable remote operations for that lane. This is the recommended transition for the
current `zog-compiler-view` project while the regular-chat rebuild uses a new
`mode: "managed"` lane.

## Commands

Prepare a durable lane specification without touching the host:

```sh
host-deploy lane-prepare --workspace HOST --lane rebuild-oct1 --spec lane.json
```

Activate it after capacity admission:

```sh
host-deploy lane-activate --workspace HOST --lane rebuild-oct1
```

Activation checks active lane memory/disk reservations against the observed host,
creates the project/state/source directories and installs a nonsecret controller
configuration. It does not fetch source or start a compiler.

Inspect or retire admission:

```sh
host-deploy lane-inspect --workspace HOST --lane rebuild-oct1
host-deploy lane-retire --workspace HOST --lane rebuild-oct1
```

Retirement does not delete state.

`lane-command` produces the exact argv for the image-build remote-operation adapter.
The command uses `PYTHONPATH=<lane-source>/src` so execution comes from the lane's
deployed source checkout, not an unrelated globally installed image-build.

## Scheduling

The finite build request supports optional systemd `CPUWeight` in addition to the
existing MemoryMax/TasksMax. Because one image-build lane serializes its pipeline
command checkpoints, per-job weight provides the initial lane scheduling priority.

A normal policy for concurrent development is:

- leading Work lane: larger CPU weight and memory reservation;
- clean/rebuild lane: lower CPU weight, bounded memory and lower compiler parallelism.

CPUWeight is work-conserving: the rebuild may use idle CPU but yields relative share
when leading-edge work is active.

Disk remains separately admitted because independent lanes retain independent roots,
attempts and generations. Cross-lane source-byte reuse should happen through
archive-mirror rather than writable cache/state sharing.

## Gateway boundary

SQS/GitHub authorization remains outside this module. The gateway may:

1. authorize and materialize an exact repository commit for a lane;
2. write a versioned image-build remote request;
3. execute the argv returned by `remote_operation_argv`;
4. publish the bounded JSON result;
5. repeat inspection/resume using the same lane and operation identities.

A dispatcher restart never authorizes a replacement image-build pipeline. Recovery is
performed by `zog.image_build.remote_operations` against durable lane state.

An existing Work project can be represented as a lane using its existing absolute
project root, provided its basename is unique. Preparing/recording that lane does not
move its state.
