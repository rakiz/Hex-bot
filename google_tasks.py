from typing import Optional, Dict

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from config import Config

_tasks_service = None  # type: Optional[object]
_tasklist_cache: Dict[str, str] = {}  # channel_name -> tasklist_id

def _get_service():
    global _tasks_service
    if _tasks_service is None:
        creds = Credentials(
            None,
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
            cache_discovery=False,
        )
    return _tasks_service

def get_or_create_tasklist(title: str) -> str:
    """
    Retourne l'id de la tasklist ayant ce titre,
    en la créant si elle n'existe pas encore.
    """
    if title in _tasklist_cache:
        return _tasklist_cache[title]

    service = _get_service()

    # Cherche une liste existante avec ce titre
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

    # Pas trouvée -> créer
    created = service.tasklists().insert(body={"title": title}).execute()
    tasklist_id = created["id"]
    _tasklist_cache[title] = tasklist_id
    return tasklist_id

def create_task(title: str, notes: str = "", tasklist_id: Optional[str] = None) -> dict:
    """
    Crée une tâche dans la liste donnée (ou la liste par défaut si tasklist_id est None).
    """
    service = _get_service()
    body = {"title": title}
    if notes:
        body["notes"] = notes

    effective_list = tasklist_id or Config.GOOGLE_TASKS_LIST_ID

    task = service.tasks().insert(
        tasklist=effective_list,
        body=body,
    ).execute()
    return task