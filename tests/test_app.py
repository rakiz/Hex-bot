import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

import hex_bot.slack_client as slack_module
from hex_bot.app import create_app

TEST_SECRET = "test_signing_secret"


@pytest.fixture
def app():
    with patch("hex_bot.app.scheduler.start"):
        return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


def test_scheduler_started_on_create_app():
    with patch("hex_bot.app.scheduler.start") as mock_start:
        create_app()
    mock_start.assert_called_once()


def _signed_headers(body: str, secret: str = TEST_SECRET, timestamp: int = None) -> dict:
    ts = str(timestamp or int(time.time()))
    basestring = f"v0:{ts}:{body}".encode()
    sig = "v0=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
        "Content-Type": "application/json",
    }


def _post_slack(client, body: dict, secret: str = TEST_SECRET):
    raw = json.dumps(body)
    original = slack_module.Config.SLACK_SIGNING_SECRET
    slack_module.Config.SLACK_SIGNING_SECRET = TEST_SECRET
    try:
        return client.post("/slack/events", data=raw, headers=_signed_headers(raw, secret))
    finally:
        slack_module.Config.SLACK_SIGNING_SECRET = original


# ---------------------------------------------------------------------------
# /healthz
# ---------------------------------------------------------------------------

def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.data == b"ok"


# ---------------------------------------------------------------------------
# /slack/events — signature
# ---------------------------------------------------------------------------

def test_slack_events_invalid_signature_rejected(client):
    resp = client.post(
        "/slack/events",
        data="{}",
        content_type="application/json",
        headers={"X-Slack-Request-Timestamp": "123", "X-Slack-Signature": "v0=bad"},
    )
    assert resp.status_code == 403


def test_slack_events_url_verification(client):
    body = {"type": "url_verification", "challenge": "abc123"}
    resp = _post_slack(client, body)
    assert resp.status_code == 200
    assert resp.get_json()["challenge"] == "abc123"


def test_slack_events_duplicate_ignored(client):
    body = {"type": "event_callback", "event_id": "Ev_dup", "event": {}}
    with patch("hex_bot.app.is_duplicate_event", return_value=True):
        resp = _post_slack(client, body)
    assert resp.status_code == 200


def test_slack_events_app_mention_starts_thread(client):
    body = {
        "type": "event_callback",
        "event_id": "Ev_new",
        "event": {"type": "app_mention", "channel": "C1", "user": "U1", "ts": "1.0", "text": "hi"},
    }
    with patch("hex_bot.app.is_duplicate_event", return_value=False), \
         patch("hex_bot.app.threading.Thread") as mock_thread:
        mock_thread.return_value = MagicMock()
        resp = _post_slack(client, body)
    assert resp.status_code == 200
    mock_thread.assert_called_once()
    assert mock_thread.call_args[1]["daemon"] is True


# ---------------------------------------------------------------------------
# /oauth/google/callback
# ---------------------------------------------------------------------------

def test_oauth_callback_google_error(client):
    resp = client.get("/oauth/google/callback?error=access_denied")
    assert resp.status_code == 400
    assert b"access_denied" in resp.data


def test_oauth_callback_missing_state(client):
    resp = client.get("/oauth/google/callback?code=abc")
    assert resp.status_code == 400


def test_oauth_callback_missing_code(client):
    resp = client.get("/oauth/google/callback?state=xyz")
    assert resp.status_code == 400


def test_oauth_callback_invalid_state(client):
    with patch("hex_bot.oauth.verify_state", side_effect=Exception("bad")):
        resp = client.get("/oauth/google/callback?code=abc&state=bad")
    assert resp.status_code == 400
    assert b"expired" in resp.data


def test_oauth_callback_exchange_fails(client):
    with patch("hex_bot.oauth.verify_state", return_value="U123"), \
         patch("hex_bot.oauth.exchange_code", side_effect=Exception("Google down")):
        resp = client.get("/oauth/google/callback?code=abc&state=valid")
    assert resp.status_code == 500


def test_oauth_callback_success_stores_token_and_sends_dm(client):
    with patch("hex_bot.oauth.verify_state", return_value="U123"), \
         patch("hex_bot.oauth.exchange_code", return_value="refresh_tok"), \
         patch("hex_bot.db.upsert_user") as mock_upsert, \
         patch("hex_bot.slack_client.slack") as mock_slack:
        resp = client.get("/oauth/google/callback?code=abc&state=valid")
    assert resp.status_code == 200
    assert b"Connected" in resp.data
    mock_upsert.assert_called_once_with("U123", "refresh_tok")
    mock_slack.chat_postMessage.assert_called_once()
    assert mock_slack.chat_postMessage.call_args[1]["channel"] == "U123"
