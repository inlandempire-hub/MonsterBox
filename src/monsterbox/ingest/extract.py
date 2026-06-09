"""Stage 2 (fallback path): OCR a page image into text + a quality score.

This is the *fallback*. The primary path is the vision parser in
``parser.py``, which reads the page image directly into structured JSON and is
far more robust on dense two-column stat blocks. OCR-to-text is here for
offline / no-API operation, and because "readability is king" means we always
want a second opinion.

``pytesseract`` + Pillow are optional dependencies (``monsterbox[ocr]``). If they
are not installed we degrade gracefully with a clear warning rather than
crashing.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from .render import PageImage


@dataclass
class ExtractionResult:
    text: str
    method: str                       # "ocr" | "unavailable"
    char_count: int = 0
    quality: float = 0.0              # 0..1 heuristic confidence
    warnings: list[str] = field(default_factory=list)


# stat-block landmarks we expect to see in a good extraction
_LANDMARKS = (
    "Armor Class",
    "Hit Points",
    "Speed",
    "STR",
    "Challenge",
)


def _score_quality(text: str) -> float:
    if not text:
        return 0.0
    hits = sum(1 for token in _LANDMARKS if token.lower() in text.lower())
    return round(hits / len(_LANDMARKS), 2)


# Common Windows install locations (winget / the UB-Mannheim installer don't
# always put tesseract.exe on PATH for an already-open shell).
_WINDOWS_TESSERACT_PATHS = (
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
)


def _configure_tesseract(pytesseract) -> bool:
    """Point pytesseract at the tesseract binary. Returns True if found."""
    import os
    import shutil

    if shutil.which("tesseract"):
        return True
    for path in _WINDOWS_TESSERACT_PATHS:
        if os.path.exists(path):
            pytesseract.pytesseract.tesseract_cmd = path
            return True
    return False


def ocr_page(page: PageImage, lang: str = "eng") -> ExtractionResult:
    """Run OCR on a single page image."""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ExtractionResult(
            text="",
            method="unavailable",
            warnings=[
                "OCR fallback unavailable: install extras with "
                "`pip install monsterbox[ocr]` and the Tesseract binary."
            ],
        )

    if not _configure_tesseract(pytesseract):
        return ExtractionResult(
            text="",
            method="unavailable",
            warnings=[
                "Tesseract program not found. Install it (Windows: "
                "`winget install UB-Mannheim.TesseractOCR`) — the Python "
                "package alone is not enough."
            ],
        )

    image = Image.open(io.BytesIO(page.data))
    text = pytesseract.image_to_string(image, lang=lang)
    quality = _score_quality(text)
    warnings: list[str] = []
    if quality < 0.6:
        warnings.append(
            f"Low OCR confidence on page {page.index + 1} "
            f"(matched {int(quality * len(_LANDMARKS))}/{len(_LANDMARKS)} "
            "stat-block landmarks)."
        )
    return ExtractionResult(
        text=text,
        method="ocr",
        char_count=len(text),
        quality=quality,
        warnings=warnings,
    )
