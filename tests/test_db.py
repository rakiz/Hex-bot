import os
import pytest
from unittest.mock import patch
from hex_bot import db as db_module


@pytest.fixture(autouse=True)
def use_test_db(test_db):
    """Point the db module at the test database for every test in this file."""
    with patch.object(db_module, "_get_db", return_value=test_db):
        # Reset the Fernet singleton so it picks up the real FERNET_KEY from env
        db_module._fernet = None
        yield


class TestUsers:

    def test_upsert_and_get_user(self):
        db_module.upsert_user("U001", "my-refresh-token")
        user = db_module.get_user("U001")
        assert user is not None
        assert user["_id"] == "U001"
        assert user["tasklist_name"] is None

    def test_get_refresh_token_decrypts_correctly(self):
        db_module.upsert_user("U002", "secret-token")
        assert db_module.get_refresh_token("U002") == "secret-token"

    def test_upsert_with_tasklist_name(self):
        db_module.upsert_user("U003", "token", tasklist_name="my-list")
        user = db_module.get_user("U003")
        assert user["tasklist_name"] == "my-list"

    def test_upsert_is_idempotent(self):
        db_module.upsert_user("U004", "token-v1")
        db_module.upsert_user("U004", "token-v2")
        assert db_module.get_refresh_token("U004") == "token-v2"

    def test_set_tasklist_name(self):
        db_module.upsert_user("U005", "token")
        db_module.set_tasklist_name("U005", "new-list")
        assert db_module.get_user("U005")["tasklist_name"] == "new-list"

    def test_set_tasklist_name_to_none(self):
        db_module.upsert_user("U006", "token", tasklist_name="old-list")
        db_module.set_tasklist_name("U006", None)
        assert db_module.get_user("U006")["tasklist_name"] is None

    def test_delete_user(self):
        db_module.upsert_user("U007", "token")
        db_module.delete_user("U007")
        assert db_module.get_user("U007") is None

    def test_get_refresh_token_unknown_user_returns_none(self):
        assert db_module.get_refresh_token("U_UNKNOWN") is None


class TestEventDeduplication:

    def test_first_event_is_not_duplicate(self):
        assert db_module.is_duplicate_event("Ev001") is False

    def test_second_event_is_duplicate(self):
        db_module.is_duplicate_event("Ev002")
        assert db_module.is_duplicate_event("Ev002") is True

    def test_different_events_are_not_duplicates(self):
        assert db_module.is_duplicate_event("Ev003") is False
        assert db_module.is_duplicate_event("Ev004") is False


class TestStats:

    def _db(self):
        return db_module._get_db()

    def test_record_tasks_creates_week_document(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[{"assignee_id": "U2", "assignee_name": "Bob"}],
                error_types=[],
            )
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc is not None
        assert doc["tasks_created"] == 1
        assert doc["senders"]["U1"] == {"name": "Alice", "count": 1}
        assert doc["assignees"]["U2"] == {"name": "Bob", "count": 1}
        assert doc["unique_senders"] == 1
        assert doc["unique_assignees"] == 1

    def test_record_tasks_increments_on_second_call(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[{"assignee_id": "U2", "assignee_name": "Bob"}],
                error_types=[],
            )
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[{"assignee_id": "U2", "assignee_name": "Bob"}],
                error_types=[],
            )
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc["tasks_created"] == 2
        assert doc["senders"]["U1"]["count"] == 2
        assert doc["assignees"]["U2"]["count"] == 2
        assert doc["unique_senders"] == 1
        assert doc["unique_assignees"] == 1

    def test_record_tasks_errors_incremented(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[],
                error_types=["unregistered_assignee", "unregistered_assignee", "google_api_error"],
            )
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc["tasks_failed"] == 3
        assert doc["errors"]["unregistered_assignee"] == 2
        assert doc["errors"]["google_api_error"] == 1

    def test_record_tasks_noop_when_empty(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[], error_types=[],
            )
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc is None

    def test_record_tasks_multiple_assignees(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[
                    {"assignee_id": "U2", "assignee_name": "Bob"},
                    {"assignee_id": "U3", "assignee_name": "Charlie"},
                ],
                error_types=[],
            )
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc["tasks_created"] == 2
        assert doc["senders"]["U1"]["count"] == 2
        assert doc["assignees"]["U2"]["count"] == 1
        assert doc["assignees"]["U3"]["count"] == 1
        assert doc["unique_senders"] == 1
        assert doc["unique_assignees"] == 2

    def test_init_week_stats_sets_registered_users(self):
        db_module.upsert_user("U1", "tok1")
        db_module.upsert_user("U2", "tok2")
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.init_week_stats()
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc["registered_users"] == 2

    def test_init_week_stats_computes_unique_counts_from_existing_data(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.record_tasks(
                sender_id="U1", sender_name="Alice",
                successes=[
                    {"assignee_id": "U2", "assignee_name": "Bob"},
                    {"assignee_id": "U3", "assignee_name": "Charlie"},
                ],
                error_types=[],
            )
            db_module.init_week_stats()
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc["unique_senders"] == 1
        assert doc["unique_assignees"] == 2

    def test_init_week_stats_creates_fresh_document_with_zero_unique_counts(self):
        with patch.object(db_module, "_week_key", return_value="2026-W17"):
            db_module.init_week_stats()
        doc = self._db().stats.find_one({"_id": "2026-W17"})
        assert doc is not None
        assert doc["unique_senders"] == 0
        assert doc["unique_assignees"] == 0
