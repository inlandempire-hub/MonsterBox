"""Web layer: the in-app PDF import endpoint (upload -> ingest -> save -> list)."""

import io

import pytest

pytest.importorskip("flask")
pytest.importorskip("reportlab")

from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from monsterbox.web import create_app  # noqa: E402

LINES = [
    "Soulscorcher Dragon",
    "Gargantuan Fiend, Lawful Evil",
    "Armor Class 23 (natural armor)",
    "Hit Points 300 (24d20 + 200)",
    "Speed 40 ft., fly 80 ft.",
    "STR DEX CON INT WIS CHA",
    "30 (+10) 14 (+2) 30 (+10) 18 (+4) 15 (+2) 20 (+5)",
    "Challenge 20 (25000 XP) Proficiency Bonus +8",
    "ACTIONS",
    "Slam. Reach 5 ft. one target.",
]


def _digital_pdf_bytes() -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 720
    for line in LINES:
        c.drawString(72, y, line)
        y -= 18
    c.showPage()
    c.save()
    return buf.getvalue()


def test_import_endpoint(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()

    pdf = _digital_pdf_bytes()
    resp = client.post(
        "/api/import",
        data={"file": (io.BytesIO(pdf), "monster.pdf")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["input_kind"] == "digital"
    assert len(data["imported"]) == 1
    assert "Soulscorcher Dragon" == data["imported"][0]["name"]

    # it now shows up in the library, with the real filename as its source
    library = client.get("/api/statblocks").get_json()
    assert any(m["name"] == "Soulscorcher Dragon" for m in library)
    sid = data["imported"][0]["id"]
    full = client.get(f"/api/statblocks/{sid}").get_json()
    assert full["source"] == "monster.pdf"
    assert full["armor_class"] == 23


def test_import_start_and_status(tmp_path):
    import time
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()

    job = client.post(
        "/api/import/start",
        data={"file": (io.BytesIO(_digital_pdf_bytes()), "monster.pdf")},
        content_type="multipart/form-data",
    ).get_json()
    job_id = job["job_id"]

    status = None
    for _ in range(50):  # poll up to ~5s for the background worker
        status = client.get(f"/api/import/status/{job_id}").get_json()
        if status["finished"]:
            break
        time.sleep(0.1)

    assert status is not None and status["finished"]
    assert status["error"] is None
    assert status["total"] >= 1
    assert any(m["name"] == "Soulscorcher Dragon" for m in status["imported"])
    # and it landed in the library
    assert any(m["name"] == "Soulscorcher Dragon"
               for m in client.get("/api/statblocks").get_json())


def test_import_rejects_non_pdf(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    resp = client.post(
        "/api/import",
        data={"file": (io.BytesIO(b"not a pdf"), "notes.txt")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400


def _import_one(client):
    return client.post(
        "/api/import",
        data={"file": (io.BytesIO(_digital_pdf_bytes()), "m.pdf")},
        content_type="multipart/form-data",
    ).get_json()["imported"][0]["id"]


def test_delete_statblock(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    sid = _import_one(client)
    assert len(client.get("/api/statblocks").get_json()) == 1

    resp = client.delete(f"/api/statblocks/{sid}")
    assert resp.get_json()["deleted"] is True
    assert client.get("/api/statblocks").get_json() == []


def test_clear_library(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    _import_one(client)
    _import_one(client)
    resp = client.delete("/api/statblocks")
    assert resp.get_json()["deleted"] == 2
    assert client.get("/api/statblocks").get_json() == []


def test_clear_rolls(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    sid = _import_one(client)
    client.post("/api/roll", json={"statblock_id": sid, "action_name": "Slam",
                                    "kind": "attack"})
    assert len(client.get("/api/rolls").get_json()) >= 1

    resp = client.delete("/api/rolls")
    assert resp.get_json()["cleared"] is True
    assert client.get("/api/rolls").get_json() == []


def test_update_statblock(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    sid = _import_one(client)

    full = client.get(f"/api/statblocks/{sid}").get_json()
    full["name"] = "Renamed Dragon"
    full["armor_class"] = 99
    full["size"] = "huge"  # free-typed; server should coerce case
    resp = client.post(f"/api/statblocks/{sid}", json=full)
    assert resp.status_code == 200

    reloaded = client.get(f"/api/statblocks/{sid}").get_json()
    assert reloaded["name"] == "Renamed Dragon"
    assert reloaded["armor_class"] == 99
    assert reloaded["size"] == "Huge"
    # id is preserved (not duplicated)
    assert len(client.get("/api/statblocks").get_json()) == 1


def test_roll_save_and_check_and_skill(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    sid = _import_one(client)

    for body in (
        {"statblock_id": sid, "kind": "check", "ability": "str"},
        {"statblock_id": sid, "kind": "save", "ability": "con"},
        {"statblock_id": sid, "kind": "skill", "skill": "Perception"},
    ):
        r = client.post("/api/roll", json=body)
        assert r.status_code == 200
        ev = r.get_json()
        assert ev["total"] == ev["dice_results"][0] + ev["modifier"]


def test_remove_combatant(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    sid = _import_one(client)
    client.post("/api/encounter/spawn", json={"statblock_id": sid, "count": 2})
    enc = client.get("/api/encounter").get_json()
    assert len(enc["combatants"]) == 2

    victim = enc["combatants"][0]["id"]
    enc2 = client.post("/api/encounter/remove", json={"combatant_id": victim}).get_json()
    assert len(enc2["combatants"]) == 1
    assert all(c["id"] != victim for c in enc2["combatants"])


def test_add_player(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    enc = client.post("/api/encounter/add-player",
                      json={"name": "Corren", "initiative": 18, "max_hp": 67}).get_json()
    assert len(enc["combatants"]) == 1
    pc = enc["combatants"][0]
    assert pc["display_name"] == "Corren"
    assert pc["is_player"] is True
    assert pc["initiative"] == 18
    assert pc["max_hp"] == 67


def test_conditions(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    sid = _import_one(client)
    client.post("/api/encounter/spawn", json={"statblock_id": sid})
    cid = client.get("/api/encounter").get_json()["combatants"][0]["id"]

    enc = client.post("/api/encounter/condition",
                      json={"combatant_id": cid, "name": "Poisoned", "action": "add"}).get_json()
    assert "Poisoned" in enc["combatants"][0]["conditions"]

    enc = client.post("/api/encounter/condition",
                      json={"combatant_id": cid, "name": "Poisoned", "action": "remove"}).get_json()
    assert "Poisoned" not in enc["combatants"][0]["conditions"]


def test_save_load_delete_encounter(tmp_path):
    app = create_app(data_dir=str(tmp_path / "data"), owner="dm")
    client = app.test_client()
    client.post("/api/encounter/add-player", json={"name": "Hero", "initiative": 12, "max_hp": 30})

    saved = client.post("/api/encounter/save", json={"name": "Goblin Ambush"}).get_json()
    assert saved["name"] == "Goblin Ambush"
    enc_id = saved["id"]

    listing = client.get("/api/encounters").get_json()
    assert any(e["id"] == enc_id and e["name"] == "Goblin Ambush" for e in listing)

    # wipe the live encounter, then reload the saved one
    client.post("/api/encounter/clear")
    assert client.get("/api/encounter").get_json()["combatants"] == []
    loaded = client.post("/api/encounter/load", json={"encounter_id": enc_id}).get_json()
    assert any(c["display_name"] == "Hero" for c in loaded["combatants"])

    assert client.delete(f"/api/encounters/{enc_id}").get_json()["deleted"] is True
    assert client.get("/api/encounters").get_json() == []
