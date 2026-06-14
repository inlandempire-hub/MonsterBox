from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..auth import current_user, ensure_public_id
from ..db import get_db
from ..models import User
from ..schemas import AccountOut

router = APIRouter(prefix="/api/auth", tags=["account"])


@router.get("/me", response_model=AccountOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Who am I, and what am I entitled to? The frontend calls this after login
    to decide whether to unlock Pro features."""
    ensure_public_id(db, user)
    return AccountOut(
        email=user.email,
        plan=user.plan,
        role=user.role,
        has_full_access=user.has_full_access,
        account_id=user.public_id,
    )
