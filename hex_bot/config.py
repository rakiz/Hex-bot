import os
from dotenv import load_dotenv

load_dotenv()  # no-op if .env doesn't exist (production)

class Config:
    # Slack
    SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
    SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
    SLACK_BOT_USER_ID = os.environ.get("SLACK_BOT_USER_ID")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Google Tasks
    GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]

    # Public base URL used to build the OAuth callback URI.
    # In dev: http://localhost:8080 (default). In prod: the Kanopy HTTPS domain.
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080")

    # MongoDB
    MONGODB_URI = os.environ["MONGODB_URI"]
    MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "hex")

    # Fernet key for encrypting Google refresh tokens at rest.
    # Never change this once tokens are stored — existing tokens become unreadable.
    FERNET_KEY = os.environ["FERNET_KEY"]