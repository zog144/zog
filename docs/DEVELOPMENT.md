# Development source and build notes

The aggregate Python root is `src/zog`. Component support material is grouped under
`components/<program>`. Box-control's private nested project root is flattened in
this source export; station-access also has one component support directory.

## Build and inspect distributions

Use a disposable Python 3.12 environment with `build`, `twine` and test dependencies:

```sh
python -m build --outdir /tmp/zog-dist
python -m twine check --strict /tmp/zog-dist/*
```

The sdist deliberately contains more material than the wheel: component tests,
maintained docs, frontend source and recipes. Builds and dependencies belong outside
Git. These commands validate packages; they do not publish them.

## Component tests

Install the aggregate into a test environment first. Run suites separately from
their component directories to avoid same-named test-module collisions, for example:

```sh
cd components/build-record
python -m pytest tests
```

`pytest` is a development dependency, not a runtime requirement. Station-access uses
its Django test runner; frontend tests use npm. Privileged systemd, cloud and host
installation tests require an explicitly provisioned disposable environment. Do not
run acceptance/deployment helpers against live hosts merely to test packaging.

Repository-only namespace/CI tests and historical handoff-dependent tests are not
part of this export. Some retained component helpers and tests still expect their
original checkout layout or private source inputs; the aggregate packaging checks
do not claim complete component-suite or live-install acceptance. In particular,
the historical frontend installation helper requires a component-shaped checkout;
its adaptation to the aggregate and read-only application software workflow remains
separate from compiling the frontend source below.

## Frontend source build

Use the Node/npm versions in `components/station-access/frontend/toolchain.json`:

```sh
cd components/station-access/frontend
npm ci
npm run test:licenses
npm run build
```

The build verifies third-party notice evidence and creates a notice-linked bundle.
Do not commit `dist` or `node_modules`. A successful frontend build does not activate
an application. Image-build must stage Python dependencies, compiled frontend and
notices into immutable application software before box-control launches it.

## Recipe and deployment limits

The image-build catalogue records the reviewed source snapshot's build metadata;
it is not a claim that every recipe has live acceptance or complete licensing review.
Some historical host-enrollment recipes still obtain earlier private component
sources. A public end-to-end rootfs build requires new public aggregate source inputs
and acceptance. Keep existing pins, build records and generations immutable.

Component examples and service descriptors are configuration/build inputs. Replace
all cloud identifiers and domains deliberately. Do not treat them as an automatic
installation or a tested deployment for your machine.
