"""Firebase authentication helpers for FastAPI routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from firebase_admin.exceptions import FirebaseError

from app.database import initialize_firebase


bearer_scheme = HTTPBearer(auto_error=False)


def verify_firebase_token(token: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return its decoded user claims."""
    if not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="A Firebase ID token is required.",
        )

    try:
        initialize_firebase()
        return dict(auth.verify_id_token(token, check_revoked=True))
    except (auth.ExpiredIdTokenError, auth.RevokedIdTokenError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The Firebase ID token has expired or been revoked.",
        ) from exc
    except (auth.InvalidIdTokenError, FirebaseError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="The Firebase ID token is invalid.",
        ) from exc


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict[str, Any]:
    """FastAPI dependency that supplies the authenticated Firebase user."""
    middleware_user = getattr(request.state, "user", None)
    if isinstance(middleware_user, dict):
        return middleware_user

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Use an Authorization: Bearer <Firebase ID token> header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return verify_firebase_token(credentials.credentials)
