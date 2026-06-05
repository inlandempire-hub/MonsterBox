"""Flask app exposing the engine to the browser UI.

Endpoints (all JSON except `/`):
    GET  /                          -> the single-page UI
    GET  /api/statblocks            -> library list (id, name, cr, ac, hp)
    GET  /api/statblocks/<id>       -> one full stat block
    GET  /api/encounter             -> current initiative tracker state
    POST /api/encounter/spawn       -> add a monster to the encounter
    POST /api/encounter/damage      -> apply damage / healing to a combatant
    POST /api/encounter/next        -> advance to the next turn
    POST /api/encounter/clear       -> empty the encounter
    POST /api/roll                  -> roll an action's attack or damage
    GET  /api/rolls                 -> recent roll-log events

The encounter lives in memory for the session (single local DM). Stat blocks
and the roll log persist through the owner-scoped Repository.
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

from ..combat import InitiativeTracker, Roller
from ..ingest import ingest_pdf
from ..models import Ability, Action, RollType, Size, StatBlock
from ..storage import Repository

_STATIC = Path(__file__).parent / "static"


def _cr_value(cr: Optional[str]) -> float:
    """Numeric value of a challenge rating string ('1/2' -> 0.5) for sorting.
    Unknown / unparseable ratings sort to the end."""
    if not cr:
        return float("inf")
    cr = cr.strip()
    try:
        if "/" in cr:
            num, den = cr.split("/")
            return float(num) / float(den)
        return float(cr)
    except (ValueError, ZeroDivisionError):
        return float("inf")


def _find_action(sb: StatBlock, name: str) -> Optional[Action]:
    for bucket in (
        sb.actions,
        sb.legendary_actions,
        sb.bonus_actions,
        sb.reactions,
        sb.traits,
    ):
        for a in bucket:
            if a.name == name:
                return a
    return None


def _encounter_dump(tracker: InitiativeTracker) -> dict:
    enc = tracker.encounter
    return {
        "round": enc.round,
        "active_index": enc.active_index,
        "combatants": [
            {
                "id": c.id,
                "display_name": c.display_name,
                "initiative": c.initiative,
                "current_hp": c.current_hp,
                "max_hp": c.max_hp,
                "temp_hp": c.temp_hp,
                "armor_class": c.armor_class,
                "statblock_id": c.statblock_id,
                "is_player": c.is_player,
                "conditions": [cc.name for cc in c.conditions],
            }
            for c in enc.combatants
        ],
    }


def start_idle_watchdog(
    app: Flask,
    timeout: float,
    *,
    startup_grace: float = 30.0,
    check_interval: float = 3.0,
) -> None:
    """Exit the process when the page stops sending heartbeats.

    Used by the windowless launcher so the hidden server doesn't outlive the
    app: the page POSTs ``/api/ping`` every few seconds; once it's closed the
    pings stop, and ``timeout`` seconds later this watchdog ends the process.
    A ``startup_grace`` keeps it alive while the browser is still opening.
    """
    started = time.time()

    def loop() -> None:
        while True:
            time.sleep(check_interval)
            now = time.time()
            if now - started < startup_grace:
                continue
            last = app.config.get("_last_ping", started)
            if now - last > timeout:
                os._exit(0)        # forceful, immediate; it's a local single-user app

    threading.Thread(target=loop, daemon=True).start()


def create_app(data_dir: str = "data", owner: str = "local-user") -> Flask:
    app = Flask(__name__, static_folder=str(_STATIC), static_url_path="")
    repo = Repository(data_dir)
    state = {
        "tracker": InitiativeTracker(),
        "roller": Roller(owner_id=owner),
    }

    def statblock_index() -> dict[str, StatBlock]:
        return {sb.id: sb for sb in repo.list_statblocks(owner)}

    # Heartbeat: the page pings this while it's open. The idle watchdog (see
    # start_idle_watchdog / the `serve --shutdown-on-idle` flag) uses the last
    # ping time to shut a *hidden* server down shortly after the app is closed.
    app.config["_last_ping"] = time.time()

    @app.get("/")
    def index():
        return send_from_directory(_STATIC, "index.html")

    @app.post("/api/ping")
    def ping():
        app.config["_last_ping"] = time.time()
        return jsonify({"ok": True})

    @app.get("/api/statblocks")
    def list_statblocks():
        items = []
        for sb in repo.list_statblocks(owner):
            items.append(
                {
                    "id": sb.id,
                    "name": sb.name,
                    "challenge_rating": sb.challenge_rating,
                    "armor_class": sb.armor_class,
                    "hit_points": sb.hit_points,
                    "creature_type": sb.creature_type,
                    "size": sb.size.value if sb.size else None,
                    "parse_confidence": sb.parse_confidence,
                }
            )
        # sort by challenge rating (ascending) for encounter building, then name
        items.sort(key=lambda x: (_cr_value(x["challenge_rating"]), x["name"].lower()))
        return jsonify(items)

    @app.get("/api/statblocks/<sid>")
    def get_statblock(sid):
        sb = repo.get_statblock(owner, sid)
        return jsonify(sb.model_dump(mode="json"))

    _SIZES = {s.value.lower(): s.value for s in Size}

    @app.post("/api/statblocks/<sid>")
    def update_statblock(sid):
        data = request.get_json(force=True)
        data["id"] = sid           # ids/owner are server-controlled, not editable
        data["owner_id"] = owner
        # tolerate a free-typed size: match case-insensitively, else clear it
        data["size"] = _SIZES.get(str(data.get("size") or "").strip().lower())
        try:
            sb = StatBlock.model_validate(data)
        except Exception as e:
            return jsonify({"error": f"invalid stat block: {e}"}), 400
        repo.save_statblock(sb)
        return jsonify(sb.model_dump(mode="json"))

    @app.delete("/api/statblocks/<sid>")
    def delete_statblock(sid):
        return jsonify({"deleted": repo.delete_statblock(owner, sid)})

    @app.delete("/api/statblocks")
    def clear_statblocks():
        return jsonify({"deleted": repo.delete_all_statblocks(owner)})

    # Background import jobs (for the progress bar). Keyed by job id; updated by a
    # worker thread, polled by the browser. Fine for a single local DM.
    jobs: dict[str, dict] = {}

    @app.post("/api/import/start")
    def import_start():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file uploaded"}), 400
        if not f.filename.lower().endswith(".pdf"):
            return jsonify({"error": "please upload a .pdf file"}), 400

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        f.save(tmp.name)
        tmp.close()
        filename = f.filename
        job_id = uuid.uuid4().hex
        jobs[job_id] = {
            "current": 0, "total": 0, "finished": False,
            "imported": [], "error": None, "source": filename,
            "input_kind": None, "warnings": [],
        }

        def work():
            job = jobs[job_id]
            try:
                def prog(cur, total):
                    job["current"], job["total"] = cur, total

                result = ingest_pdf(tmp.name, owner_id=owner, progress=prog)
                for sb in result.statblocks:
                    sb.source = filename
                    repo.save_statblock(sb)
                    job["imported"].append(
                        {"id": sb.id, "name": sb.name,
                         "confidence": sb.parse_confidence}
                    )
                job["input_kind"] = result.input_kind
                job["warnings"] = result.warnings
            except Exception as e:  # noqa: BLE001 - surface any failure to the UI
                job["error"] = str(e)
            finally:
                job["finished"] = True
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass

        threading.Thread(target=work, daemon=True).start()
        return jsonify({"job_id": job_id})

    @app.get("/api/import/status/<job_id>")
    def import_status(job_id):
        job = jobs.get(job_id)
        if job is None:
            return jsonify({"error": "unknown job"}), 404
        return jsonify(job)

    @app.post("/api/import")
    def import_pdf():
        f = request.files.get("file")
        if f is None or not f.filename:
            return jsonify({"error": "no file uploaded"}), 400
        if not f.filename.lower().endswith(".pdf"):
            return jsonify({"error": "please upload a .pdf file"}), 400

        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            f.save(tmp.name)
            tmp.close()
            result = ingest_pdf(tmp.name, owner_id=owner)
            imported = []
            for sb in result.statblocks:
                sb.source = f.filename  # keep the real name, not the temp path
                repo.save_statblock(sb)
                imported.append(
                    {
                        "id": sb.id,
                        "name": sb.name,
                        "confidence": sb.parse_confidence,
                    }
                )
            return jsonify(
                {
                    "input_kind": result.input_kind,
                    "parser_used": result.parser_used,
                    "warnings": result.warnings,
                    "imported": imported,
                }
            )
        finally:
            os.unlink(tmp.name)

    @app.get("/api/encounter")
    def get_encounter():
        return jsonify(_encounter_dump(state["tracker"]))

    @app.post("/api/encounter/spawn")
    def spawn():
        data = request.get_json(force=True)
        sb = repo.get_statblock(owner, data["statblock_id"])
        state["tracker"].spawn(sb, int(data.get("count", 1)))
        state["tracker"].roll_initiative(statblock_index(), state["roller"])
        return jsonify(_encounter_dump(state["tracker"]))

    @app.post("/api/encounter/damage")
    def damage():
        data = request.get_json(force=True)
        tracker = state["tracker"]
        combatant = next(
            (c for c in tracker.encounter.combatants if c.id == data["combatant_id"]),
            None,
        )
        if combatant is None:
            return jsonify({"error": "combatant not found"}), 404
        amount = int(data["amount"])
        if amount >= 0:
            tracker.apply_damage(combatant, amount)
        else:
            tracker.heal(combatant, -amount)
        return jsonify(_encounter_dump(tracker))

    @app.post("/api/encounter/remove")
    def remove_combatant():
        data = request.get_json(force=True)
        state["tracker"].remove(data["combatant_id"])
        return jsonify(_encounter_dump(state["tracker"]))

    @app.post("/api/encounter/add-player")
    def add_player():
        data = request.get_json(force=True)
        tracker = state["tracker"]
        tracker.add_player(
            name=data.get("name") or "Player",
            initiative=int(data.get("initiative") or 0),
            max_hp=int(data.get("max_hp") or 0),
        )
        tracker.sort()
        return jsonify(_encounter_dump(tracker))

    @app.post("/api/encounter/condition")
    def condition():
        data = request.get_json(force=True)
        tracker = state["tracker"]
        combatant = next(
            (c for c in tracker.encounter.combatants if c.id == data["combatant_id"]),
            None,
        )
        if combatant is None:
            return jsonify({"error": "combatant not found"}), 404
        name = data["name"]
        if data.get("action") == "remove":
            tracker.remove_condition(combatant, name)
        else:
            tracker.add_condition(combatant, name)
        return jsonify(_encounter_dump(tracker))

    # --- saved encounters --------------------------------------------------- #
    @app.post("/api/encounter/save")
    def save_encounter():
        data = request.get_json(force=True)
        enc = state["tracker"].encounter
        if data.get("name"):
            enc.name = data["name"]
        enc.owner_id = owner
        repo.save_encounter(enc)
        return jsonify({"id": enc.id, "name": enc.name})

    @app.get("/api/encounters")
    def list_encounters():
        return jsonify([
            {"id": e.id, "name": e.name, "combatants": len(e.combatants),
             "round": e.round}
            for e in repo.list_encounters(owner)
        ])

    @app.post("/api/encounter/load")
    def load_encounter():
        data = request.get_json(force=True)
        enc = repo.get_encounter(owner, data["encounter_id"])
        state["tracker"] = InitiativeTracker(enc)
        return jsonify(_encounter_dump(state["tracker"]))

    @app.delete("/api/encounters/<eid>")
    def delete_encounter(eid):
        return jsonify({"deleted": repo.delete_encounter(owner, eid)})

    @app.post("/api/encounter/next")
    def next_turn():
        state["tracker"].next_turn()
        return jsonify(_encounter_dump(state["tracker"]))

    @app.post("/api/encounter/clear")
    def clear():
        state["tracker"] = InitiativeTracker()
        return jsonify(_encounter_dump(state["tracker"]))

    @app.post("/api/roll")
    def roll():
        data = request.get_json(force=True)
        sb = repo.get_statblock(owner, data["statblock_id"])
        source = data.get("source") or sb.name
        roller = state["roller"]
        kind = data.get("kind", "attack")
        adv = data.get("advantage")

        if kind in ("attack", "damage"):
            action = _find_action(sb, data["action_name"])
            if action is None:
                return jsonify({"error": "action not found"}), 404
            if kind == "damage":
                event = roller.damage_roll(action, source=source,
                                           crit=bool(data.get("crit")))
            else:
                event = roller.attack_roll(action, source=source, advantage=adv)
        elif kind == "initiative":
            mod = sb.abilities.modifier(Ability.DEX)
            event = roller.d20(mod, source, "Initiative", RollType.CHECK, adv)
        elif kind == "skill":
            skill = data["skill"]
            bonus = next((v for k, v in sb.skills.items()
                          if k.lower() == skill.lower()), 0)
            event = roller.d20(bonus, source, f"{skill} check",
                               RollType.CHECK, adv)
        elif kind in ("save", "check"):
            ability = Ability(data["ability"])
            mod = sb.abilities.modifier(ability)
            if kind == "save":
                total = next((v for k, v in sb.saving_throws.items()
                              if k.lower() == ability.value), None)
                modifier = total if total is not None else mod
                label = f"{ability.value.upper()} save"
                rtype = RollType.SAVE
            else:
                modifier = mod
                label = f"{ability.value.upper()} check"
                rtype = RollType.CHECK
            event = roller.d20(modifier, source, label, rtype, adv)
        else:
            return jsonify({"error": f"unknown roll kind '{kind}'"}), 400

        repo.append_roll(event)
        return jsonify(event.model_dump(mode="json"))

    @app.get("/api/rolls")
    def rolls():
        # chronological (oldest first); the UI shows the newest roll at the bottom
        events = list(repo.read_rolls(owner))[-30:]
        return jsonify([e.model_dump(mode="json") for e in events])

    @app.delete("/api/rolls")
    def clear_rolls():
        repo.clear_rolls(owner)
        return jsonify({"cleared": True})

    return app
