import pytest
from unittest.mock import MagicMock, patch
from google.auth.exceptions import RefreshError

import hex_bot.google_tasks as gt


@pytest.fixture(autouse=True)
def clear_caches():
    gt._services.clear()
    gt._tasklist_cache.clear()
    yield
    gt._services.clear()
    gt._tasklist_cache.clear()


def _mock_service(items=None, created_id="LIST_NEW"):
    """Build a MagicMock that mimics a googleapiclient tasks service."""
    svc = MagicMock()
    svc.tasklists.return_value.list.return_value.execute.return_value = {
        "items": items or []
    }
    svc.tasklists.return_value.insert.return_value.execute.return_value = {"id": created_id}
    svc.tasks.return_value.insert.return_value.execute.return_value = {"id": "T1", "title": "x"}
    return svc


# ---------------------------------------------------------------------------
# get_or_create_tasklist
# ---------------------------------------------------------------------------

def test_finds_existing_tasklist():
    svc = _mock_service(items=[{"title": "general", "id": "L_EXIST"}, {"title": "other", "id": "L_OTHER"}])
    with patch("hex_bot.google_tasks.build", return_value=svc):
        result = gt.get_or_create_tasklist("general", refresh_token="tok")
    assert result == "L_EXIST"
    svc.tasklists.return_value.insert.assert_not_called()


def test_creates_tasklist_when_not_found():
    svc = _mock_service(items=[{"title": "other", "id": "L_OTHER"}], created_id="L_NEW")
    with patch("hex_bot.google_tasks.build", return_value=svc):
        result = gt.get_or_create_tasklist("general", refresh_token="tok")
    assert result == "L_NEW"
    svc.tasklists.return_value.insert.assert_called_once_with(body={"title": "general"})


def test_result_is_cached_on_second_call():
    svc = _mock_service(items=[{"title": "general", "id": "L1"}])
    with patch("hex_bot.google_tasks.build", return_value=svc):
        r1 = gt.get_or_create_tasklist("general", refresh_token="tok")
        r2 = gt.get_or_create_tasklist("general", refresh_token="tok")
    assert r1 == r2 == "L1"
    assert svc.tasklists.return_value.list.return_value.execute.call_count == 1


def test_different_tokens_use_separate_caches():
    svc = _mock_service(items=[{"title": "general", "id": "L_A"}])
    with patch("hex_bot.google_tasks.build", return_value=svc):
        gt.get_or_create_tasklist("general", refresh_token="tok_a")
        gt.get_or_create_tasklist("general", refresh_token="tok_b")
    # Two separate cache keys → two API calls
    assert svc.tasklists.return_value.list.return_value.execute.call_count == 2


def test_handles_paginated_results():
    svc = MagicMock()
    svc.tasklists.return_value.list.return_value.execute.side_effect = [
        {"items": [{"title": "other", "id": "L0"}], "nextPageToken": "p2"},
        {"items": [{"title": "general", "id": "L1"}]},
    ]
    with patch("hex_bot.google_tasks.build", return_value=svc):
        result = gt.get_or_create_tasklist("general", refresh_token="tok")
    assert result == "L1"


def test_refresh_error_resets_service_and_cache():
    svc = MagicMock()
    svc.tasklists.return_value.list.return_value.execute.side_effect = RefreshError("expired")
    gt._services["tok"] = svc
    # Pre-populate a different tasklist entry so we can verify it's evicted on reset
    gt._tasklist_cache[("tok", "other")] = "other_id"

    with patch("hex_bot.google_tasks.build", return_value=svc):
        with pytest.raises(RefreshError):
            gt.get_or_create_tasklist("general", refresh_token="tok")

    assert "tok" not in gt._services
    assert ("tok", "other") not in gt._tasklist_cache


# ---------------------------------------------------------------------------
# create_task
# ---------------------------------------------------------------------------

def test_create_task_success():
    svc = _mock_service()
    with patch("hex_bot.google_tasks.build", return_value=svc):
        result = gt.create_task("Buy milk", notes="urgent", tasklist_id="L1", refresh_token="tok")
    assert result["id"] == "T1"
    svc.tasks.return_value.insert.assert_called_once_with(
        tasklist="L1",
        body={"title": "Buy milk", "notes": "urgent"},
    )


def test_create_task_without_notes_omits_notes_field():
    svc = _mock_service()
    with patch("hex_bot.google_tasks.build", return_value=svc):
        gt.create_task("Buy milk", refresh_token="tok")
    body = svc.tasks.return_value.insert.call_args[1]["body"]
    assert "notes" not in body


def test_create_task_falls_back_to_default_tasklist():
    svc = _mock_service()
    with patch("hex_bot.google_tasks.build", return_value=svc):
        gt.create_task("Buy milk", refresh_token="tok")  # no tasklist_id
    assert svc.tasks.return_value.insert.call_args[1]["tasklist"] == "@default"


def test_create_task_refresh_error_resets_service():
    svc = MagicMock()
    svc.tasks.return_value.insert.return_value.execute.side_effect = RefreshError("expired")
    gt._services["tok"] = svc

    with patch("hex_bot.google_tasks.build", return_value=svc):
        with pytest.raises(RefreshError):
            gt.create_task("Buy milk", refresh_token="tok")

    assert "tok" not in gt._services
