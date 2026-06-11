"""Authentication + entitlement dependencies.

Identity comes from Supabase (a verified JWT). We mirror each user into our own
`users` table on first contact so we can attach app-level fields (plan/role).
Authorization (who can use paid features, who is a god account) is decided here
from that local row — never from the provider.
"""
import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User


class AuthError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)


def _verify_supabase_jwt(token: str) -> dict:
    if not settings.supabase_jwt_secret:
        raise AuthError("Auth is not configured (SUPABASE_JWT_SECRET is missing).")
    try:
        return jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience=settings.supabase_jwt_aud,
        )
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid token: {e}")


def _get_or_create_user(db: Session, *, sub: str | None, email: str | None) -> User:
    """Resolve the local user row. Order: by provider id, then by a pre-granted
    email row (which we then bind to this provider id), else create fresh."""
    user = db.scalar(select(User).where(User.supabase_id == sub)) if sub else None
    if user is None and email:
        user = db.scalar(select(User).where(User.email == email))
        if user is not None and sub and not user.supabase_id:
            user.supabase_id = sub          # bind a pre-granted account on first login
    if user is None:
        user = User(supabase_id=sub, email=(email or f"{sub}@no-email.local"))
        db.add(user)
    db.commit()
    db.refresh(user)
    return user


def current_user(
    authorization: str | None = Header(default=None),
    x_dev_user: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    # Local-only escape hatch (DEV_AUTH): trust an email header so the API can be
    # exercised before Supabase is wired up. Never enable in production.
    if settings.dev_auth and x_dev_user:
        return _get_or_create_user(db, sub=None, email=x_dev_user.strip().lower())

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()
    claims = _verify_supabase_jwt(token)
    return _get_or_create_user(db, sub=claims.get("sub"), email=(claims.get("email") or "").lower())


def require_full_access(user: User = Depends(current_user)) -> User:
    """Gate paid features. 402 = payment required (or ask an admin to comp you)."""
    if not user.has_full_access:
        raise HTTPException(status_code=402, detail="This feature requires MonsterBox Pro.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only.")
    return user
