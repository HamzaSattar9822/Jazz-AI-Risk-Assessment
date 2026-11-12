from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User
from app.security import read_token
from app.services.oidc import user_has_role

COOKIE_NAME = "aira_session"
_bearer = HTTPBearer(auto_error=False)
REVIEW_ROLES = ("reviewer", "governance", "admin")
ADMIN_ROLES = ("admin",)


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    token = credentials.credentials if credentials else request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Sign in required.")
    user_id = read_token(token)
    user = db.get(User, user_id) if user_id is not None else None
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    return user


def reviewer(user: User = Depends(current_user)) -> User:
    if not user_has_role(user, *REVIEW_ROLES):
        raise HTTPException(status_code=403, detail="Only reviewers can do that.")
    return user


def admin_user(user: User = Depends(current_user)) -> User:
    if not user_has_role(user, *ADMIN_ROLES):
        raise HTTPException(status_code=403, detail="Only admins can do that.")
    return user
