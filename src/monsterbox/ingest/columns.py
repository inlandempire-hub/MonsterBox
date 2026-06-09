"""Column-aware text extraction for digital PDFs.

Real rulebooks are typeset in two columns (lore on the left, stat block on the
right). A naive `extract_text()` reads straight across the page and interleaves
the two, dropping stat-block lines into the middle of lore sentences. We instead
group words into columns by horizontal position and read each column
top-to-bottom, so a stat block comes out clean and contiguous.

Each line also carries its dominant **font** (normalised — subset prefix and
weight/style suffix stripped). The stat block, the surrounding lore, section
headers, and sidebars are set in different fonts, so the font lets the parser
tell where a stat block ends (and stop sweeping page lore into the last
feature). Requires pdfplumber (a core dependency).
"""

from __future__ import annotations

import collections
from pathlib import Path
from typing import Callable, Optional

Line = tuple[str, str]  # (text, font-family)
Progress = Optional[Callable[[int, int], None]]  # (pages_done, pages_total)


def _normalize_font(name: str | None) -> str:
    """'GAAAAA+ScalySans-Bold' -> 'ScalySans'."""
    n = (name or "").split("+")[-1]
    n = n.split("-")[0]
    n = n.split(",")[0]
    return n


def _lines_from_words(words: list[dict]) -> list[Line]:
    """Group words into (text, dominant-font) lines, top→bottom, left→right.

    Words are grouped into a line by vertical position, then each line is sorted
    strictly left-to-right by x. (Sorting the whole page by rounded-top first
    would scramble word order on lines whose labels sit a sub-pixel off the
    baseline — e.g. italic "Hit:" in a stat-block attack.)
    """
    words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[Line] = []
    current: list[dict] = []
    current_top: float | None = None

    def flush():
        if not current:
            return
        ordered = sorted(current, key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ordered)
        fonts = collections.Counter(
            _normalize_font(w.get("fontname")) for w in ordered
        )
        lines.append((text, fonts.most_common(1)[0][0]))

    for w in words:
        if current_top is None or abs(w["top"] - current_top) <= 4:
            current.append(w)
            if current_top is None:
                current_top = w["top"]
        else:
            flush()
            current = [w]
            current_top = w["top"]
    flush()
    return lines


def page_lines(page) -> list[Line]:
    """Column-ordered (left then right) lines with fonts for one page."""
    words = page.extract_words(extra_attrs=["fontname"], use_text_flow=False)
    if not words:
        return []
    mid = page.width / 2
    left = [w for w in words if (w["x0"] + w["x1"]) / 2 < mid]
    right = [w for w in words if (w["x0"] + w["x1"]) / 2 >= mid]
    return _lines_from_words(left) + _lines_from_words(right)


def page_column_text(page) -> str:
    """Plain column-ordered text for one page (fonts dropped)."""
    return "\n".join(t for t, _ in page_lines(page)).strip()


def extract_column_line_pages(
    path: str | Path, progress: Progress = None
) -> list[list[Line]]:
    """Column-aware (text, font) lines for every page of a digital PDF.

    Calls ``progress(pages_done, pages_total)`` after each page so a caller can
    drive a progress bar — this loop is the slow part of a big-book import.
    """
    import pdfplumber

    pages: list[list[Line]] = []
    with pdfplumber.open(str(path)) as pdf:
        total = len(pdf.pages)
        for i, page in enumerate(pdf.pages):
            try:
                pages.append(page_lines(page))
            except Exception:
                # never let one bad page abort a whole book import
                text = page.extract_text() or ""
                pages.append([(ln, "") for ln in text.split("\n")])
            if progress:
                progress(i + 1, total)
    return pages


def extract_column_pages(path: str | Path) -> list[str]:
    """Column-aware plain text for every page (compatibility helper)."""
    return [
        "\n".join(t for t, _ in page).strip()
        for page in extract_column_line_pages(path)
    ]
