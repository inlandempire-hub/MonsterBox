"""Orchestration: PDF file -> list of StatBlocks.

One entry point handles both kinds of input a DM might have:

* **Digital PDF** (a real e-book with a selectable text layer) — we read the
  text column-aware (lore on the left, stat block on the right) and split each
  page into one body per monster. No AI, no OCR: faster, free, most accurate.
* **Scanned PDF** (a phone photo of a physical book — just images) — we send
  each page image to the vision model, or fall back to OCR offline.

    ingest_pdf(path, owner_id, parser=...) -> IngestResult

For the auto path we read the text once (pdfplumber): plenty of text means a
digital book; almost none means a scan, and only then do we decode page images.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from ..models import StatBlock
from .columns import extract_column_line_pages
import re

from .parser import (
    OcrHeuristicParser,
    StatBlockParser,
    VisionLLMParser,
    _SECTION_RE,   # section-header regex for continuation filtering
    has_actions_section,
    split_into_blocks,
)
from .render import RenderedPdf, render_pdf


@dataclass
class IngestResult:
    source: str
    page_count: int
    is_scanned: bool
    input_kind: str           # "digital" | "scanned"
    parser_used: str
    statblocks: list[StatBlock] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def ingest_pdf(
    path: str | Path,
    owner_id: str = "local-user",
    parser: Optional[StatBlockParser] = None,
    progress: Optional[Callable[[int, int], None]] = None,
) -> IngestResult:
    path = Path(path)

    # Auto mode: read the text once. Lots of text -> digital book.
    if parser is None:
        line_pages = extract_column_line_pages(path, progress=progress)
        total = sum(len(t) for page in line_pages for t, _ in page)
        if line_pages and total > 40 * len(line_pages):
            result = IngestResult(
                source=path.name,
                page_count=len(line_pages),
                is_scanned=False,
                input_kind="digital",
                parser_used="digital text-layer (column-aware)",
            )
            _blocks_from_pages(line_pages, result, owner_id, path.name)
            return result

    # Scanned, or an explicit parser was requested -> image path (needs pypdf
    # to pull the page images).
    rendered = render_pdf(path)
    result = IngestResult(
        source=path.name,
        page_count=rendered.page_count,
        is_scanned=rendered.is_scanned,
        input_kind="scanned" if rendered.is_scanned else "digital",
        parser_used="",
    )
    _ingest_images(path, rendered, result, owner_id, path.name, parser, progress)
    return result


_RE_AC_LINE = re.compile(r"^\s*Armor Class\b", re.IGNORECASE)

# Running headers / footers and other page furniture that repeats on most pages
# (book title, chapter name, thumb-index letters, page numbers). In some books
# these render in the *same decorative font as the monster names* and land right
# above a stat block in column-reading order, so the name detector swallows them
# (e.g. ToB3: "C", "TOME OF BEASTS 3" above "RAZORBACK CRAB"). We strip them
# before splitting. Structural stat-block lines that also repeat every page
# (section headers, the ability-score row, stat fields) are protected.
_ABILITY_ABBR = {"STR", "DEX", "CON", "INT", "WIS", "CHA"}
_CHROME_PROTECT_PREFIXES = (
    "armor class", "hit points", "speed", "saving throws", "skills", "senses",
    "languages", "challenge", "damage ", "condition ", "proficiency",
)
# Creature sizes — the "Size type, alignment" meta line repeats across many
# pages (e.g. "Large Beast, Unaligned") and must NOT be mistaken for chrome:
# without it the name detector can't anchor the block and falls back to Unknown.
_SIZE_WORDS = {"tiny", "small", "medium", "large", "huge", "gargantuan"}


def _is_structural_line(s: str) -> bool:
    """True for lines that legitimately repeat on every page and must be kept:
    section headers, the STR/DEX/… ability row, the secondary stat fields, and
    the size/type/alignment meta line."""
    if _SECTION_RE.match(s):
        return True
    toks = s.upper().split()
    if sum(1 for t in toks if t in _ABILITY_ABBR) >= 3:
        return True
    low = s.lower()
    words = low.split()
    if words and words[0] in _SIZE_WORDS:    # "Large Beast, Unaligned" meta line
        return True
    return any(low.startswith(p) for p in _CHROME_PROTECT_PREFIXES)


_RE_FURNITURE = re.compile(
    r"^(?:[A-Za-z]|\d{1,4}|[A-Za-z]\s+\d{1,4}|\d{1,4}\s+[A-Za-z])$"
)


def _is_page_furniture(s: str) -> bool:
    """A lone thumb-index letter ('C'), a bare page number ('98'), or the two
    combined as a single footer token ('D 136' / '136 D') — never real content."""
    return bool(_RE_FURNITURE.match(s.strip()))


def strip_page_chrome(
    line_pages: list[list[tuple[str, str]]],
) -> list[list[tuple[str, str]]]:
    """Remove running headers/footers and page furniture from every page.

    A line is treated as *chrome* when it appears (verbatim) on a meaningful
    fraction of the book's pages, is short, isn't a sentence, and isn't a
    structural stat-block line. Lone index letters and bare page numbers are
    always dropped. Returns new page lists; the input is left untouched.
    """
    import collections

    n = len(line_pages)
    if n < 4:
        return line_pages

    page_freq: collections.Counter[str] = collections.Counter()
    for page in line_pages:
        for s in {t.strip() for t, _ in page if t.strip()}:
            page_freq[s] += 1

    threshold = max(5, int(0.03 * n))   # repeats on >=5 pages or >=3% of the book
    chrome = {
        s for s, c in page_freq.items()
        if c >= threshold
        and len(s) <= 30                # running headers/footers are short
        and s[-1] not in ".!?"          # never a full sentence (a real trait line)
        and not _is_structural_line(s)
    }

    cleaned: list[list[tuple[str, str]]] = []
    for page in line_pages:
        cleaned.append([
            (t, f) for (t, f) in page
            if (t.strip() not in chrome) and not _is_page_furniture(t.strip())
        ])
    return cleaned


def _continuation_text(page: list[tuple[str, str]], sb_font: str) -> str:
    """Extract stat-block-font lines from a page for cross-page stitching.

    Used when the entire page has no new Armor Class lines (no new stat blocks
    start here), so the whole page is potential continuation content. Keeps
    every line in the stat block's body font plus any recognised section
    headers (which may be in a decorative font in some books).  Returns an
    empty string when ``sb_font`` is unknown.
    """
    if not sb_font:
        return ""
    kept = [
        text
        for text, font in page
        if font == sb_font or _SECTION_RE.match(text)
    ]
    return "\n".join(kept)


def _pre_ac_continuation_text(page: list[tuple[str, str]], sb_font: str) -> str:
    """Extract stat-block-font lines that appear *before* the first Armor Class
    line on a page.

    Used when a page contains both continuation content at the top (the tail
    of the previous page's stat block) and new stat blocks further down.
    Stops as soon as it hits any ``Armor Class …`` line so it never spills
    into the next monster's body.  Returns an empty string when ``sb_font``
    is unknown.
    """
    if not sb_font:
        return ""
    kept = []
    for text, font in page:
        if _RE_AC_LINE.match(text):
            break  # reached the next monster's stat block — stop here
        if font == sb_font or _SECTION_RE.match(text):
            kept.append(text)
    return "\n".join(kept)


def _blocks_from_pages(
    line_pages: list[list[tuple[str, str]]],
    result: IngestResult,
    owner_id: str,
    source: str,
) -> None:
    """Split each page's column-ordered (text, font) lines into one stat block
    per monster, using the font to trim trailing lore from the last feature.

    Cross-page stat blocks
    ~~~~~~~~~~~~~~~~~~~~~~
    Some books (e.g. large boss monsters in Tome of Beasts 3) start a stat
    block near the bottom of one page and continue it on the next — with lore
    sidebars and artwork filling the gap in between.  The continuation page has
    no "Armor Class" line, so ``split_into_blocks`` returns nothing for it and
    all of its combat content would be silently lost.

    We detect this by checking whether the *last* block on a page has no
    ACTIONS / BONUS ACTIONS / REACTIONS / LEGENDARY ACTIONS section header.
    A complete 5e stat block virtually always has at least an ACTIONS section,
    so its absence is a reliable signal that the block was truncated at the
    page break.  We then carry the partial block forward and, for every
    following page that yields no new blocks, extract its stat-block-font lines
    and append them.  Once a page with new blocks is found (the next monster),
    the stitched block is flushed and parsed.
    """
    # Drop running headers/footers and page furniture (book title, thumb-index
    # letters, page numbers) up front so they can't be mistaken for a stat
    # block's name when they render in the same decorative font as the title.
    line_pages = strip_page_chrome(line_pages)

    text_parser = OcrHeuristicParser()

    # pending: a stat block truncated at the end of the previous page.
    # Keys: 'body' (accumulated text), 'page' (source page number),
    #        'sb_font' (the body font — used to extract continuation lines).
    pending: dict | None = None

    def _flush_pending() -> None:
        nonlocal pending
        if pending is None:
            return
        try:
            result.statblocks.append(
                text_parser.parse_text(
                    pending["body"],
                    owner_id=owner_id,
                    source=source,
                    source_page=pending["page"],
                )
            )
        except Exception as e:  # noqa: BLE001
            result.warnings.append(
                f"skipped a block on page {pending['page']}: {e}"
            )
        pending = None

    for i, page in enumerate(line_pages):
        page_text = "\n".join(t for t, _ in page)
        fonts = [f for _, f in page]
        blocks = split_into_blocks(page_text, fonts)

        if not blocks:
            # No new stat block starts here.  If we have a pending incomplete
            # block, try to extend it with stat-block-font lines from this page.
            if pending is not None:
                continuation = _continuation_text(page, pending["sb_font"])
                if continuation.strip():
                    pending["body"] = pending["body"] + "\n" + continuation
            continue

        # New blocks found on this page.  If we have a pending incomplete block,
        # it may still have continuation content at the TOP of this page — i.e.
        # lines that appear before the first "Armor Class …" line (which is
        # where the new stat block starts).  Extract and stitch those first,
        # then flush the now-complete pending block before processing the new ones.
        if pending is not None:
            pre_ac = _pre_ac_continuation_text(page, pending["sb_font"])
            if pre_ac.strip():
                pending["body"] = pending["body"] + "\n" + pre_ac
            _flush_pending()

        # Determine the font used for the stat block body on this page.
        # Use the last Armor Class line's font (all blocks share the same body
        # font; the last one is the most relevant for the final block).
        sb_font_this_page = ""
        lines_for_font = page_text.split("\n")
        for k, ln in enumerate(lines_for_font):
            if _RE_AC_LINE.match(ln) and k < len(fonts):
                sb_font_this_page = fonts[k]

        for j, body in enumerate(blocks):
            is_last = j == len(blocks) - 1
            if is_last and not has_actions_section(body):
                # Last block on this page has no actions section — likely
                # continues on the next page.
                pending = {
                    "body": body,
                    "page": i + 1,
                    "sb_font": sb_font_this_page,
                }
            else:
                try:
                    result.statblocks.append(
                        text_parser.parse_text(
                            body,
                            owner_id=owner_id,
                            source=source,
                            source_page=i + 1,
                        )
                    )
                except Exception as e:  # noqa: BLE001
                    result.warnings.append(f"skipped a block on page {i + 1}: {e}")

    # End of book — flush whatever is still pending.
    _flush_pending()

    if not result.statblocks:
        result.warnings.append(
            "No stat blocks found (no 'Size type, alignment' lines detected). "
            "If this is a scan, use the vision or OCR parser."
        )


def _ingest_images(
    path: Path,
    rendered: RenderedPdf,
    result: IngestResult,
    owner_id: str,
    source: str,
    parser: Optional[StatBlockParser],
    progress: Optional[Callable[[int, int], None]] = None,
) -> None:
    """Read scanned PDFs from page images (vision primary, OCR fallback)."""
    chosen = parser or _default_parser()
    result.parser_used = getattr(chosen, "name", type(chosen).__name__)
    if rendered.is_scanned:
        result.warnings.append(
            "Document has no text layer (scanned). Vision/OCR parsing required."
        )

    # A born-digital PDF with no embedded images but text we could have read:
    # only happens if a parser was forced. Fall back to the text layer.
    if not rendered.pages and rendered.has_text_layer:
        result.warnings.append(
            "No page images found; using the embedded text layer instead."
        )
        _blocks_from_pages(
            extract_column_line_pages(path), result, owner_id, source
        )
        result.parser_used = "digital text-layer (column-aware)"
        return

    total = len(rendered.pages)
    for n, page in enumerate(rendered.pages):
        try:
            result.statblocks.extend(
                chosen.parse(page, owner_id=owner_id, source=source)
            )
        except NotImplementedError:
            result.warnings.append(
                f"Parser '{result.parser_used}' is not active (no LLM client). "
                "Falling back to the OCR heuristic parser."
            )
            fallback = OcrHeuristicParser()
            result.parser_used = fallback.name
            result.statblocks.extend(
                fallback.parse(page, owner_id=owner_id, source=source)
            )
        if progress:
            progress(n + 1, total)


def _default_parser() -> StatBlockParser:
    """Prefer the vision parser when an API key is configured, else OCR."""
    return VisionLLMParser.from_env() or OcrHeuristicParser()
