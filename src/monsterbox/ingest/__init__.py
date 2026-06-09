"""Ingestion: PDF -> page images -> structured StatBlock.

The public surface is :func:`ingest_pdf` plus the swappable parsers. Everything
flows through the ``parse(page, owner_id, source) -> StatBlock`` boundary so it
can run locally or behind a hosted endpoint unchanged.
"""

from .parser import (
    OcrHeuristicParser,
    StatBlockParser,
    VisionLLMParser,
)
from .pipeline import IngestResult, ingest_pdf
from .render import PageImage, RenderedPdf, render_pdf

__all__ = [
    "ingest_pdf",
    "IngestResult",
    "render_pdf",
    "RenderedPdf",
    "PageImage",
    "StatBlockParser",
    "VisionLLMParser",
    "OcrHeuristicParser",
]
