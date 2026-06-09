"""Initiative tracker — the heart of the "live character sheet" experience.

Embodies the template-vs-instance rule: :meth:`spawn` takes a StatBlock
*template* and produces independent Combatant *instances*. Drop the same
monster in three times and each gets its own HP, conditions and legendary
action pool.
"""

from __future__ import annotations

from typing import Optional

from ..models import Combatant, ConditionState, Encounter, StatBlock
from .roller import Roller


class InitiativeTracker:
    def __init__(self, encounter: Optional[Encounter] = None):
        self.encounter = encounter or Encounter()

    # --- building the field ---------------------------------------------- #
    def spawn(self, statblock: StatBlock, count: int = 1) -> list[Combatant]:
        """Create ``count`` live combatants from a template."""
        created: list[Combatant] = []
        existing = sum(
            1
            for c in self.encounter.combatants
            if c.statblock_id == statblock.id
        )
        for n in range(count):
            label = statblock.name
            if count > 1 or existing:
                label = f"{statblock.name} #{existing + n + 1}"
            combatant = Combatant(
                owner_id=statblock.owner_id,
                statblock_id=statblock.id,
                display_name=label,
                max_hp=statblock.hit_points,
                current_hp=statblock.hit_points,
                armor_class=statblock.armor_class,
                legendary_actions_remaining=statblock.legendary_action_count,
            )
            self.encounter.combatants.append(combatant)
            created.append(combatant)
        return created

    def add_player(self, name: str, initiative: int, max_hp: int = 0) -> Combatant:
        c = Combatant(
            owner_id=self.encounter.owner_id,
            statblock_id="",
            display_name=name,
            initiative=initiative,
            max_hp=max_hp,
            current_hp=max_hp,
            is_player=True,
        )
        self.encounter.combatants.append(c)
        return c

    # --- turn order ------------------------------------------------------- #
    def roll_initiative(
        self, statblocks: dict[str, StatBlock], roller: Roller
    ) -> None:
        """Roll initiative for every non-player combatant lacking one."""
        for c in self.encounter.combatants:
            if c.initiative is not None:
                continue
            sb = statblocks.get(c.statblock_id)
            if sb is None:
                c.initiative = 10
                continue
            c.initiative = roller.initiative(sb.abilities, c.display_name).total
        self.sort()

    def sort(self) -> None:
        self.encounter.combatants.sort(
            key=lambda c: (c.initiative or 0), reverse=True
        )

    def remove(self, combatant_id: str) -> bool:
        """Remove a combatant, keeping the active-turn marker valid."""
        combatants = self.encounter.combatants
        idx = next(
            (i for i, c in enumerate(combatants) if c.id == combatant_id), None
        )
        if idx is None:
            return False
        combatants.pop(idx)
        if not combatants:
            self.encounter.active_index = 0
        else:
            if idx < self.encounter.active_index:
                self.encounter.active_index -= 1
            if self.encounter.active_index >= len(combatants):
                self.encounter.active_index = 0
        return True

    def current(self) -> Optional[Combatant]:
        if not self.encounter.combatants:
            return None
        return self.encounter.combatants[self.encounter.active_index]

    def next_turn(self) -> Optional[Combatant]:
        n = len(self.encounter.combatants)
        if n == 0:
            return None
        self.encounter.active_index += 1
        if self.encounter.active_index >= n:
            self.encounter.active_index = 0
            self.encounter.round += 1
            self._on_round_start()
        return self.current()

    def _on_round_start(self) -> None:
        # tick conditions and refresh legendary actions
        for c in self.encounter.combatants:
            for cond in list(c.conditions):
                if cond.rounds_remaining is not None:
                    cond.rounds_remaining -= 1
                    if cond.rounds_remaining <= 0:
                        c.conditions.remove(cond)

    # --- hp & conditions -------------------------------------------------- #
    def apply_damage(self, combatant: Combatant, amount: int) -> int:
        absorbed = min(combatant.temp_hp, amount)
        combatant.temp_hp -= absorbed
        remaining = amount - absorbed
        combatant.current_hp = max(0, combatant.current_hp - remaining)
        return combatant.current_hp

    def heal(self, combatant: Combatant, amount: int) -> int:
        combatant.current_hp = min(combatant.max_hp, combatant.current_hp + amount)
        return combatant.current_hp

    def add_condition(
        self, combatant: Combatant, name: str, rounds: Optional[int] = None
    ) -> None:
        combatant.conditions.append(
            ConditionState(name=name, rounds_remaining=rounds)
        )

    def remove_condition(self, combatant: Combatant, name: str) -> None:
        combatant.conditions = [
            c for c in combatant.conditions if c.name.lower() != name.lower()
        ]
