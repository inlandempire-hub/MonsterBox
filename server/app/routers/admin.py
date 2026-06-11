"""Admin-only: grant/revoke access by email (the API equivalent of the
grant_access CLI). Lets a god account comp someone from inside the app later."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..db import get_db
from ..models import User
from ..schemas import GrantIn

router = APIRouter(prefix="/api/admin", tags=["admin"])

PLANS = {"free", "pro", "comp"}
ROLES = {"user", "admin"}


@router.post("/grant")
def grant(body: GrantIn, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    if body.plan and body.plan not in PLANS:
        raise HTTPException(400, f"plan must be one of {sorted(PLANS)}")
    if body.role and body.role not in ROLES:
        raise HTTPException(400, f"role must be one of {sorted(ROLES)}")

    user = db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email)   # pre-create; binds to Supabase id on first login
        db.add(user)
    if body.plan:
        user.plan = body.plan
    if body.role:
        user.role = body.role
    db.commit()
    db.refresh(user)
    return {
        "email": user.email,
        "plan": user.plan,
        "role": user.role,
        "has_full_access": user.has_full_access,
    }
