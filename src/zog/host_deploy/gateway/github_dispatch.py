"""GitHub issue authorization, request extraction, and bounded SQS submission."""

import argparse
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from .protocol import (
    MAXIMUM_REQUEST_BYTES,
    ORIGIN_REPOSITORY,
    RequestProtocolError,
    canonical_bytes,
    request_digest,
    validate_request,
)


ISSUE_MARKER = "<!-- zog-gateway-request:v1 -->"
MAXIMUM_ISSUE_BODY_BYTES = 24 * 1024
AWS_REGION = "us-east-1"
QUEUE_NAME = "zog-build-requests.fifo"
_ACTOR = re.compile(r"[A-Za-z0-9-]+(?:\[bot\])?")
_ACCOUNT_ID = re.compile(r"[0-9]{12}")


class GitHubDispatchError(RequestProtocolError):
    """A GitHub event or dispatch setting violates the gateway trust boundary."""


def load_authorized_actors(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise GitHubDispatchError("invalid authorized actor file") from None
    if not isinstance(value, dict) or set(value) != {"schema", "actors"}:
        raise GitHubDispatchError("authorized actor file has unknown fields")
    if value["schema"] != 1 or type(value["schema"]) is not int:
        raise GitHubDispatchError("unsupported authorized actor schema")
    actors = value["actors"]
    if (
        not isinstance(actors, list)
        or not actors
        or len(actors) > 32
        or len(set(actors)) != len(actors)
    ):
        raise GitHubDispatchError("authorized actor list is invalid")
    for actor in actors:
        if (
            not isinstance(actor, str)
            or not 1 <= len(actor) <= 100
            or not _ACTOR.fullmatch(actor)
        ):
            raise GitHubDispatchError("authorized actor login is invalid")
    return frozenset(actors)


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise GitHubDispatchError(f"duplicate JSON field: {key}")
        value[key] = item
    return value


def extract_issue_intent(body):
    if not isinstance(body, str):
        raise GitHubDispatchError("issue body is missing")
    raw = body.encode("utf-8")
    if len(raw) > MAXIMUM_ISSUE_BODY_BYTES:
        raise GitHubDispatchError("issue body exceeds gateway size limit")
    normalized = body.replace("\r\n", "\n").strip()
    prefix = ISSUE_MARKER + "\n```json\n"
    suffix = "\n```"
    if not normalized.startswith(prefix) or not normalized.endswith(suffix):
        raise GitHubDispatchError("issue body must contain only the v1 request envelope")
    request_text = normalized[len(prefix):-len(suffix)]
    if "```" in request_text:
        raise GitHubDispatchError("nested code fences are not allowed")
    try:
        intent = json.loads(
            request_text,
            object_pairs_hook=_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                GitHubDispatchError(f"non-finite JSON number: {value}")
            ),
        )
    except GitHubDispatchError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError):
        raise GitHubDispatchError("invalid request JSON") from None
    if not isinstance(intent, dict) or "origin" in intent:
        raise GitHubDispatchError("issue intent must omit origin")
    return intent


def prepare_event(event, authorized_actors):
    if not isinstance(event, dict):
        raise GitHubDispatchError("GitHub event must be an object")
    if event.get("action") != "opened":
        raise GitHubDispatchError("gateway accepts only issue-opened events")
    repository = event.get("repository")
    issue = event.get("issue")
    sender = event.get("sender")
    if not isinstance(repository, dict) or repository.get("full_name") != ORIGIN_REPOSITORY:
        raise GitHubDispatchError("GitHub event repository mismatch")
    if not isinstance(issue, dict) or issue.get("state") != "open":
        raise GitHubDispatchError("gateway issue must be open")
    if not isinstance(sender, dict):
        raise GitHubDispatchError("GitHub event sender is missing")
    actor = sender.get("login")
    if actor not in authorized_actors:
        raise GitHubDispatchError("GitHub triggering actor is not authorized")
    issue_user = issue.get("user")
    if not isinstance(issue_user, dict) or issue_user.get("login") != actor:
        raise GitHubDispatchError("issue creator differs from triggering actor")
    issue_number = issue.get("number")
    if type(issue_number) is not int or issue_number < 1:
        raise GitHubDispatchError("GitHub issue number is invalid")
    intent = extract_issue_intent(issue.get("body"))
    request = dict(intent)
    request["origin"] = {
        "repository": ORIGIN_REPOSITORY,
        "issue_number": issue_number,
        "trigger_actor": actor,
    }
    return validate_request(request)


def load_event(path, actors_path):
    try:
        event = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise GitHubDispatchError("invalid GitHub event JSON") from None
    return prepare_event(event, load_authorized_actors(actors_path))


def write_prepared_request(path, request):
    request = validate_request(request)
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(destination, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(canonical_bytes(request) + b"\n")
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        try:
            destination.unlink()
        except FileNotFoundError:
            pass
        raise
    return destination


def validate_queue_url(value):
    if not isinstance(value, str) or len(value) > 512:
        raise GitHubDispatchError("SQS queue URL is invalid")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "sqs.us-east-1.amazonaws.com"
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GitHubDispatchError("SQS queue URL must be the us-east-1 primary queue")
    parts = parsed.path.split("/")
    if (
        len(parts) != 3
        or parts[0] != ""
        or not _ACCOUNT_ID.fullmatch(parts[1])
        or parts[2] != QUEUE_NAME
    ):
        raise GitHubDispatchError("SQS queue URL must name zog-build-requests.fifo")
    return value


def submit_request(queue_url, request, client=None):
    queue_url = validate_queue_url(queue_url)
    request = validate_request(request)
    if client is None:
        import boto3
        client = boto3.client("sqs", region_name=AWS_REGION)
    response = client.send_message(
        QueueUrl=queue_url,
        MessageBody=canonical_bytes(request).decode("ascii"),
        MessageGroupId=request["workspace_id"],
        MessageDeduplicationId=request["request_id"],
    )
    message_id = response.get("MessageId")
    sequence = response.get("SequenceNumber")
    if (
        not isinstance(message_id, str)
        or not 1 <= len(message_id) <= 200
        or not isinstance(sequence, str)
        or not 1 <= len(sequence) <= 200
    ):
        raise GitHubDispatchError("SQS did not return a complete FIFO receipt")
    return {
        "request_id": request["request_id"],
        "request_sha256": request_digest(request),
        "message_id": message_id,
        "sequence_number": sequence,
    }


def summary(request):
    request = validate_request(request)
    value = {
        "request_id": request["request_id"],
        "workspace_id": request["workspace_id"],
        "operation": request["operation"],
        "issue_number": request["origin"]["issue_number"],
    }
    if "source" in request:
        value["source_repository"] = request["source"]["repository"]
        value["source_commit"] = request["source"]["commit"]
    return value


def main(argv=None):
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--event", required=True)
    prepare.add_argument("--actors", required=True)
    prepare.add_argument("--output", required=True)

    submit = commands.add_parser("submit")
    submit.add_argument("--request", required=True)
    submit.add_argument("--queue-url", required=True)

    arguments = parser.parse_args(argv)
    if arguments.command == "prepare":
        request = load_event(arguments.event, arguments.actors)
        write_prepared_request(arguments.output, request)
        print(json.dumps(summary(request), sort_keys=True))
        return

    from .protocol import loads_request
    request = loads_request(Path(arguments.request).read_bytes())
    print(json.dumps(submit_request(arguments.queue_url, request), sort_keys=True))


if __name__ == "__main__":
    main()
