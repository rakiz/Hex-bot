from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet
from pymongo import MongoClient, ASCENDING
from pymongo.errors import DuplicateKeyError

from config import Config

log = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_fernet: Optional[Fernet] = None


def _get_db():
    global _client
    if _client is None:
        _client = MongoClient(Config.MONGODB_URI)
        db = _client[Config.MONGODB_DB_NAME]

        # TTL index: Slack event IDs are kept for 10 minutes to deduplicate retries.
        # MongoDB automatically deletes documents after expireAfterSeconds.
        db.events.create_index("created_at", expireAfterSeconds=600)

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
