"""
Google Sign-In — POST /auth/google verifies the ID token Google's Identity
Services button hands the browser, mints a signed session cookie, and the
browser is trusted from then on via that cookie (see auth_service.py).
"""
import os
import logging

# pyrefly: ignore [missing-import]
from fastapi import APIRouter, Request, Response, HTTPException
# pyrefly: ignore [missing-import]
from fastapi.responses import RedirectResponse
# pyrefly: ignore [missing-import]
from pydantic import BaseModel

from backend.services import auth_service
from backend.templating import templates
from backend.rate_limit import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/login")
async def login_page(request: Request):
    if auth_service.get_current_user_optional(request) is not None:
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"request": request, "google_client_id": os.environ["GOOGLE_CLIENT_ID"]},
    )


class GoogleAuthRequest(BaseModel):
    credential: str


@router.post("/auth/google")
@limiter.limit("10/minute")
async def auth_google(req: GoogleAuthRequest, request: Request, response: Response):
    try:
        claims = await auth_service.verify_google_id_token(req.credential)
    except Exception:
        logger.exception("Google ID token verification failed")
        raise HTTPException(status_code=401, detail="Google ile giriş doğrulanamadı.")

    user = {
        "email": claims["email"],
        "name": claims.get("name", claims["email"]),
        "picture": claims.get("picture"),
    }
    token = auth_service.create_session_token(user)
    response.set_cookie(
        key=auth_service.SESSION_COOKIE_NAME,
        value=token,
        max_age=auth_service.SESSION_MAX_AGE_SECONDS,
        httponly=True,
        secure=auth_service.COOKIE_SECURE,
        samesite="strict",
    )
    # Faz 3 will redirect first-time users to /onboarding instead once a
    # SQLite profile table exists to check against.
    return {"redirect": "/"}


@router.post("/auth/logout")
async def logout(response: Response):
    response.delete_cookie(auth_service.SESSION_COOKIE_NAME)
    return {"redirect": "/login"}
