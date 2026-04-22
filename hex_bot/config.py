import os

class Config:
    # Slack
    SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
    SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
    SLACK_BOT_USER_ID = os.environ.get("SLACK_BOT_USER_ID")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Google Tasks
    GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
    GOOGLE_REFRESH_TOKEN = os.environ["GOOGLE_REFRESH_TOKEN"]
    # Fallback when no per-user tasklist_id is available
    GOOGLE_TASKS_LIST_ID = os.environ.get("GOOGLE_TASKS_LIST_ID", "@default")

    # MongoDB
    MONGODB_URI = os.environ["MONGODB_URI"]
    MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "hex")

    # Fernet key for encrypting Google refresh tokens at rest.
    # Never change this once tokens are stored — existing tokens become unreadable.
    FERNET_KEY = os.environ["FERNET_KEY"]