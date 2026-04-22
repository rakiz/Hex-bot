from typing import Optional, Dict

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Config

# Module-level singletons: lazy-initialized on first API call, shared across requests.
# NOTE: not shared across Gunicorn workers — will move to DB-backed cache in Phase 1.
_tasks_service = None  # type: Optional[object]
_tasklist_cache: Dict[str, str] = {}  # channel_name -> tasklist_id


def _get_service():
    global _tasks_service
    if _tasks_service is None:
        creds = Credentials(
            None,  # no access token — the library will fetch one using the refresh token
            refresh_token=Config.GOOGLE_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.GOOGLE_CLIENT_ID,
            client_secret=Config.GOOGLE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/tasks"],
        )
        _tasks_service = build(
            "tasks",
            "v1",
            credentials=creds,
            cache_discovery=False,  # avoids a network hit to the discovery endpoint on cold start
        )
    return _tasks_service


def _reset_service() -> None:
    global _tasks_service, _tasklist_cache
    # Also clear the tasklist cache: those IDs are tied to the credentials being reset
    _tasks_service = None
    _tasklist_cache = {}


def get_or_create_tasklist(title: str) -> str:
    if title in _tasklist_cache:
        return _tasklist_cache[title]

    try:
        service = _get_service()
        page_token = None
        while True:
            result = service.tasklists().list(
                maxResults=100,
                pageToken=page_token,
            ).execute()
            for item in result.get("items", []):
                if item.get("title") == title:
                    tasklist_id = item["id"]
                    _tasklist_cache[title] = tasklist_id
                    return tasklist_id

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        created = service.tasklists().insert(body={"title": title}).execute()
        tasklist_id = created["id"]
        _tasklist_cache[title] = tasklist_id
        return tasklist_id
    except RefreshError:
        _reset_service()
        raise


def create_task(title: str, notes: str = "", tasklist_id: Optional[str] = None) -> dict:
    try:
        service = _get_service()
        body = {"title": title}
        if notes:
            body["notes"] = notes

        task = service.tasks().insert(
            tasklist=tasklist_id or Config.GOOGLE_TASKS_LIST_ID,
            body=body,
        ).execute()
        return task
    except RefreshError:
        _reset_service()
        raise