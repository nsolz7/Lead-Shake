from __future__ import annotations

import hmac
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings


bearer = HTTPBearer(auto_error=False)

SESSION_COOKIE = "leadintel_session"


def authenticate(username: str, password: str) -> bool:
    settings = get_settings()
    return hmac.compare_digest(username, settings.admin_username) and hmac.compare_digest(password, settings.admin_password)


def create_token(username: str) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": username, "iat": now, "exp": now + timedelta(minutes=settings.jwt_expiry_minutes)},
        settings.jwt_secret,
        algorithm="HS256",
    )


def set_session_cookie(response: Response, token: str) -> None:
    """Attach the session as an HttpOnly cookie so browser JS can never read it.

    SameSite=Strict stops the cookie from riding along on any cross-site
    request (CSRF). `secure` is enforced outside local development.
    """
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.jwt_expiry_minutes * 60,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
    )


def _decode(token: str) -> str:
    payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
    username = payload.get("sub")
    if username != get_settings().admin_username:
        raise ValueError("unknown user")
    return username


def require_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Accept the session cookie (browser) or a bearer token (API clients)."""
    token = credentials.credentials if credentials else request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        return _decode(token)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc


def client_ip(request: Request) -> str:
    """Best-effort client IP: first X-Forwarded-For hop (set by our nginx),
    falling back to the direct peer address."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"
