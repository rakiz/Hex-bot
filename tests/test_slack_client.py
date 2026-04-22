import pytest
from unittest.mock import patch

import hex_bot.slack_client as sc


@pytest.fixture(autouse=True)
def restore_bot_user_id():
    """Reset the cached bot user ID after each test."""
    original = sc._bot_user_id
    yield
    sc._bot_user_id = original


def test_get_bot_user_id_returns_cached_value():
    sc._bot_user_id = "U_CACHED"
    assert sc.get_bot_user_id() == "U_CACHED"


def test_get_bot_user_id_calls_auth_test_when_not_set():
    sc._bot_user_id = None
    with patch.object(sc.slack, "auth_test", return_value={"user_id": "U_FROM_API"}):
        result = sc.get_bot_user_id()
    assert result == "U_FROM_API"


def test_get_bot_user_id_caches_result_after_auth_test():
    sc._bot_user_id = None
    with patch.object(sc.slack, "auth_test", return_value={"user_id": "U_FROM_API"}):
        sc.get_bot_user_id()
    assert sc._bot_user_id == "U_FROM_API"


def test_get_bot_user_id_raises_if_auth_test_fails():
    sc._bot_user_id = None
    with patch.object(sc.slack, "auth_test", side_effect=Exception("network error")):
        with pytest.raises(Exception, match="network error"):
            sc.get_bot_user_id()
