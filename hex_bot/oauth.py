import json
import logging
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet

from .config import Config

log = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
TASKS_SCOPE = "https://www.googleapis.com/auth/tasks"

STATE_TTL_SECONDS = 600  # OAuth link expires after 10 minutes


def _fernet() -> Fernet:
    # New instance per call: Fernet is stateless so this is cheap,
    # and it avoids caching a stale key reference (e.g. in tests).
    return Fernet(Config.FERNET_KEY.encode())


def _callback_uri() -> str:
    return f"{Config.PUBLIC_BASE_URL}/oauth/google/callback"


def generate_oauth_url(slack_user_id: str) -> str:
    # We use Fernet for the state rather than a hand-rolled HMAC+timestamp because
    # Fernet tokens carry their own timestamp: decrypt(token, ttl=600) handles both
    # authentication and expiry in a single call, with no extra payload to sign.
    state = _fernet().encrypt(slack_user_id.encode()).decode()
    params = {
        "client_id": Config.GOOGLE_CLIENT_ID,
        "redirect_uri": _callback_uri(),
        "response_type": "code",
        "scope": TASKS_SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # forces a new refresh_token even if the user already authorized
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"


def verify_state(state: str) -> str:
    """Decrypts the state token and returns slack_user_id. Raises InvalidToken if tampered or expired."""
    return _fernet().decrypt(state.encode(), ttl=STATE_TTL_SECONDS).decode()


def exchange_code(code: str) -> str:
    """Exchanges a Google authorization code for a refresh token."""
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": Config.GOOGLE_CLIENT_ID,
        "client_secret": Config.GOOGLE_CLIENT_SECRET,
        "redirect_uri": _callback_uri(),
        "grant_type": "authorization_code",
    }).encode()

    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read())

    refresh_token = body.get("refresh_token")
    # Google only returns refresh_token on first authorization or when prompt=consent is set.
    # If it's absent here something unexpected happened upstream.
    if not refresh_token:
        raise ValueError(f"No refresh_token in Google response: {body}")
    return refresh_token
