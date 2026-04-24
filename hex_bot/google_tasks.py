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
    """
    Return (and cache) a Google Tasks API service object for the given refresh token.

    The first call for a token builds a Credentials object and calls googleapiclient.discovery.build.
    Subsequent calls return the cached service directly, avoiding repeated discovery requests.
    The cache is keyed by refresh token, so each registered user gets their own session.
    """
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


def list_tasks(
    tasklist_id: str,
    *,
    refresh_token: str,
    limit: Optional[int] = _MAX_LIST_TASKS,
    skip: int = 0,
) -> list:
    """
    Returns non-completed tasks from the given tasklist.
    limit=None fetches all tasks; otherwise stops after limit tasks (post-skip).
    skip discards the first N results before applying limit.
    """
    try:
        service = _get_service(refresh_token)
        tasks: list = []
        page_token = None

        while True:
            # Request as many as needed to cover skip + limit in one or few pages.
            if limit is not None:
                still_needed = skip + limit - len(tasks)
                if still_needed <= 0:
                    break
                page_size = min(still_needed, _PAGE_SIZE)
            else:
                page_size = _PAGE_SIZE

            kwargs: dict = {
                "tasklist": tasklist_id,
                "showCompleted": False,  # only open tasks
                "maxResults": page_size,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            result = service.tasks().list(**kwargs).execute()
            tasks.extend(result.get("items", []))

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        tasks = tasks[skip:]
        if limit is not None:
            tasks = tasks[:limit]
        return tasks
    except RefreshError:
        log.warning("RefreshError in list_tasks (token=...%s)", refresh_token[-4:])
        _reset_service(refresh_token)
        raise


def get_or_create_tasklist(title: str, *, refresh_token: str) -> str:
    """
    Return the ID of the tasklist with the given title, creating it if it doesn't exist.

    Paginates through all tasklists (up to _PAGE_SIZE per page) to find a match.
    If no match is found, creates a new tasklist and returns its ID.
    Results are cached in _tasklist_cache so repeated calls for the same
    (token, title) pair don't hit the API.
    Raises RefreshError (re-raised after cache eviction) if the token is expired.
    """
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
    due: Optional[str] = None,
    *,
    refresh_token: str,  # keyword-only: prevents accidental positional misuse with the other str params
) -> dict:
    """
    Create a task in the user's Google Tasks account and return the created task dict.

    title:        visible task title (e.g. "[Alice] fix the login bug")
    notes:        optional body text — used for the Slack message permalink
    tasklist_id:  target list; falls back to "@default" (the user's primary list) if None
    due:          optional RFC 3339 UTC midnight string, e.g. "2026-04-28T00:00:00.000Z"
    refresh_token: the user's stored OAuth refresh token (required, keyword-only)
    """
    try:
        service = _get_service(refresh_token)
        body: dict = {"title": title}
        if notes:
            body["notes"] = notes
        if due:
            body["due"] = due  # RFC 3339 UTC midnight, e.g. "2026-04-28T00:00:00.000Z"
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
