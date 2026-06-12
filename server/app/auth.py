"""Authentication + entitlement dependencies.

Identity comes from Supabase (a verified JWT). We mirror each user into our own
`users` table on first contact so we can attach app-level fields (plan/role).
Authorization (who can use paid features, who is a god account) is decided here
from that local row — never from the provider.
"""
import jwt
from jwt import PyJWKClient
from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import User


class AuthError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=401, detail=detail)


_jwks_clients: dict[str, PyJWKClient] = {}


def _jwks_client(jwks_url: str) -> PyJWKClient:
    client = _jwks_clients.get(jwks_url)
    if client is None:
        client = PyJWKClient(jwks_url)   # caches keys internally
        _jwks_clients[jwks_url] = client
    return client


def _supabase_base() -> str:
    """The project's base URL, for locating its public keys (JWKS). Prefers an
    explicit SUPABASE_URL; otherwise derives it from the Supabase Postgres URL
    (username 'postgres.<project-ref>'), so no extra config is needed."""
    if settings.supabase_url:
        return settings.supabase_url.rstrip("/")
    try:
        from sqlalchemy.engine import make_url
        user = make_url(settings.database_url).username or ""
        if user.startswith("postgres."):
            return f"https://{user.split('.', 1)[1]}.supabase.co"
    except Exception:
        pass
    return ""


def _verify_supabase_jwt(token: str) -> dict:
    try:
        alg = jwt.get_unverified_header(token).get("alg", "")
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid token: {e}")

    try:
        # Legacy projects sign user tokens with the shared HS256 secret.
        if alg == "HS256":
            if not settings.supabase_jwt_secret:
                raise AuthError("Auth is not configured (SUPABASE_JWT_SECRET is missing).")
            return jwt.decode(token, settings.supabase_jwt_secret,
                              algorithms=["HS256"], audience=settings.supabase_jwt_aud)
        # Modern projects use asymmetric signing keys (ES256/RS256): verify against
        # the project's PUBLIC keys (JWKS), pinned to OUR configured project.
        base = _supabase_base()
        if not base:
            raise AuthError("Cannot locate the project's public keys (set SUPABASE_URL).")
        jwks_url = base + "/auth/v1/.well-known/jwks.json"
        signing_key = _jwks_client(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(token, signing_key.key,
                          algorithms=[alg], audience=settings.supabase_jwt_aud)
    except AuthError:
        raise
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid token: {e}")
    except Exception as e:
        raise AuthError(f"Token verification failed: {e}")


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
