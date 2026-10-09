import json
import uuid

import pytest

from zog.host_deploy.gateway.protocol import (
    BUILD_TASKS,
    RequestProtocolError,
    loads_request,
    new_state,
    request_digest,
    transition,
    validate_request,
    validate_state,
)


REQUEST_ID = "0123456789abcdef0123456789abcdef"
WORKSPACE_ID = "fedcba9876543210fedcba9876543210"
PIPELINE_ID = "11111111111111111111111111111111"
COMMIT = "2" * 40
ORIGIN = {
    "repository": "zog144/host-deploy",
    "issue_number": 17,
    "trigger_actor": "zog144",
}


def request(operation, parameters, **extra):
    value = {
        "schema": 1,
        "request_id": REQUEST_ID,
        "workspace_id": WORKSPACE_ID,
        "operation": operation,
        "origin": dict(ORIGIN),
        "parameters": parameters,
    }
    value.update(extra)
    return value


def submit(task="final-compiler"):
    return request(
        "build.submit",
        {"lane": "rebuild-oct1", "task": task},
        source={"repository": "zog144/image-build", "commit": COMMIT},
    )


@pytest.mark.parametrize("task", sorted(BUILD_TASKS))
def test_all_approved_build_tasks_are_valid(task):
    assert validate_request(submit(task))["parameters"]["task"] == task


@pytest.mark.parametrize(
    "operation,parameters",
    [
        ("build.status", {"lane": "rebuild-oct1", "pipeline_id": PIPELINE_ID}),
        ("build.resume", {"lane": "rebuild-oct1", "pipeline_id": PIPELINE_ID}),
        ("build.cancel", {"lane": "rebuild-oct1", "pipeline_id": PIPELINE_ID}),
        ("diagnostic.submit", {"diagnostic": "host.runtime"}),
        (
            "diagnostic.submit",
            {"diagnostic": "build.pipeline", "lane": "rebuild-oct1", "pipeline_id": PIPELINE_ID},
        ),
        ("host.status", {}),
    ],
)
def test_non_submit_operations_are_strict_and_do_not_accept_source(operation, parameters):
    value = request(operation, parameters)
    assert validate_request(value) == value
    value["source"] = {"repository": "zog144/image-build", "commit": COMMIT}
    with pytest.raises(RequestProtocolError):
        validate_request(value)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(extra="field"),
        lambda value: value.update(operation="shell.run"),
        lambda value: value["parameters"].update(command=["sh", "-c", "id"]),
        lambda value: value["parameters"].update(environment={"X": "1"}),
        lambda value: value["source"].update(repository="attacker/example"),
        lambda value: value["source"].update(commit="unstable"),
        lambda value: value["origin"].update(repository="zog144/image-build"),
        lambda value: value["origin"].update(issue_number=0),
        lambda value: value["origin"].update(untrusted=True),
    ],
)
def test_submit_rejects_unknown_fields_arbitrary_execution_and_untrusted_identity(change):
    value = submit()
    change(value)
    with pytest.raises(RequestProtocolError):
        validate_request(value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "not-a-uuid"),
        ("request_id", REQUEST_ID.upper()),
        ("workspace_id", "0" * 31),
        ("workspace_id", WORKSPACE_ID.upper()),
    ],
)
def test_request_and_workspace_identities_are_canonical(field, value):
    item = submit()
    item[field] = value
    with pytest.raises(RequestProtocolError):
        validate_request(item)


def test_issue_actor_is_bounded_syntax_not_authorization():
    item = submit()
    item["origin"]["trigger_actor"] = "release-bot[bot]"
    validate_request(item)
    for actor in ("", "bad actor", "_" * 10, "x" * 101):
        item["origin"]["trigger_actor"] = actor
        with pytest.raises(RequestProtocolError):
            validate_request(item)


def test_json_parser_rejects_duplicate_fields_and_non_finite_values():
    raw = json.dumps(submit())
    assert loads_request(raw) == submit()
    duplicate = raw[:-1] + ',"operation":"host.status"}'
    with pytest.raises(RequestProtocolError, match="duplicate"):
        loads_request(duplicate)
    with pytest.raises(RequestProtocolError):
        loads_request('{"schema":NaN}')


def test_request_digest_is_canonical_and_input_is_detached():
    first = submit()
    second = dict(reversed(list(first.items())))
    assert request_digest(first) == request_digest(second)
    validated = validate_request(first)
    validated["parameters"]["task"] = "changed"
    assert first["parameters"]["task"] == "final-compiler"


def test_initial_state_binds_exact_request_and_has_separate_stages():
    state = new_state(submit())
    assert state["request_id"] == REQUEST_ID
    assert state["request_sha256"] == request_digest(submit())
    assert state["states"] == {
        "acceptance": "received",
        "admission": "not_started",
        "dispatch": "not_started",
        "completion": "not_started",
        "reporting": "not_started",
    }
    assert validate_state(state) == state


def advance_to_running():
    state = new_state(submit())
    state = transition(state, "acceptance", "accepted", "2026-10-08T17:00:00Z")
    state = transition(state, "admission", "pending", "2026-10-08T17:00:01Z")
    state = transition(state, "admission", "admitted", "2026-10-08T17:00:02Z")
    state = transition(state, "dispatch", "prepared", "2026-10-08T17:00:03Z")
    state = transition(state, "dispatch", "submitted", "2026-10-08T17:00:04Z")
    state = transition(state, "completion", "pending", "2026-10-08T17:00:05Z")
    return transition(state, "completion", "running", "2026-10-08T17:00:06Z")


def test_happy_path_preserves_independent_reporting_state():
    state = advance_to_running()
    state = transition(state, "reporting", "pending", "2026-10-08T17:00:07Z")
    state = transition(state, "reporting", "published", "2026-10-08T17:00:08Z")
    state = transition(state, "completion", "completed", "2026-10-08T17:00:09Z")
    state = transition(state, "reporting", "pending", "2026-10-08T17:00:10Z")
    state = transition(state, "reporting", "published", "2026-10-08T17:00:11Z")
    assert state["states"]["completion"] == "completed"
    assert state["states"]["reporting"] == "published"
    assert validate_state(state) == state


def test_submission_uncertainty_must_reconcile_before_execution():
    state = new_state(submit())
    state = transition(state, "acceptance", "accepted", "2026-10-08T17:00:00Z")
    state = transition(state, "admission", "pending", "2026-10-08T17:00:01Z")
    state = transition(state, "admission", "admitted", "2026-10-08T17:00:02Z")
    state = transition(state, "dispatch", "prepared", "2026-10-08T17:00:03Z")
    state = transition(
        state, "dispatch", "submission_uncertain", "2026-10-08T17:00:04Z"
    )
    with pytest.raises(RequestProtocolError, match="confirmed dispatch"):
        transition(state, "completion", "pending", "2026-10-08T17:00:05Z")
    state = transition(state, "dispatch", "submitted", "2026-10-08T17:00:06Z")
    transition(state, "completion", "pending", "2026-10-08T17:00:07Z")


def test_recovery_blocked_is_explicit_and_recoverable_without_rebinding():
    state = advance_to_running()
    state = transition(
        state, "completion", "recovery_blocked", "2026-10-08T17:00:07Z"
    )
    resumed = transition(state, "completion", "running", "2026-10-08T17:00:08Z")
    assert resumed["request_sha256"] == state["request_sha256"]
    assert resumed["request"] == state["request"]


def test_rejected_and_blocked_requests_can_be_reported_without_dispatch():
    rejected = new_state(submit())
    rejected = transition(
        rejected, "acceptance", "rejected", "2026-10-08T17:00:00Z"
    )
    rejected = transition(
        rejected, "reporting", "pending", "2026-10-08T17:00:01Z"
    )
    assert rejected["states"]["dispatch"] == "not_started"

    blocked = new_state(submit())
    blocked = transition(
        blocked, "acceptance", "accepted", "2026-10-08T17:00:00Z"
    )
    blocked = transition(blocked, "admission", "pending", "2026-10-08T17:00:01Z")
    blocked = transition(blocked, "admission", "blocked", "2026-10-08T17:00:02Z")
    blocked = transition(blocked, "reporting", "pending", "2026-10-08T17:00:03Z")
    assert blocked["states"]["dispatch"] == "not_started"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda state: state["request"].update(workspace_id=uuid.uuid4().hex),
        lambda state: state["states"].update(dispatch="submitted"),
        lambda state: state["history"].append(
            {
                "stage": "dispatch",
                "from": "not_started",
                "to": "submitted",
                "at": "2026-10-08T17:00:00Z",
            }
        ),
    ],
)
def test_state_tampering_is_detected(mutate):
    state = new_state(submit())
    mutate(state)
    with pytest.raises(RequestProtocolError):
        validate_state(state)


def test_stage_order_and_timestamp_order_are_enforced():
    state = new_state(submit())
    with pytest.raises(RequestProtocolError):
        transition(state, "dispatch", "prepared", "2026-10-08T17:00:00Z")
    state = transition(state, "acceptance", "accepted", "2026-10-08T17:00:02Z")
    with pytest.raises(RequestProtocolError, match="chronological"):
        transition(state, "admission", "pending", "2026-10-08T17:00:01Z")


def test_fractional_rfc3339_timestamps_use_time_order_not_string_order():
    state = new_state(submit())
    state = transition(state, "acceptance", "accepted", "2026-10-08T17:00:00Z")
    state = transition(state, "admission", "pending", "2026-10-08T17:00:00.1Z")
    assert state["states"]["admission"] == "pending"

    later = new_state(submit())
    later = transition(later, "acceptance", "accepted", "2026-10-08T17:00:00.9Z")
    with pytest.raises(RequestProtocolError, match="chronological"):
        transition(later, "admission", "pending", "2026-10-08T17:00:00.10Z")


def test_build_operations_require_lane_routing():
    for value in (
        request("build.status", {"pipeline_id": PIPELINE_ID}),
        request("build.resume", {"pipeline_id": PIPELINE_ID}),
        request("build.cancel", {"pipeline_id": PIPELINE_ID}),
        request("diagnostic.submit", {"diagnostic": "build.pipeline", "pipeline_id": PIPELINE_ID}),
    ):
        with pytest.raises(RequestProtocolError, match="fields"):
            validate_request(value)
    bad = submit()
    bad["parameters"]["lane"] = "Bad Lane"
    with pytest.raises(RequestProtocolError, match="lane"):
        validate_request(bad)
