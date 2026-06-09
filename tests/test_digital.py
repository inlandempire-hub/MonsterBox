"""Digital-PDF path: a born-digital PDF (real text layer) is read straight from
its text, no image/OCR/vision needed. We generate a tiny PDF with reportlab so
the test is self-contained."""

import pytest

reportlab = pytest.importorskip("reportlab")

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from monsterbox.ingest import ingest_pdf  # noqa: E402

STATBLOCK_LINES = [
    "Soulscorcher Dragon",
    "Gargantuan Fiend, Lawful Evil",
    "Armor Class 23 (natural armor)",
    "Hit Points 300 (24d20 + 200)",
    "Speed 40 ft., fly 80 ft.",
    "STR DEX CON INT WIS CHA",
    "30 (+10) 14 (+2) 30 (+10) 18 (+4) 15 (+2) 20 (+5)",
    "Challenge 20 (25000 XP) Proficiency Bonus +8",
]


def _make_digital_pdf(path):
    c = canvas.Canvas(str(path), pagesize=letter)
    y = 720
    for line in STATBLOCK_LINES:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()


def test_digital_pdf_read_from_text_layer(tmp_path):
    pdf = tmp_path / "monster.pdf"
    _make_digital_pdf(pdf)

    result = ingest_pdf(pdf, owner_id="dm1")

    assert result.input_kind == "digital"
    assert result.is_scanned is False
    assert "text-layer" in result.parser_used
    assert len(result.statblocks) == 1

    sb = result.statblocks[0]
    assert sb.name == "Soulscorcher Dragon"
    assert sb.armor_class == 23
    assert sb.hit_points == 300
    assert sb.challenge_rating == "20"
    assert sb.owner_id == "dm1"
