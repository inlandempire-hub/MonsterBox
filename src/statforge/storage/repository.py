"""Owner-scoped, local-first persistence.

Everything is keyed by ``owner_id`` and stored under ``<root>/<owner_id>/``.
That is the whole multi-tenant story for the skeleton: one directory per
tenant, hard filesystem isolation, and a schema that already carries the owner
key so a future move to a real per-tenant database is a backend swap rather
than a model migration.

Roll events are appended to a JSON-Lines log (one event per line) — cheap to
append, naturally ordered, and trivially filterable by ``private`` for the
DM-privacy requirement.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

from ..models import Encounter, RollEvent, StatBlock


class Repository:
    def __init__(self, root: str | Path = "data"):
        self.root = Path(root)

    # --- path helpers (owner isolation lives here) ----------------------- #
    def _dir(self, owner_id: str, kind: str) -> Path:
        d = self.root / owner_id / kind
        d.mkdir(parents=True, exist_ok=True)
        return d

    # --- statblocks ------------------------------------------------------- #
    def save_statblock(self, sb: StatBlock) -> Path:
        path = self._dir(sb.owner_id, "statblocks") / f"{sb.id}.json"
        path.write_text(sb.model_dump_json(indent=2), encoding="utf-8")
        return path

    def get_statblock(self, owner_id: str, sb_id: str) -> StatBlock:
        path = self._dir(owner_id, "statblocks") / f"{sb_id}.json"
        return StatBlock.model_validate_json(path.read_text(encoding="utf-8"))

    def list_statblocks(self, owner_id: str) -> list[StatBlock]:
        out: list[StatBlock] = []
        for p in sorted(self._dir(owner_id, "statblocks").glob("*.json")):
            out.append(StatBlock.model_validate_json(p.read_text(encoding="utf-8")))
        return out

    def delete_statblock(self, owner_id: str, sb_id: str) -> bool:
        path = self._dir(owner_id, "statblocks") / f"{sb_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def delete_all_statblocks(self, owner_id: str) -> int:
        count = 0
        for p in self._dir(owner_id, "statblocks").glob("*.json"):
            p.unlink()
            count += 1
        return count

    # --- encounters ------------------------------------------------------- #
    def save_encounter(self, enc: Encounter) -> Path:
        path = self._dir(enc.owner_id, "encounters") / f"{enc.id}.json"
        path.write_text(enc.model_dump_json(indent=2), encoding="utf-8")
        return path

    def get_encounter(self, owner_id: str, enc_id: str) -> Encounter:
        path = self._dir(owner_id, "encounters") / f"{enc_id}.json"
        return Encounter.model_validate_json(path.read_text(encoding="utf-8"))

    def list_encounters(self, owner_id: str) -> list[Encounter]:
        out: list[Encounter] = []
        for p in sorted(self._dir(owner_id, "encounters").glob("*.json")):
            out.append(Encounter.model_validate_json(p.read_text(encoding="utf-8")))
        return out

    def delete_encounter(self, owner_id: str, enc_id: str) -> bool:
        path = self._dir(owner_id, "encounters") / f"{enc_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    # --- roll log (JSON Lines) ------------------------------------------- #
    def append_roll(self, event: RollEvent) -> None:
        path = self._dir(event.owner_id, "") / "rolls.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(event.model_dump_json() + "\n")

    def clear_rolls(self, owner_id: str) -> None:
        path = self.root / owner_id / "rolls.jsonl"
        if path.exists():
            path.unlink()

    def read_rolls(
        self, owner_id: str, include_private: bool = True
    ) -> Iterator[RollEvent]:
        path = self.root / owner_id / "rolls.jsonl"
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = RollEvent.model_validate(json.loads(line))
            if include_private or not event.private:
                yield event
