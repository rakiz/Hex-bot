import json
import time
import urllib.error
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet, InvalidToken


TEST_USER = "U12345TEST"
TEST_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def patch_config(monkeypatch):
    monkeypatch.setattr("hex_bot.oauth.Config.FERNET_KEY", TEST_KEY)
    monkeypatch.setattr("hex_bot.oauth.Config.PUBLIC_BASE_URL", "http://localhost:8080")
    monkeypatch.setattr("hex_bot.oauth.Config.GOOGLE_CLIENT_ID", "test_client_id")
    monkeypatch.setattr("hex_bot.oauth.Config.GOOGLE_CLIENT_SECRET", "test_secret")


def _parse_state(url: str) -> str:
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    return qs["state"][0]


def _urlopen_mock(body: dict):
    mock = MagicMock()
    mock.__enter__ = lambda s: s
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = json.dumps(body).encode()
    return mock


# ---------------------------------------------------------------------------
# generate_oauth_url / verify_state
# ---------------------------------------------------------------------------

def test_state_roundtrip():
    from hex_bot.oauth import generate_oauth_url, verify_state
    url = generate_oauth_url(TEST_USER)
    state = _parse_state(url)
    assert verify_state(state) == TEST_USER


def test_oauth_url_params():
    from hex_bot.oauth import generate_oauth_url
    url = generate_oauth_url(TEST_USER)
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert qs["client_id"] == ["test_client_id"]
    assert qs["redirect_uri"] == ["http://localhost:8080/oauth/google/callback"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert "state" in qs


def test_state_expired():
    from hex_bot.oauth import verify_state
    f = Fernet(TEST_KEY.encode())
    old_state = f.encrypt_at_time(TEST_USER.encode(), int(time.time()) - 700).decode()
    with pytest.raises(InvalidToken):
        verify_state(old_state)


def test_state_tampered():
    from hex_bot.oauth import verify_state
    with pytest.raises(Exception):
        verify_state("this-is-not-a-valid-fernet-token")


def test_different_users_get_different_states():
    from hex_bot.oauth import generate_oauth_url, verify_state
    url1 = generate_oauth_url("UAAA")
    url2 = generate_oauth_url("UBBB")
    state1 = _parse_state(url1)
    state2 = _parse_state(url2)
    assert state1 != state2
    assert verify_state(state1) == "UAAA"
    assert verify_state(state2) == "UBBB"


# ---------------------------------------------------------------------------
# exchange_code
# ---------------------------------------------------------------------------

def test_exchange_code_returns_refresh_token():
    from hex_bot.oauth import exchange_code
    mock = _urlopen_mock({"refresh_token": "tok_123", "access_token": "acc"})
    with patch("urllib.request.urlopen", return_value=mock):
        result = exchange_code("auth_code_abc")
    assert result == "tok_123"


def test_exchange_code_raises_if_no_refresh_token():
    from hex_bot.oauth import exchange_code
    # Google omits refresh_token when the user already authorized and prompt!=consent
    mock = _urlopen_mock({"access_token": "acc"})
    with patch("urllib.request.urlopen", return_value=mock):
        with pytest.raises(ValueError, match="No refresh_token"):
            exchange_code("auth_code_abc")


def test_exchange_code_propagates_network_error():
    from hex_bot.oauth import exchange_code
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
        with pytest.raises(urllib.error.URLError):
            exchange_code("auth_code_abc")
