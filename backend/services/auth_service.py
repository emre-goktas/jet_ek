"""
Google Sign-In (passwordless) verification + signed session cookies.

Auth is entirely optional/toggleable via environment variables: if
GOOGLE_CLIENT_ID or SESSION_SECRET_KEY isn't set, is_auth_enabled() is False
and main.py leaves every route open, exactly like before this feature
existed — so an already-running deployment isn't locked out the moment this
code ships, only once its operator deliberately configures Google OAuth.
"""
import os
import asyncio
from functools import lru_cache

# pyrefly: ignore [missing-import]
from fastapi import Request, HTTPException
# pyrefly: ignore [missing-import]
from itsdangerous import URLSafeTimedSerializer, BadSignature
# pyrefly: ignore [missing-import]
from google.oauth2 import id_token as google_id_token
# pyrefly: ignore [missing-import]
from google.auth.transport import requests as google_requests

SESSION_COOKIE_NAME = "jetek_session"
SESSION_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 days

# Secure by default; only relaxed for local HTTP testing (JETEK_ENV=development
# in .env) since browsers silently drop Secure-flagged cookies over plain HTTP.
COOKIE_SECURE = os.environ.get("JETEK_ENV", "").strip().lower() != "development"


def is_auth_enabled() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(os.environ.get("SESSION_SECRET_KEY"))


@lru_cache(maxsize=1)
def _serializer() -> URLSafeTimedSerializer:
    secret = os.environ.get("SESSION_SECRET_KEY")
    if not secret:
        raise RuntimeError("SESSION_SECRET_KEY is not set.")
    # A dedicated salt namespaces this signature so the same secret couldn't
    # also be replayed against some other itsdangerous use elsewhere later.
    return URLSafeTimedSerializer(secret, salt="jetek-session")


def create_session_token(user: dict) -> str:
    """user must at least contain 'email'; may also carry 'name'/'picture'."""
    return _serializer().dumps(user)


def read_session_token(token: str) -> dict | None:
    """Returns the signed payload, or None for anything invalid/expired/
    tampered-with — callers treat all of those the same way (not logged in)."""
    try:
        return _serializer().loads(token, max_age=SESSION_MAX_AGE_SECONDS)
    except BadSignature:
        return None


def _verify_google_id_token_sync(credential: str) -> dict:
    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not set.")
    claims = google_id_token.verify_oauth2_token(credential, google_requests.Request(), client_id)
    if not claims.get("email_verified", False):
        raise ValueError("Google account email is not verified.")
    return claims


async def verify_google_id_token(credential: str) -> dict:
    """Verifies a Google Identity Services credential (a signed JWT) and
    returns its claims (email, name, picture, ...). Runs off the event loop
    since verification fetches Google's public certs over the network on a
    cache miss — a blocking call has no business running inline in an async
    route."""
    return await asyncio.to_thread(_verify_google_id_token_sync, credential)


def get_current_user(request: Request) -> dict:
    """Strict FastAPI dependency: 401s if there's no valid session. Used to
    gate API routers (upload/pages/extract/download/ai) when auth is enabled."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    user = read_session_token(token) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user


def get_current_user_optional(request: Request) -> dict | None:
    """Lenient variant: returns None instead of raising. Used by page routes
    (/ and /login) that redirect themselves rather than returning a bare 401."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return read_session_token(token) if token else None
