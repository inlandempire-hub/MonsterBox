from fastapi import APIRouter, Depends

from ..auth import current_user
from ..models import User
from ..schemas import AccountOut

router = APIRouter(prefix="/api/auth", tags=["account"])


@router.get("/me", response_model=AccountOut)
def me(user: User = Depends(current_user)):
    """Who am I, and what am I entitled to? The frontend calls this after login
    to decide whether to unlock Pro features."""
    return AccountOut(
        email=user.email,
        plan=user.plan,
        role=user.role,
        has_full_access=user.has_full_access,
    )
