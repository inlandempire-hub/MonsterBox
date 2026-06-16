"""Public "report an issue" endpoint. Anyone (signed in or not) can send a bug
report with an optional screenshot. Every report is stored in the DB; if email is
configured it's also sent to settings.report_to with the screenshot attached.

Delivery prefers Resend's HTTP API (port 443) over SMTP, because hosts like
Render block outbound SMTP ports (25/465/587) — there, smtplib just times out.
Falls back to SMTP when no Resend key is available.
"""
import base64
import json
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..auth import require_admin
from ..config import settings
from ..db import get_db
from ..models import Report, User

router = APIRouter(prefix="/api", tags=["report"])

MAX_MESSAGE = 5000
MAX_IMAGE_BYTES = 6 * 1024 * 1024   # 6 MB


def _resend_api_key() -> str:
    """The Resend HTTP API key, if we can use the HTTP path. An explicit
    REPORT_RESEND_API_KEY wins; otherwise reuse the SMTP password when it's a
    Resend key (re_...) so no extra env var is needed."""
    if settings.report_resend_api_key:
        return settings.report_resend_api_key
    if "resend.com" in (settings.report_smtp_host or "").lower() \
            and settings.report_smtp_password.startswith("re_"):
        return settings.report_smtp_password
    return ""


def _send_via_resend_http(api_key: str, message: str, reply_to: str | None,
                          image: bytes | None, image_name: str | None) -> None:
    payload = {
        "from": settings.report_from or "onboarding@resend.dev",
        "to": [settings.report_to],
        "subject": "MonsterBox issue report",
        "text": f"From: {reply_to or '(not provided)'}\n\n{message}",
    }
    if reply_to:
        payload["reply_to"] = reply_to
    if image:
        payload["attachments"] = [{
            "filename": image_name or "screenshot.png",
            "content": base64.b64encode(image).decode(),
        }]
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            # Resend's API is behind Cloudflare, which bans the default
            # "Python-urllib/x" signature (error 1010). Send a real UA.
            "User-Agent": "MonsterBox/1.0 (issue-report)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"Resend HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"Resend HTTP {e.code}: {body}") from None


def _send_via_smtp(message: str, reply_to: str | None, image: bytes | None, image_name: str | None) -> None:
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


def _send_email(message: str, reply_to: str | None, image: bytes | None, image_name: str | None) -> None:
    key = _resend_api_key()
    if key:
        _send_via_resend_http(key, message, reply_to, image, image_name)
    else:
        _send_via_smtp(message, reply_to, image, image_name)


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
    if settings.email_ready:
        try:
            _send_email(message, row.email, image_bytes, image_name)
            emailed = True
            row.emailed = True
            db.commit()
        except Exception:
            emailed = False   # stored anyway; don't fail the user's submission

    return {"ok": True, "emailed": emailed}


@router.get("/report/diag")
def report_diag(_admin: User = Depends(require_admin)):
    """Admin-only: show whether SMTP is configured and attempt a live test send,
    surfacing the exact error so email delivery can be diagnosed. Reveals only
    whether secrets are present (not their values), plus the From/To addresses."""
    transport = "resend-http" if _resend_api_key() else ("smtp" if settings.smtp_ready else "none")
    info = {
        "smtp_ready": settings.smtp_ready,
        "email_ready": settings.email_ready,
        "transport": transport,
        "host": settings.report_smtp_host or "(unset)",
        "port": settings.report_smtp_port,
        "user_set": bool(settings.report_smtp_user),
        "password_set": bool(settings.report_smtp_password),
        "from": settings.report_from or settings.report_smtp_user or "(unset)",
        "to": settings.report_to or "(unset)",
    }
    if not settings.email_ready:
        info["test_send"] = "skipped — email not configured"
        return info
    try:
        _send_email("MonsterBox SMTP diagnostic test (admin /report/diag).", None, None, None)
        info["test_send"] = "ok"
    except Exception as e:
        info["test_send"] = f"{type(e).__name__}: {e}"
    return info
