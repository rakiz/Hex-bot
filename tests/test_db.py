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
