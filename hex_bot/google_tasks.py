import logging
from typing import Optional, Dict, Tuple

from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .config import Config

log = logging.getLogger(__name__)

# Per-user service and tasklist caches, keyed by refresh token.
# Each registered user gets their own Google API session.
_PAGE_SIZE = 100        # max tasklists per page (Google Tasks API limit is 100)
_MAX_LIST_TASKS = 20   # max tasks returned by list_tasks — keeps Slack messages readable
_GOOGLE_DEFAULT_TASKLIST = "@default"  # Google's special ID for the user's default tasklist

_services: Dict[str, object] = {}
_tasklist_cache: Dict[Tuple[str, str], str] = {}  # (refresh_token, channel_name) -> tasklist_id


def _get_service(refresh_token: str):
    if refresh_token not in _services:
        log.debug("Building Google Tasks service (token=...%s)", refresh_token[-4:])
        creds = Credentials(
            None,  # no access token — the library fetches one using the refresh token
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=Config.GOOGLE_CLIENT_ID,
            client_secret=Config.GOOGLE_CLIENT_SECRET,
            scopes=["https://www.googleapis.com/auth/tasks"],
        )
        _services[refresh_token] = build(
            "tasks",
            "v1",
            credentials=creds,
            cache_discovery=False,  # avoids a network hit to the discovery endpoint on cold start
        )
    return _services[refresh_token]


def _reset_service(refresh_token: str) -> None:
    log.warning("Evicting service and tasklist cache for token=...%s", refresh_token[-4:])
    _services.pop(refresh_token, None)
    # Evict tasklist cache entries for this token too: the tasklist IDs themselves
    # are stable, but if we need to reauthenticate we prefer a clean slate rather
    # than acting on state that was established under a broken credential.
    for key in list(_tasklist_cache):
        if key[0] == refresh_token:
            del _tasklist_cache[key]


def find_tasklist(title: str, *, refresh_token: str) -> Optional[str]:
    """Returns the tasklist ID for the given title, or None if not found. Never creates."""
    cache_key = (refresh_token, title)
    if cache_key in _tasklist_cache:
        return _tasklist_cache[cache_key]

    try:
        service = _get_service(refresh_token)
        page_token = None
        while True:
            result = service.tasklists().list(
                maxResults=_PAGE_SIZE,
                pageToken=page_token,
            ).execute()
            for item in result.get("items", []):
                if item.get("title") == title:
                    tasklist_id = item["id"]
                    _tasklist_cache[cache_key] = tasklist_id
                    return tasklist_id
            page_token = result.get("nextPageToken")
            if not page_token:
                break
    except RefreshError:
        log.warning("RefreshError in find_tasklist (token=...%s)", refresh_token[-4:])
        _reset_service(refresh_token)
        raise

    return None


def list_tasks(tasklist_id: str, *, refresh_token: str) -> list:
    """Returns up to _MAX_LIST_TASKS non-completed tasks from the given tasklist."""
    try:
        service = _get_service(refresh_token)
        result = service.tasks().list(
            tasklist=tasklist_id,
            showCompleted=False,  # Google Tasks API defaults to True, we only want open tasks
            maxResults=_MAX_LIST_TASKS,
        ).execute()
        return result.get("items", [])
    except RefreshError:
        log.warning("RefreshError in list_tasks (token=...%s)", refresh_token[-4:])
        _reset_service(refresh_token)
        raise


def get_or_create_tasklist(title: str, *, refresh_token: str) -> str:
    cache_key = (refresh_token, title)
    if cache_key in _tasklist_cache:
        return _tasklist_cache[cache_key]

    try:
        service = _get_service(refresh_token)
        page_token = None
        while True:
            result = service.tasklists().list(
                maxResults=_PAGE_SIZE,
                pageToken=page_token,
            ).execute()
            for item in result.get("items", []):
                if item.get("title") == title:
                    tasklist_id = item["id"]
                    _tasklist_cache[cache_key] = tasklist_id
                    return tasklist_id
            page_token = result.get("nextPageToken")
            if not page_token:
                break

        log.info("Creating tasklist %r (token=...%s)", title, refresh_token[-4:])
        created = service.tasklists().insert(body={"title": title}).execute()
        tasklist_id = created["id"]
        _tasklist_cache[cache_key] = tasklist_id
        return tasklist_id
    except RefreshError:
        log.warning("RefreshError in get_or_create_tasklist (token=...%s)", refresh_token[-4:])
        _reset_service(refresh_token)
        raise


def create_task(
    title: str,
    notes: str = "",
    tasklist_id: Optional[str] = None,
    *,
    refresh_token: str,  # keyword-only: prevents accidental positional misuse with the other str params
) -> dict:
    try:
        service = _get_service(refresh_token)
        body = {"title": title}
        if notes:
            body["notes"] = notes
        effective_tasklist = tasklist_id or _GOOGLE_DEFAULT_TASKLIST
        task = service.tasks().insert(
            tasklist=effective_tasklist,
            body=body,
        ).execute()
        log.info("Task created: %r in tasklist=%s (token=...%s)", title, effective_tasklist, refresh_token[-4:])
        return task
    except RefreshError:
        log.warning("RefreshError in create_task (token=...%s)", refresh_token[-4:])
        _reset_service(refresh_token)
        raise
