import json
from pathlib import Path

import pytest

from zog.host_deploy.gateway.github_dispatch import (
    GitHubDispatchError,
    ISSUE_MARKER,
    extract_issue_intent,
    load_authorized_actors,
    prepare_event,
    submit_request,
    validate_queue_url,
)
from zog.host_deploy.gateway.protocol import canonical_bytes


REQUEST_ID = "0123456789abcdef0123456789abcdef"
WORKSPACE_ID = "fedcba9876543210fedcba9876543210"
COMMIT = "2" * 40


def intent():
    return {
        "schema": 1,
        "request_id": REQUEST_ID,
        "workspace_id": WORKSPACE_ID,
        "operation": "build.submit",
        "source": {
            "repository": "zog144/image-build",
            "commit": COMMIT,
        },
        "parameters": {"lane": "rebuild-oct1", "task": "final-compiler"},
    }


def request(issue=41, actor="zog144"):
    value = intent()
    value["origin"] = {
        "repository": "zog144/host-deploy",
        "issue_number": issue,
        "trigger_actor": actor,
    }
    return value


def body(value=None):
    value = intent() if value is None else value
    return ISSUE_MARKER + "\n```json\n" + json.dumps(value) + "\n```"


def event(value=None, actor="zog144", issue=41):
    return {
        "action": "opened",
        "repository": {"full_name": "zog144/host-deploy"},
        "sender": {"login": actor, "type": "User"},
        "issue": {
            "number": issue,
            "state": "open",
            "body": body(value),
            "user": {"login": actor},
        },
    }


def test_authorized_issue_event_binds_trusted_origin():
    assert prepare_event(event(), {"zog144"}) == request()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value["sender"].update(login="mallory"),
        lambda value: value["issue"]["user"].update(login="mallory"),
        lambda value: value["repository"].update(full_name="zog144/image-build"),
        lambda value: value.update(action="edited"),
        lambda value: value["issue"].update(state="closed"),
    ],
)
def test_event_identity_and_action_are_not_controlled_by_issue_body(mutate):
    value = event()
    mutate(value)
    with pytest.raises(GitHubDispatchError):
        prepare_event(value, {"zog144"})


def test_origin_is_constructed_from_event_and_forbidden_in_issue_content():
    prepared = prepare_event(event(), {"zog144"})
    assert prepared["origin"] == {
        "repository": "zog144/host-deploy",
        "issue_number": 41,
        "trigger_actor": "zog144",
    }
    with pytest.raises(GitHubDispatchError, match="omit origin"):
        prepare_event(event(request()), {"zog144"})


@pytest.mark.parametrize(
    "value",
    [
        "prose\n" + body(),
        body() + "\nprose",
        ISSUE_MARKER + "\n```json\n{}\n```\n```text\nextra\n```",
        ISSUE_MARKER + "\n{}",
    ],
)
def test_issue_body_is_a_single_strict_request_envelope(value):
    with pytest.raises(GitHubDispatchError):
        extract_issue_intent(value)


def test_authorized_actor_file_is_closed_and_no_wildcards(tmp_path):
    path = tmp_path / "actors.json"
    path.write_text(json.dumps({"schema": 1, "actors": ["zog144"]}))
    assert load_authorized_actors(path) == frozenset({"zog144"})
    for value in (
        {"schema": 1, "actors": ["*"]},
        {"schema": 1, "actors": ["zog144", "zog144"]},
        {"schema": 1, "actors": []},
        {"schema": 1, "actors": ["zog144"], "extra": True},
    ):
        path.write_text(json.dumps(value))
        with pytest.raises(GitHubDispatchError):
            load_authorized_actors(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://sqs.us-east-1.amazonaws.com/123456789012/zog-build-requests.fifo",
        "https://sqs.us-west-2.amazonaws.com/123456789012/zog-build-requests.fifo",
        "https://sqs.us-east-1.amazonaws.com/123/zog-build-requests.fifo",
        "https://sqs.us-east-1.amazonaws.com/123456789012/other.fifo",
        "https://example.com/123456789012/zog-build-requests.fifo",
    ],
)
def test_queue_url_is_fixed_to_primary_fifo(url):
    with pytest.raises(GitHubDispatchError):
        validate_queue_url(url)


class FakeSQS:
    def __init__(self):
        self.calls = []

    def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "message-1", "SequenceNumber": "12345"}


def test_sqs_submission_uses_workspace_group_and_request_deduplication():
    client = FakeSQS()
    value = request()
    url = "https://sqs.us-east-1.amazonaws.com/123456789012/zog-build-requests.fifo"
    receipt = submit_request(url, value, client)
    assert receipt["request_id"] == REQUEST_ID
    assert client.calls == [{
        "QueueUrl": url,
        "MessageBody": canonical_bytes(value).decode("ascii"),
        "MessageGroupId": WORKSPACE_ID,
        "MessageDeduplicationId": REQUEST_ID,
    }]


def test_sqs_incomplete_receipt_is_rejected():
    class Incomplete:
        def send_message(self, **kwargs):
            return {"MessageId": "message-1"}

    with pytest.raises(GitHubDispatchError, match="receipt"):
        submit_request(
            "https://sqs.us-east-1.amazonaws.com/123456789012/zog-build-requests.fifo",
            request(),
            Incomplete(),
        )


def test_workflow_orders_authorization_before_oidc_and_live_gate():
    text = (
        Path(__file__).resolve().parents[1]
        / ".github/workflows/gateway-issue-dispatch.yml"
    ).read_text()
    assert "pull_request_target" not in text
    assert "issues:" in text and "- opened" in text
    assert "id-token: write" in text
    assert "gateway-authorized-actors.json" in text
    assert "ZOG_GATEWAY_SUBMIT_ENABLED == 'true'" in text
    assert "aws-actions/configure-aws-credentials@v6.3.0" in text
    assert "AWS_ACCESS_KEY_ID" not in text
    assert text.index("Authorize actor and validate request") < text.index(
        "Configure short-lived AWS credentials"
    )
    assert text.index("Require AWS dispatch configuration") < text.index(
        "Configure short-lived AWS credentials"
    )
