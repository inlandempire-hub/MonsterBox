"""BETA-ONLY: auto-collect PDFs that signed-in testers import, so the dev can run
them through the parser. Gated by settings.beta_collect_pdfs. Deduped by content
hash; bytes only kept up to a size cap (metadata always recorded). Admin reads the
list / downloads via the in-app 'Books' view.

To retire after beta: set BETA_COLLECT_PDFS=false (or delete this router + the
frontend hook + drop the pdf_uploads table)."""
import hashlib

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_admin
from ..config import settings
from ..db import get_db
from ..models import PdfUpload, User

router = APIRouter(prefix="/api/beta", tags=["beta"])


@router.post("/pdf")
async def collect_pdf(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not settings.beta_collect_pdfs:
        return {"collected": False, "reason": "disabled"}
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    sha = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(PdfUpload).where(PdfUpload.sha256 == sha))
    if existing:
        return {"collected": True, "dedup": True}     # already have this exact book
    keep = data if len(data) <= settings.beta_pdf_max_mb * 1024 * 1024 else None
    db.add(PdfUpload(sha256=sha, filename=(file.filename or "")[:200], size=len(data),
                     email=user.email, data=keep))
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


@router.get("/pdfs/{pdf_id}/download")
def download_pdf(pdf_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    r = db.get(PdfUpload, pdf_id)
    if r is None or not r.data:
        raise HTTPException(404, "no stored file for that upload (over the size cap?)")
    return Response(content=r.data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{r.filename or "book.pdf"}"'})
