"""Cloud sync of stat blocks — the first real slice of the existing /api
contract, now server-backed and per-user. Gated behind full access because
cloud sync is the Pro feature (the free tier stays local-only in the browser).

This mirrors the in-browser fetch-shim routes so the frontend can later point at
this server instead of IndexedDB with minimal change.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import require_full_access
from ..db import get_db
from ..models import StatBlock, User
from ..schemas import StatBlockIn, StatBlockOut

router = APIRouter(prefix="/api/statblocks", tags=["statblocks"])


@router.get("", response_model=list[StatBlockOut])
def list_statblocks(user: User = Depends(require_full_access), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(StatBlock).where(StatBlock.user_id == user.id, StatBlock.deleted.is_(False))
    ).all()
    return [StatBlockOut(id=r.client_id, name=r.name, data=r.data, updated_at=r.updated_at) for r in rows]


@router.put("/{client_id}", response_model=StatBlockOut)
def upsert_statblock(
    client_id: str,
    body: StatBlockIn,
    user: User = Depends(require_full_access),
    db: Session = Depends(get_db),
):
    name = body.name or (body.data.get("name") if isinstance(body.data, dict) else "") or ""
    row = db.scalar(
        select(StatBlock).where(StatBlock.user_id == user.id, StatBlock.client_id == client_id)
    )
    if row is None:
        row = StatBlock(user_id=user.id, client_id=client_id, name=name, data=body.data, deleted=False)
        db.add(row)
    else:
        row.name, row.data, row.deleted = name, body.data, False
    db.commit()
    db.refresh(row)
    return StatBlockOut(id=row.client_id, name=row.name, data=row.data, updated_at=row.updated_at)


@router.delete("/{client_id}")
def delete_statblock(
    client_id: str,
    user: User = Depends(require_full_access),
    db: Session = Depends(get_db),
):
    row = db.scalar(
        select(StatBlock).where(StatBlock.user_id == user.id, StatBlock.client_id == client_id)
    )
    if row is not None:
        row.deleted = True   # soft-delete so a sync can tombstone across devices
        db.commit()
    return {"deleted": True}


@router.delete("")
def clear_statblocks(user: User = Depends(require_full_access), db: Session = Depends(get_db)):
    """Tombstone the whole library (mirrors the app's 'Clear All')."""
    rows = db.scalars(
        select(StatBlock).where(StatBlock.user_id == user.id, StatBlock.deleted.is_(False))
    ).all()
    for r in rows:
        r.deleted = True
    db.commit()
    return {"deleted": len(rows)}
