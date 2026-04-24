import os
from dotenv import load_dotenv

load_dotenv()  # no-op if .env doesn't exist (production)


class Config:
    """
    Central configuration loaded from environment variables (or .env in dev).

    Required keys use os.environ["KEY"] — missing ones raise KeyError at startup
    so the app fails fast with a clear error rather than silently misbehaving at
    runtime. Optional keys use os.environ.get("KEY", default).
    """

    # Slack
    SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
    SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
    # Optional: auto-discovered via auth.test() on first use if not provided.
    SLACK_BOT_USER_ID = os.environ.get("SLACK_BOT_USER_ID")

    LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")

    # Google Tasks OAuth credentials (from Google Cloud Console)
    GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
    GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]

    # Base URL used to build the Google OAuth callback URI.
    # In dev: http://localhost:8080 works as-is (Google allows localhost for Desktop clients).
    # In prod: set to the public HTTPS domain so the callback reaches this server.
    PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8080")

    # MongoDB
    MONGODB_URI = os.environ["MONGODB_URI"]
    MONGODB_DB_NAME = os.environ.get("MONGODB_DB_NAME", "hex")

    # Fernet key for encrypting Google refresh tokens at rest.
    # Generate once with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Never change this once tokens are stored — existing tokens become unreadable.
    FERNET_KEY = os.environ["FERNET_KEY"]