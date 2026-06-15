"""Public "report an issue" endpoint. Anyone (signed in or not) can send a bug
report with an optional screenshot. Every report is stored in the DB; if SMTP is
configured it's also emailed to settings.report_to with the screenshot attached.
"""
import smtplib
from email.message import EmailMessage

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import Report

router = APIRouter(prefix="/api", tags=["report"])

MAX_MESSAGE = 5000
MAX_IMAGE_BYTES = 6 * 1024 * 1024   # 6 MB


def _send_email(message: str, reply_to: str | None, image: bytes | None, image_name: str | None) -> None:
    msg = EmailMessage()
    msg["Subject"] = "MonsterBox issue report"
    msg["From"] = settings.report_from or settings.report_smtp_user
    msg["To"] = settings.report_to
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.set_content(f"From: {reply_to or '(not provided)'}\n\n{message}")
    if image:
        subtype = (image_name or "screenshot.png").rsplit(".", 1)[-1].lower()
        if subtype == "jpg":
            subtype = "jpeg"
        msg.add_attachment(image, maintype="image", subtype=subtype,
                           filename=image_name or "screenshot.png")
    with smtplib.SMTP(settings.report_smtp_host, settings.report_smtp_port, timeout=20) as s:
        s.starttls()
        s.login(settings.report_smtp_user, settings.report_smtp_password)
        s.send_message(msg)


@router.post("/report")
async def report(
    message: str = Form(...),
    email: str | None = Form(None),
    screenshot: UploadFile | None = File(None),
    db: Session = Depends(get_db),
):
    message = (message or "").strip()
    if not message:
        raise HTTPException(400, "Please describe the issue.")
    if len(message) > MAX_MESSAGE:
        raise HTTPException(400, "Message is too long.")

    image_bytes = None
    image_name = None
    if screenshot is not None and screenshot.filename:
        image_bytes = await screenshot.read()
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(400, "Screenshot is too large (max 6 MB).")
        image_name = screenshot.filename

    row = Report(email=(email or "").strip() or None, message=message,
                 had_screenshot=bool(image_bytes),
                 screenshot=image_bytes, screenshot_mime=(screenshot.content_type if image_bytes else None))
    db.add(row)
    db.commit()

    emailed = False
    if settings.smtp_ready:
        try:
            _send_email(message, row.email, image_bytes, image_name)
            emailed = True
            row.emailed = True
            db.commit()
        except Exception:
            emailed = False   # stored anyway; don't fail the user's submission

    return {"ok": True, "emailed": emailed}
