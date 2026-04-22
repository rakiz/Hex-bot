import hashlib
import hmac
import time

from flask import Flask
from hex_bot.slack_client import verify_slack_signature

TEST_SECRET = "test_signing_secret"
TEST_BODY = '{"type":"event_callback"}'


def _make_request(body: str, signing_secret: str = TEST_SECRET, timestamp: int = None):
    """
    Build a fake Flask request signed with signing_secret.
    The config is always set to TEST_SECRET — so passing a different signing_secret
    simulates a request signed with the wrong key.
    """
    app = Flask(__name__)
    ts = str(timestamp or int(time.time()))
    basestring = f"v0:{ts}:{body}".encode("utf-8")
    sig = "v0=" + hmac.new(signing_secret.encode(), basestring, hashlib.sha256).hexdigest()

    with app.test_request_context(
        "/slack/events",
        method="POST",
        data=body,
        headers={
            "X-Slack-Request-Timestamp": ts,
            "X-Slack-Signature": sig,
            "Content-Type": "application/json",
        },
    ):
        from flask import request
        import hex_bot.slack_client as sc
        original = sc.Config.SLACK_SIGNING_SECRET
        sc.Config.SLACK_SIGNING_SECRET = TEST_SECRET
        result = verify_slack_signature(request)
        sc.Config.SLACK_SIGNING_SECRET = original
        return result


def test_valid_signature():
    assert _make_request(TEST_BODY, TEST_SECRET) is True


def test_wrong_secret():
    assert _make_request(TEST_BODY, signing_secret="wrong_secret") is False


def test_replayed_request():
    old_timestamp = int(time.time()) - 400  # older than 5 minutes
    assert _make_request(TEST_BODY, TEST_SECRET, timestamp=old_timestamp) is False
