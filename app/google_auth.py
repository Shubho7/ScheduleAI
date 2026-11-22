"""Per-user Google Calendar sign-in (OAuth web flow).

Each visitor connects their own Google account. Their refresh token is kept only
in an encrypted, HttpOnly cookie in their own browser, so the server stores
nothing and the login survives restarts.

Required environment variables:
    GOOGLE_OAUTH_CLIENT_ID      OAuth client of type "Web application"
    GOOGLE_OAUTH_CLIENT_SECRET  its secret
    APP_BASE_URL                public URL, e.g. https://scheduleaiv1.onrender.com
                                (redirect URI is APP_BASE_URL + /auth/callback)
    COOKIE_SECRET               any long random string; used to encrypt cookies
"""

import base64
import hashlib
import json
import os
import secrets
from collections.abc import Mapping
from typing import Optional

import requests
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

# Google may return a superset of the requested scopes; don't treat that as an error.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

SCOPES = ["https://www.googleapis.com/auth/calendar"]
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"
REVOKE_URI = "https://oauth2.googleapis.com/revoke"

# Key under which the refresh token is placed in the ADK session state.
REFRESH_TOKEN_KEY = "gcal_refresh_token"

AUTH_COOKIE = "gcal"  # {"rt": refresh_token, "email": ...}
STATE_COOKIE = "gcal_state"  # {"state": ..., "verifier": ...} during sign-in
STATE_COOKIE_TTL = 600  # seconds
AUTH_COOKIE_TTL = 60 * 60 * 24 * 365  # one year

router = APIRouter()


# --- configuration ---------------------------------------------------------


def client_credentials() -> tuple[Optional[str], Optional[str]]:
    return os.getenv("GOOGLE_OAUTH_CLIENT_ID"), os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")


def _base_url() -> str:
    return os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/")


def _redirect_uri() -> str:
    return f"{_base_url()}/auth/callback"


def is_configured() -> bool:
    client_id, client_secret = client_credentials()
    return bool(client_id and client_secret and os.getenv("COOKIE_SECRET"))


def _cookie_flags() -> dict:
    return {
        "httponly": True,
        "samesite": "lax",
        "secure": _base_url().startswith("https"),
    }


# --- encrypted cookies -----------------------------------------------------


def _fernet() -> Optional[Fernet]:
    secret = os.getenv("COOKIE_SECRET")
    if not secret:
        return None
    # Derive a valid Fernet key from any secret string.
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _encrypt(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data).encode()).decode()


def _decrypt(value: Optional[str], ttl: Optional[int] = None) -> Optional[dict]:
    """Return the decrypted dict, or None if missing, tampered with, or expired."""
    fernet = _fernet()
    if not value or not fernet:
        return None
    try:
        return json.loads(fernet.decrypt(value.encode(), ttl=ttl))
    except (InvalidToken, ValueError):
        return None


def read_connection(cookies: Mapping[str, str]) -> Optional[dict]:
    """The signed-in user's {"rt", "email"} from the cookie, or None."""
    data = _decrypt(cookies.get(AUTH_COOKIE))
    return data if data and data.get("rt") else None


def get_refresh_token(cookies: Mapping[str, str]) -> Optional[str]:
    data = read_connection(cookies)
    return data["rt"] if data else None


# --- OAuth helpers ---------------------------------------------------------


def _flow() -> Flow:
    client_id, client_secret = client_credentials()
    config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI,
            "redirect_uris": [_redirect_uri()],
        }
    }
    return Flow.from_client_config(
        config,
        scopes=SCOPES,
        redirect_uri=_redirect_uri(),
        autogenerate_code_verifier=True,  # PKCE; the verifier travels in the state cookie
    )


def _primary_email(creds: Credentials) -> Optional[str]:
    """The Google account's email (the primary calendar's id)."""
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return service.calendars().get(calendarId="primary").execute().get("id")
    except Exception as e:
        print(f"[AUTH] could not read primary calendar id: {type(e).__name__}")
        return None


def _redirect_home(result: str) -> RedirectResponse:
    response = RedirectResponse(f"/?auth={result}", status_code=303)
    response.delete_cookie(STATE_COOKIE)
    return response


# --- routes ----------------------------------------------------------------


@router.get("/auth/login")
def login():
    """Start the Google sign-in."""
    if not is_configured():
        return JSONResponse(
            {"error": "Google sign-in is not configured on this server."},
            status_code=503,
        )
    flow = _flow()
    url, state = flow.authorization_url(
        access_type="offline",  # we need a refresh token
        prompt="consent",  # ...and Google only sends it on consent
    )
    response = RedirectResponse(url, status_code=303)
    response.set_cookie(
        STATE_COOKIE,
        _encrypt({"state": state, "verifier": flow.code_verifier}),
        max_age=STATE_COOKIE_TTL,
        **_cookie_flags(),
    )
    return response


@router.get("/auth/callback")
def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
):
    """Google redirects here after the user approves (or declines)."""
    if error:
        return _redirect_home("denied")

    saved = _decrypt(request.cookies.get(STATE_COOKIE), ttl=STATE_COOKIE_TTL)
    if not (code and state and saved) or not secrets.compare_digest(
        saved.get("state", ""), state
    ):
        return _redirect_home("error")

    try:
        flow = _flow()
        flow.code_verifier = saved.get("verifier")
        flow.fetch_token(code=code)
    except Exception as e:
        print(f"[AUTH] token exchange failed: {type(e).__name__}: {e}")
        return _redirect_home("error")

    creds = flow.credentials
    if not creds.refresh_token:
        return _redirect_home("error")

    response = _redirect_home("ok")
    response.set_cookie(
        AUTH_COOKIE,
        _encrypt({"rt": creds.refresh_token, "email": _primary_email(creds)}),
        max_age=AUTH_COOKIE_TTL,
        **_cookie_flags(),
    )
    return response


@router.get("/auth/status")
def status(request: Request):
    """Used by the frontend to show Connect / Connected."""
    data = read_connection(request.cookies)
    return JSONResponse(
        {
            "configured": is_configured(),
            "connected": bool(data),
            "email": data.get("email") if data else None,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/auth/disconnect")
def disconnect(request: Request):
    """Forget the user's Google login and revoke it at Google."""
    refresh_token = get_refresh_token(request.cookies)
    if refresh_token:
        try:
            requests.post(REVOKE_URI, params={"token": refresh_token}, timeout=5)
        except requests.RequestException as e:
            print(f"[AUTH] revoke failed: {type(e).__name__}")
    response = JSONResponse({"connected": False})
    response.delete_cookie(AUTH_COOKIE)
    return response
