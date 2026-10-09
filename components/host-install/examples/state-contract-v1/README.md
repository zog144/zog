# Synthetic STATE contract v1 fixture

`bundle.json` contains the four individual records; each separate JSON file
matches its bundle member. `scenarios.json` contains 19 test-only observations
and expected policy outcomes. All identifiers, provenance and authorization
facts are synthetic. There are no private keys or actual credentials.

Use `host-install state-validate bundle.json` for record validation. Use the
repository test suite to evaluate scenarios. Do not install these files on a
host or pass synthetic observations into an authorization service. The complete
schema, API boundaries and integration prerequisites are in
`../../docs/state-interface.md`.
