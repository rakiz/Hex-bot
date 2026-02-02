import time
import hmac
import hashlib
import logging
from typing import Optional

from flask import Request
from slack_sdk import WebClient

from config import Config

log = logging.getLogger(__name__)

slack = WebClient(token=Config.SLACK_BOT_TOKEN)

_bot_user_id: Optional[str] = Config.SLACK_BOT_USER_ID

def get_bot_user_id() -> str:
    """
    Resolve and cache Hex's Slack user ID (Uxxxxx) via auth.test if not provided.
    """
    global _bot_user_id
    if not _bot_user_id:
        resp = slack.auth_test()
        _bot_user_id = resp["user_id"]
        log.info("Resolved bot user id: %s", _bot_user_id)
    return _bot_user_id

def verify_slack_signature(request: Request) -> bool:
    """
    Verify Slack request signature to ensure the call is genuine.
    """
    timestamp = request.headers.get("X-Slack-Request-Timestamp")
    sig = request.headers.get("X-Slack-Signature")

    if not timestamp or not sig:
        log.warning("Missing Slack signature headers")
        return False

    # Basic replay protection
    if abs(time.time() - int(timestamp)) > 60 * 5:
        log.warning("Slack request timestamp too old")
        return False

    body = request.get_data(as_text=True)
    basestring = f"v0:{timestamp}:{body}".encode("utf-8")

    my_sig = "v0=" + hmac.new(
        Config.SLACK_SIGNING_SECRET.encode("utf-8"),
        basestring,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(my_sig, sig):
        log.warning("Slack signature mismatch")
        return False

    return True