"""BETA-ONLY: auto-collect PDFs that signed-in testers import, so the dev can run
them through the parser. Gated by settings.beta_collect_pdfs. Deduped by content
hash. Admin reads the list / downloads via the in-app 'Books' view.

Storage: PREFERRED is Supabase Storage (object storage, streamed — handles large
files without using the app's RAM). If that isn't configured, falls back to a
small DB-bytes path (RAM-capped). Metadata is always recorded either way.

To retire after beta: set BETA_COLLECT_PDFS=false (or delete this router + the
frontend hook + drop the pdf_uploads table + the storage bucket)."""
import hashlib

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from .. import storage
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
    # machine. Anonymous (no account) testers ARE collected, email recorded as null.
    if user is not None and user.role == "admin":
        return {"collected": False, "reason": "admin"}

    storage_on = settings.storage_ready
    db_cap = settings.beta_pdf_max_mb * 1024 * 1024
    # Stream the upload so a big file is NEVER held whole in RAM. Hash + size as we
    # go; for the DB fallback also buffer up to the DB cap (storage path needs no buffer).
    h = hashlib.sha256()
    buf = bytearray()
    keeping_db, size, first = True, 0, True
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        if first:
            if not chunk[:5].startswith(b"%PDF"):
                return {"collected": False, "reason": "not a pdf"}   # ignore non-PDF uploads
            first = False
        h.update(chunk)
        size += len(chunk)
        if not storage_on:
            if keeping_db and size <= db_cap:
                buf.extend(chunk)
            elif keeping_db:
                keeping_db = False
                buf = bytearray()
    if size == 0:
        raise HTTPException(400, "empty file")
    sha = h.hexdigest()

    def _used() -> int:
        return db.scalar(select(func.coalesce(func.sum(PdfUpload.size), 0)).where(
            or_(PdfUpload.data.isnot(None), PdfUpload.storage_path.isnot(None)))) or 0

    def _store():
        """Persist this upload's bytes. Returns ('storage', path) | ('db', bytes) |
        (None, None). Storage preferred; never raises (failure -> metadata only)."""
        if storage_on:
            if size <= settings.beta_storage_max_mb * 1024 * 1024 \
                    and _used() + size <= settings.beta_storage_total_mb * 1024 * 1024:
                path = f"{sha}.pdf"
                try:
                    file.file.seek(0)
                    storage.upload(path, file.file, size)
                    return ("storage", path)
                except Exception:
                    return (None, None)
            return (None, None)
        if keeping_db and size <= db_cap and _used() + size <= settings.beta_pdf_total_mb * 1024 * 1024:
            return ("db", bytes(buf))
        return (None, None)

    existing = db.scalar(select(PdfUpload).where(PdfUpload.sha256 == sha))
    if existing:
        # Backfill if we previously kept metadata only and it now fits somewhere.
        if existing.data is None and existing.storage_path is None:
            kind, val = _store()
            if kind == "storage":
                existing.storage_path = val
            elif kind == "db":
                existing.data = val
            if kind:
                db.commit()
                return {"collected": True, "dedup": True, "backfilled": True}
        return {"collected": True, "dedup": True}     # already have this exact book

    if db.scalar(select(func.count()).select_from(PdfUpload)) >= MAX_ROWS:
        return {"collected": False, "reason": "full"}        # don't grow unbounded
    kind, val = _store()
    db.add(PdfUpload(sha256=sha, filename=(file.filename or "")[:200], size=size,
                     email=(user.email if user else None),
                     data=(val if kind == "db" else None),
                     storage_path=(val if kind == "storage" else None)))
    db.commit()
    return {"collected": True, "stored": kind is not None, "where": kind or "none"}


@router.get("/pdfs")
def list_pdfs(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Select ONLY metadata columns — never the data BLOB (loading every row's bytes
    # OOM'd the instance on open). has_file is true for DB- or storage-backed rows.
    rows = db.execute(
        select(PdfUpload.id, PdfUpload.filename, PdfUpload.email, PdfUpload.size,
               or_(PdfUpload.data.isnot(None), PdfUpload.storage_path.isnot(None)).label("has_file"),
               PdfUpload.created_at)
        .order_by(PdfUpload.created_at.desc()).limit(300)
    ).all()
    return [{
        "id": r.id,
        "filename": r.filename,
        "email": r.email,
        "size_mb": round((r.size or 0) / 1048576, 1),
        "has_file": bool(r.has_file),
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


@router.delete("/pdfs/unstored")
def delete_unstored(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Tidy-up: drop all metadata-only rows (never stored anywhere). Declared before
    /pdfs/{pdf_id} so 'unstored' isn't read as an id."""
    res = db.execute(delete(PdfUpload).where(
        PdfUpload.data.is_(None), PdfUpload.storage_path.is_(None)))
    db.commit()
    return {"deleted": res.rowcount}


@router.get("/pdfs/{pdf_id}/download")
def download_pdf(pdf_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    # Read storage_path WITHOUT the BLOB first, so storage-backed books never load bytes.
    row = db.execute(select(PdfUpload.storage_path).where(PdfUpload.id == pdf_id)).first()
    if row is None:
        raise HTTPException(404, "not found")
    if row.storage_path:
        try:
            return {"url": storage.signed_url(row.storage_path)}   # JSON: browser downloads direct from Supabase
        except Exception:
            raise HTTPException(502, "couldn't create a download link")
    # Legacy DB-stored bytes: load only now.
    r = db.get(PdfUpload, pdf_id)
    if r is None or not r.data:
        raise HTTPException(404, "no stored file for that upload (over the size cap?)")
    return Response(content=r.data, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{r.filename or "book.pdf"}"'})


@router.delete("/pdfs/{pdf_id}")
def delete_pdf(pdf_id: int, _admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Remove a collected book. Reads storage_path WITHOUT the BLOB, deletes the
    storage object (if any), then the row — so deleting a big book can't OOM."""
    row = db.execute(select(PdfUpload.storage_path).where(PdfUpload.id == pdf_id)).first()
    if row is None:
        raise HTTPException(404, "not found")
    if row.storage_path:
        storage.delete(row.storage_path)
    db.execute(delete(PdfUpload).where(PdfUpload.id == pdf_id))
    db.commit()
    return {"ok": True}
