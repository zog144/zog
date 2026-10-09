# Controller integration

This delivery rebases the workspace launch-parameter changes onto the supplied
`zog-build-visibility-pass11` tree, preserving its journal and build-visibility work.
The combined kit includes a focused patch against the unmodified pass11 input.

Added/extended API:

```python
launch_application(application_name, *, request_id=None, parameters=None)
request_application_launch(application_name, *, request_id=None, parameters=None)
cancel_application_launch(application_name, *, request_id, parameters=None)
observe_application_runtime(runtime_id)
```

`parameters` is a mapping of declared names to strings or integers. Booleans are not
integers here. All declared values are required; unknown names are rejected. Definitions
may set integer minimum/maximum or explicit choices. Parameterized applications are
externally-controlled. Bindings target complete non-executable command arguments or
explicit environment keys, with no shell expansion or general interpolation.

`ProgramSpec.command_parameters` maps argument index to parameter name;
`environment_parameters` maps environment key to parameter name. Example:

```python
application(
    name="example",
    launch_parameters={"port": {"type": "integer", "minimum": 1024, "maximum": 65535}},
    programs=(program(name="server", command=("/usr/bin/server", "--port", "0"),
        command_parameters={2: "port"}),),
)
```

Resolved commands/environment and typed inputs are frozen in authoritative operation
records. Inputs are also saved in runtime references so explicit restart can preserve
them after operation retention. Pending requests and results retain parameters for
intent comparison. Reusing a request ID with changed parameters is rejected.
Recovery executes its original snapshot even if declarations change later.

`cancel_application_launch` never issues a new launch. Under the project lock, it
recovers accepted operations, returns a matching runtime if present, or durably abandons
an unstarted request. With expired identity and no adequate evidence it refuses ambiguity.

`observe_application_runtime` reads current systemd facts for one recorded runtime
without acquiring the mutation lock, launching, repairing, or persisting observation.
It now returns the pass11 dictionary snapshot, not a runtime reference. This
allows connection authorization to notice process exit without running full evaluation.

The station-access gateway remains the only module that depends on concrete controller
types. Existing declaration files are not edited by station-access at runtime.
