"""BETA-ONLY: auto-collect PDFs that signed-in testers import, so the dev can run
them through the parser. Gated by settings.beta_collect_pdfs. Deduped by content
hash; bytes only kept up to a size cap (metadata always recorded). Admin reads the
list / downloads via the in-app 'Books' view.

To retire after beta: set BETA_COLLECT_PDFS=false (or delete this router + the
frontend hook + drop the pdf_uploads table)."""
import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import optional_user, require_admin
from ..config import settings
from ..db import get_db
from ..models import PdfUpload, User

router = APIRouter(prefix="/api/beta", tags=["beta"])

MAX_ROWS = 5000   # hard cap on stored rows (abuse guard for the open endpoint)


@router.post("/pdf")
async def collect_pdf(
    file: UploadFile = File(...),
    user: User | None = Depends(optional_user),
    db: Session = Depends(get_db),
):
    if not settings.beta_collect_pdfs:
        return {"collected": False, "reason": "disabled"}
    # The admin's own imports are skipped — those books are already on the dev's
    # machine, so collecting them just wastes backend storage. Anonymous (no
    # account) testers ARE collected, with email recorded as null.
    if user is not None and user.role == "admin":
        return {"collected": False, "reason": "admin"}
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if not data[:5].startswith(b"%PDF"):
        return {"collected": False, "reason": "not a pdf"}   # ignore non-PDF uploads
    sha = hashlib.sha256(data).hexdigest()

    # Can we keep the bytes? (a) under the per-file cap AND (b) storing won't push
    # past the total budget. Otherwise metadata only — import is NEVER failed for
    # lack of space (free-tier safe).
    def _can_keep(nbytes: int) -> bool:
        if nbytes > settings.beta_pdf_max_mb * 1024 * 1024:
            return False
        used = db.scalar(select(func.coalesce(func.sum(PdfUpload.size), 0))
                         .where(PdfUpload.data.isnot(None))) or 0
        return used + nbytes <= settings.beta_pdf_total_mb * 1024 * 1024

    existing = db.scalar(select(PdfUpload).where(PdfUpload.sha256 == sha))
    if existing:
        # If we previously kept metadata only (over the old cap) but it now fits,
        # backfill the bytes on this re-import instead of skipping as a duplicate.
        if existing.data is None and _can_keep(len(data)):
            existing.data = data
            db.commit()
            return {"collected": True, "dedup": True, "backfilled": True}
        return {"collected": True, "dedup": True}     # already have this exact book

    if db.scalar(select(func.count()).select_from(PdfUpload)) >= MAX_ROWS:
        return {"collected": False, "reason": "full"}        # don't grow unbounded
    keep = data if _can_keep(len(data)) else None
    db.add(PdfUpload(sha256=sha, filename=(file.filename or "")[:200], size=len(data),
                     email=(user.email if user else None), data=keep))
    db.commit()
    return {"collected": True, "stored_bytes": keep is not None}


@router.get("/pdfs")
def list_pdfs(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.scalars(select(PdfUpload).order_by(PdfUpload.created_at.desc()).limit(300)).all()
    return [{
        "id": r.id,
        "filename": r.filename,
        "email": r.email,
        "size_mb": round((r.size or 0) / 1048576, 1),
        "has_file": r.data is not None,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.delete("/pdfs/unstored")
def delete_unstored(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Tidy-up: drop all metadata-only rows (books that were over the size cap and
    never stored). Declared before /pdfs/{pdf_id} so 'unstored' isn't read as an id."""
    rows = db.scalars(select(PdfUpload).where(PdfUpload.data.is_(None))).all()
    n = len(rows)
    for r in rows:
        db.delete(r)
    db.commit()
    return {"deleted": n}


@router.get("/pdfs/{pdf_id}/download")
def download_pdf(pdf_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(PdfUpload, pdf_id)
    if r is None or not r.data:
        raise HTTPException(404, "no stored file for that upload (over the size cap?)")
    return Response(content=r.data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{r.filename or "book.pdf"}"'})


@router.delete("/pdfs/{pdf_id}")
def delete_pdf(pdf_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Admin removes a collected book once it's been downloaded, to free space."""
    r = db.get(PdfUpload, pdf_id)
    if r is None:
        raise HTTPException(404, "not found")
    db.delete(r)
    db.commit()
    return {"ok": True}
