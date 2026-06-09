"""Stage 1 of ingestion: turn a PDF into page images.

The sample PDF that drove this design is a *scanned* book — every page is a
single full-page image with **no text layer at all**. So the realistic first
move is not "extract text" (that returns nothing) but "get the page images",
which both the vision parser and the OCR fallback consume.

We extract the embedded images directly with ``pypdf`` (no external poppler /
ghostscript dependency, which matters on a fresh Windows box). If a PDF *does*
carry a real text layer we still surface it so the pipeline can skip OCR.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader


@dataclass
class PageImage:
    index: int                 # 0-based page index
    data: bytes                # raw image bytes (PNG/JPEG as embedded)
    name: str = ""             # internal image name, e.g. "Im1.png"
    width: int = 0
    height: int = 0


@dataclass
class RenderedPdf:
    path: Path
    page_count: int
    pages: list[PageImage] = field(default_factory=list)
    embedded_text: list[str] = field(default_factory=list)  # per-page text layer
    has_text_layer: bool = False

    @property
    def is_scanned(self) -> bool:
        """True when the document is effectively image-only."""
        return not self.has_text_layer and bool(self.pages)


def render_pdf(path: str | Path) -> RenderedPdf:
    """Extract page images + any embedded text layer from a PDF."""
    path = Path(path)
    reader = PdfReader(str(path))

    result = RenderedPdf(path=path, page_count=len(reader.pages))
    total_text_chars = 0

    for page in reader.pages:
        text = (page.extract_text() or "").strip()
        result.embedded_text.append(text)
        total_text_chars += len(text)

    # Heuristic: a genuine text layer yields plenty of characters per page.
    result.has_text_layer = total_text_chars > 40 * result.page_count

    # Only decode page images when we actually need them (a scan). Digital books
    # carry megabytes of full-page artwork we'd otherwise decode for nothing.
    if not result.has_text_layer:
        for i, page in enumerate(reader.pages):
            for img in page.images:
                result.pages.append(
                    PageImage(
                        index=i,
                        data=img.data,
                        name=getattr(img, "name", "") or "",
                    )
                )

    return result
