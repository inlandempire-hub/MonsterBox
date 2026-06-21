"""BETA-ONLY: Supabase Storage helpers for collected PDFs.

Uploads are STREAMED (http.client reads the file object in blocks), so memory
stays low no matter how big the file is — the whole point of moving off the DB.
Downloads are short-lived signed URLs served direct from Supabase, so the app
server never handles the bytes. stdlib urllib only (no extra dependency).

Retire with the rest of the beta feature: unset SUPABASE_SERVICE_KEY.
"""
import json
import urllib.error
import urllib.request

from .config import settings


def _headers(extra: dict | None = None) -> dict:
    h = {
        "Authorization": f"Bearer {settings.supabase_service_key}",
        "apikey": settings.supabase_service_key,
    }
    if extra:
        h.update(extra)
    return h


def _obj_url(path: str) -> str:
    return f"{settings.supabase_base}/storage/v1/object/{settings.beta_storage_bucket}/{path}"


def upload(path: str, fileobj, size: int, content_type: str = "application/pdf") -> None:
    """Stream a file-like object to the bucket. Content-Length is set so http.client
    streams `fileobj` in blocks rather than buffering it. Raises on failure."""
    req = urllib.request.Request(
        _obj_url(path), data=fileobj, method="POST",
        headers=_headers({"Content-Type": content_type, "Content-Length": str(size), "x-upsert": "true"}),
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"storage upload HTTP {resp.status}")
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"storage upload HTTP {e.code}: {body}") from None


def signed_url(path: str, expires: int = 3600) -> str:
    """A time-limited URL the browser can download from directly."""
    url = f"{settings.supabase_base}/storage/v1/object/sign/{settings.beta_storage_bucket}/{path}"
    req = urllib.request.Request(
        url, data=json.dumps({"expiresIn": expires}).encode(), method="POST",
        headers=_headers({"Content-Type": "application/json"}),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode())
    signed = body.get("signedURL") or body.get("signedUrl") or ""
    if not signed:
        raise RuntimeError(f"no signedURL in response: {str(body)[:200]}")
    if signed.startswith("http"):
        return signed
    # Supabase returns a path RELATIVE to /storage/v1 (e.g. /object/sign/<bucket>/
    # <path>?token=...). The full download URL therefore needs the /storage/v1
    # segment that the bare base is missing — without it the link 404s.
    if not signed.startswith("/"):
        signed = "/" + signed
    if not signed.startswith("/storage/v1"):
        signed = "/storage/v1" + signed
    return settings.supabase_base + signed


def delete(path: str) -> None:
    """Best-effort delete of a stored object."""
    req = urllib.request.Request(_obj_url(path), method="DELETE", headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=30):
            pass
    except urllib.error.HTTPError:
        pass
