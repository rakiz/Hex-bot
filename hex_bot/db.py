from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, List

from cryptography.fernet import Fernet
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

from .config import Config

log = logging.getLogger(__name__)

_EVENT_DEDUP_TTL_SECONDS = 600  # keep event IDs for 10 minutes to deduplicate Slack retries

_client: Optional[MongoClient] = None
_fernet: Optional[Fernet] = None


def _get_db():
    global _client
    if _client is None:
        _client = MongoClient(Config.MONGODB_URI)
        db = _client[Config.MONGODB_DB_NAME]

        # TTL index: MongoDB automatically deletes documents after expireAfterSeconds.
        db.events.create_index("created_at", expireAfterSeconds=_EVENT_DEDUP_TTL_SECONDS)

        log.info("MongoDB connected (db=%s)", Config.MONGODB_DB_NAME)
    return _client[Config.MONGODB_DB_NAME]


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(Config.FERNET_KEY.encode())
    return _fernet


# ---------------------------------------------------------------------------
# Event deduplication
# ---------------------------------------------------------------------------

def is_duplicate_event(event_id: str) -> bool:
    """
    Returns True if this event_id was already seen (Slack retry).
    Inserts the event_id atomically — no race condition between check and insert.
    """
    try:
        _get_db().events.insert_one({
            "_id": event_id,
            "created_at": datetime.now(tz=timezone.utc),
        })
        return False
    except DuplicateKeyError:
        return True


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(slack_user_id: str) -> Optional[dict]:
    """Returns the user document (without decrypting the token) or None."""
    return _get_db().users.find_one({"_id": slack_user_id})


def get_refresh_token(slack_user_id: str) -> Optional[str]:
    """Returns the decrypted Google refresh token for a user, or None if not registered."""
    user = get_user(slack_user_id)
    if not user or not user.get("refresh_token_enc"):
        return None
    return _get_fernet().decrypt(user["refresh_token_enc"]).decode()


def upsert_user(
    slack_user_id: str,
    refresh_token: str,
    tasklist_name: Optional[str] = None,
) -> None:
    """Encrypts the refresh token and stores (or updates) the user record."""
    encrypted = _get_fernet().encrypt(refresh_token.encode())
    _get_db().users.update_one(
        {"_id": slack_user_id},
        {"$set": {
            "refresh_token_enc": encrypted,
            "tasklist_name": tasklist_name,
            "registered_at": datetime.now(tz=timezone.utc),
        }},
        upsert=True,
    )


def set_tasklist_name(slack_user_id: str, tasklist_name: Optional[str]) -> None:
    """Updates only the tasklist_name for an existing user."""
    _get_db().users.update_one(
        {"_id": slack_user_id},
        {"$set": {"tasklist_name": tasklist_name}},
    )


def delete_user(slack_user_id: str) -> None:
    """Removes all stored data for a user."""
    _get_db().users.delete_one({"_id": slack_user_id})


# ---------------------------------------------------------------------------
# Usage stats
# ---------------------------------------------------------------------------

def _week_key() -> str:
    return datetime.now(tz=timezone.utc).strftime("%G-W%V")


def record_tasks(
    *,
    sender_id: str,
    sender_name: str,
    successes: List[dict],   # [{"assignee_id": str, "assignee_name": str}, ...]
    error_types: List[str],  # ["unregistered_assignee", "google_api_error", ...]
) -> None:
    if not successes and not error_types:
        return

    week = _week_key()
    inc: dict = {}
    set_: dict = {}

    if successes:
        inc["tasks_created"] = len(successes)
        inc[f"senders.{sender_id}.count"] = len(successes)
        set_[f"senders.{sender_id}.name"] = sender_name
        for s in successes:
            aid, aname = s["assignee_id"], s["assignee_name"]
            inc[f"assignees.{aid}.count"] = inc.get(f"assignees.{aid}.count", 0) + 1
            set_[f"assignees.{aid}.name"] = aname

    if error_types:
        inc["tasks_failed"] = len(error_types)
        for etype in error_types:
            inc[f"errors.{etype}"] = inc.get(f"errors.{etype}", 0) + 1

    update: dict = {}
    if inc:
        update["$inc"] = inc
    if set_:
        update["$set"] = set_

    try:
        db = _get_db()
        db.stats.update_one({"_id": week}, update, upsert=True)
        doc = db.stats.find_one({"_id": week}) or {}
        db.stats.update_one(
            {"_id": week},
            {"$set": {
                "unique_senders": len(doc.get("senders", {})),
                "unique_assignees": len(doc.get("assignees", {})),
            }},
        )
    except Exception as exc:
        log.warning("Failed to record stats: %s", exc)


def init_week_stats() -> None:
    db = _get_db()
    week = _week_key()
    registered = db.users.count_documents({"refresh_token_enc": {"$exists": True}})
    doc = db.stats.find_one({"_id": week}) or {}
    db.stats.update_one(
        {"_id": week},
        {"$set": {
            "registered_users": registered,
            "unique_senders": len(doc.get("senders", {})),
            "unique_assignees": len(doc.get("assignees", {})),
        }},
        upsert=True,
    )
    log.info("Weekly stats: week=%s registered_users=%d", week, registered)
