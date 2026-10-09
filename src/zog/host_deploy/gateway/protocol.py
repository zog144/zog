"""Strict, side-effect-free v1 contract for the GitHub-to-EC2 gateway."""

from copy import deepcopy
from datetime import datetime
import hashlib
import json
import re
import uuid


SCHEMA = 1
MAXIMUM_REQUEST_BYTES = 16 * 1024
ORIGIN_REPOSITORY = "zog144/host-deploy"
SOURCE_REPOSITORIES = {"zog144/image-build"}

OPERATIONS = frozenset({
    "build.submit",
    "build.status",
    "build.resume",
    "build.cancel",
    "diagnostic.submit",
    "host.status",
})

# These are maintained image-build worker entry points. The later execution adapter
# owns all host paths and argv construction; requests select a name only.
BUILD_TASKS = frozenset({
    "stages",
    "native-stage",
    "glibc-final",
    "glibc-publish",
    "final-math",
    "final-compiler",
})

DIAGNOSTICS = frozenset({"host.runtime", "build.pipeline"})

INITIAL_STATES = {
    "acceptance": "received",
    "admission": "not_started",
    "dispatch": "not_started",
    "completion": "not_started",
    "reporting": "not_started",
}

STATE_VALUES = {
    "acceptance": {"received", "accepted", "rejected"},
    "admission": {"not_started", "pending", "admitted", "blocked"},
    "dispatch": {"not_started", "prepared", "submitted", "submission_uncertain"},
    "completion": {
        "not_started",
        "pending",
        "running",
        "completed",
        "failed",
        "timed_out",
        "cancelled",
        "recovery_blocked",
    },
    "reporting": {"not_started", "pending", "published", "failed"},
}

TRANSITIONS = {
    "acceptance": {
        "received": {"accepted", "rejected"},
    },
    "admission": {
        "not_started": {"pending"},
        "pending": {"admitted", "blocked"},
    },
    "dispatch": {
        "not_started": {"prepared"},
        "prepared": {"submitted", "submission_uncertain"},
        "submission_uncertain": {"submitted"},
    },
    "completion": {
        "not_started": {"pending"},
        "pending": {
            "running",
            "completed",
            "failed",
            "timed_out",
            "cancelled",
            "recovery_blocked",
        },
        "running": {
            "completed",
            "failed",
            "timed_out",
            "cancelled",
            "recovery_blocked",
        },
        "recovery_blocked": {
            "pending",
            "running",
            "completed",
            "failed",
            "timed_out",
            "cancelled",
        },
    },
    "reporting": {
        "not_started": {"pending"},
        "pending": {"published", "failed"},
        "published": {"pending"},
        "failed": {"pending"},
    },
}

_HEX_32 = re.compile(r"[0-9a-f]{32}")
_HEX_40 = re.compile(r"[0-9a-f]{40}")
_ACTOR = re.compile(r"[A-Za-z0-9-]+(?:\[bot\])?")
_LANE = re.compile(r"[a-z0-9][a-z0-9-]{0,47}")
_TIMESTAMP = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z"
)


class RequestProtocolError(ValueError):
    """The request or durable protocol state violates the v1 contract."""


def _exact(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise RequestProtocolError(
            f"{name} fields must be exactly {sorted(fields)}"
        )


def _hex_identity(value, name):
    if not isinstance(value, str) or not _HEX_32.fullmatch(value):
        raise RequestProtocolError(f"{name} must be a canonical 32-hex identity")
    if uuid.UUID(value).hex != value:
        raise RequestProtocolError(f"{name} must be canonical")
    return value


def _pipeline_identity(value):
    if not isinstance(value, str) or not _HEX_32.fullmatch(value):
        raise RequestProtocolError("pipeline_id must be a canonical 32-hex identity")
    return value


def _commit(value):
    if not isinstance(value, str) or not _HEX_40.fullmatch(value):
        raise RequestProtocolError("source commit must be an exact lowercase 40-hex Git commit")
    return value


def _lane(value):
    if not isinstance(value, str) or not _LANE.fullmatch(value):
        raise RequestProtocolError("lane must be a canonical image-build lane name")
    return value


def _origin(value):
    _exact(value, {"repository", "issue_number", "trigger_actor"}, "origin")
    if value["repository"] != ORIGIN_REPOSITORY:
        raise RequestProtocolError("origin repository is not authorized by protocol v1")
    if type(value["issue_number"]) is not int or not 1 <= value["issue_number"] <= 2_147_483_647:
        raise RequestProtocolError("issue_number must be a positive bounded integer")
    actor = value["trigger_actor"]
    if (
        not isinstance(actor, str)
        or not 1 <= len(actor) <= 100
        or not _ACTOR.fullmatch(actor)
    ):
        raise RequestProtocolError("trigger_actor is not a valid bounded GitHub login")
    return value


def _source(value):
    _exact(value, {"repository", "commit"}, "source")
    if value["repository"] not in SOURCE_REPOSITORIES:
        raise RequestProtocolError("source repository is not approved by protocol v1")
    _commit(value["commit"])
    return value


def _parameters(operation, value):
    if not isinstance(value, dict):
        raise RequestProtocolError("parameters must be an object")
    if operation == "build.submit":
        _exact(value, {"lane", "task"}, "parameters")
        _lane(value["lane"])
        if value["task"] not in BUILD_TASKS:
            raise RequestProtocolError("unknown build task")
    elif operation in {"build.status", "build.resume", "build.cancel"}:
        _exact(value, {"lane", "pipeline_id"}, "parameters")
        _lane(value["lane"])
        _pipeline_identity(value["pipeline_id"])
    elif operation == "diagnostic.submit":
        if value.get("diagnostic") == "host.runtime":
            _exact(value, {"diagnostic"}, "parameters")
        elif value.get("diagnostic") == "build.pipeline":
            _exact(value, {"diagnostic", "lane", "pipeline_id"}, "parameters")
            _lane(value["lane"])
            _pipeline_identity(value["pipeline_id"])
        else:
            raise RequestProtocolError("unknown diagnostic")
    elif operation == "host.status":
        _exact(value, set(), "parameters")
    else:
        raise RequestProtocolError("unknown operation")
    return value


def canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def validate_request(value):
    """Validate and return a detached canonical v1 request value."""
    if not isinstance(value, dict):
        raise RequestProtocolError("request must be an object")
    operation = value.get("operation")
    if operation not in OPERATIONS:
        raise RequestProtocolError("unknown operation")
    expected = {
        "schema",
        "request_id",
        "workspace_id",
        "operation",
        "origin",
        "parameters",
    }
    if operation == "build.submit":
        expected.add("source")
    _exact(value, expected, "request")
    if value["schema"] != SCHEMA or type(value["schema"]) is not int:
        raise RequestProtocolError("unsupported request schema")
    _hex_identity(value["request_id"], "request_id")
    _hex_identity(value["workspace_id"], "workspace_id")
    _origin(value["origin"])
    _parameters(operation, value["parameters"])
    if operation == "build.submit":
        _source(value["source"])
    detached = deepcopy(value)
    if len(canonical_bytes(detached)) > MAXIMUM_REQUEST_BYTES:
        raise RequestProtocolError("request exceeds protocol size limit")
    return detached


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise RequestProtocolError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def loads_request(data):
    """Parse JSON while rejecting duplicate keys and non-finite numbers."""
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            raise RequestProtocolError("request JSON must be UTF-8") from None
    if not isinstance(data, str):
        raise RequestProtocolError("request JSON must be text or bytes")
    if len(data.encode("utf-8")) > MAXIMUM_REQUEST_BYTES:
        raise RequestProtocolError("request exceeds protocol size limit")
    try:
        value = json.loads(
            data,
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                RequestProtocolError(f"non-finite JSON number: {value}")
            ),
        )
    except RequestProtocolError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError):
        raise RequestProtocolError("invalid request JSON") from None
    return validate_request(value)


def request_digest(request):
    return hashlib.sha256(canonical_bytes(validate_request(request))).hexdigest()


def _timestamp(value):
    if not isinstance(value, str) or not _TIMESTAMP.fullmatch(value):
        raise RequestProtocolError("transition time must be RFC3339 UTC")
    try:
        return datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    except ValueError:
        raise RequestProtocolError("transition time must be RFC3339 UTC") from None


def new_state(request):
    request = validate_request(request)
    return {
        "schema": SCHEMA,
        "request_id": request["request_id"],
        "request_sha256": request_digest(request),
        "request": request,
        "states": dict(INITIAL_STATES),
        "history": [],
    }


def _apply(states, stage, target):
    if stage not in STATE_VALUES:
        raise RequestProtocolError("unknown state stage")
    if target not in STATE_VALUES[stage]:
        raise RequestProtocolError(f"unknown {stage} state")
    current = states[stage]
    if target not in TRANSITIONS.get(stage, {}).get(current, set()):
        raise RequestProtocolError(f"invalid {stage} transition {current} -> {target}")

    if stage == "admission" and target == "pending":
        if states["acceptance"] != "accepted":
            raise RequestProtocolError("admission requires accepted request")
    elif stage == "dispatch" and target == "prepared":
        if states["admission"] != "admitted":
            raise RequestProtocolError("dispatch requires admitted request")
    elif stage == "completion" and target == "pending":
        if states["dispatch"] != "submitted":
            raise RequestProtocolError("completion requires confirmed dispatch")
    elif stage == "reporting" and target == "pending":
        if states["acceptance"] == "received":
            raise RequestProtocolError("reporting requires an acceptance decision")

    states[stage] = target
    return current


def validate_state(record):
    """Validate a durable state record by replaying its transition history."""
    _exact(
        record,
        {"schema", "request_id", "request_sha256", "request", "states", "history"},
        "state record",
    )
    if record["schema"] != SCHEMA or type(record["schema"]) is not int:
        raise RequestProtocolError("unsupported state schema")
    request = validate_request(record["request"])
    if record["request_id"] != request["request_id"]:
        raise RequestProtocolError("state request identity mismatch")
    if record["request_sha256"] != request_digest(request):
        raise RequestProtocolError("state request digest mismatch")
    _exact(record["states"], INITIAL_STATES, "states")
    for stage, value in record["states"].items():
        if value not in STATE_VALUES[stage]:
            raise RequestProtocolError(f"unknown {stage} state")
    if not isinstance(record["history"], list) or len(record["history"]) > 1000:
        raise RequestProtocolError("invalid transition history")

    replay = dict(INITIAL_STATES)
    previous_time = None
    for entry in record["history"]:
        _exact(entry, {"stage", "from", "to", "at"}, "history entry")
        parsed_time = _timestamp(entry["at"])
        if previous_time is not None and parsed_time < previous_time:
            raise RequestProtocolError("transition history is not chronological")
        previous_time = parsed_time
        stage = entry["stage"]
        if stage not in replay or entry["from"] != replay[stage]:
            raise RequestProtocolError("transition history source state mismatch")
        before = _apply(replay, stage, entry["to"])
        if before != entry["from"]:
            raise RequestProtocolError("transition history mismatch")
    if replay != record["states"]:
        raise RequestProtocolError("state snapshot differs from transition history")
    return deepcopy(record)


def transition(record, stage, target, at):
    """Return a new durable state record with one validated transition appended."""
    result = validate_state(record)
    parsed_time = _timestamp(at)
    if result["history"] and parsed_time < _timestamp(result["history"][-1]["at"]):
        raise RequestProtocolError("transition history is not chronological")
    if len(result["history"]) >= 1000:
        raise RequestProtocolError("transition history limit reached")
    before = _apply(result["states"], stage, target)
    result["history"].append(
        {"stage": stage, "from": before, "to": target, "at": at}
    )
    return result
