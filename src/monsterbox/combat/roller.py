"""Turn structured :class:`Action` data into :class:`RollEvent` objects.

This is the "every number is a button" engine. A parsed action carries a
``to_hit`` and a list of damage components; the roller resolves those into dice
and emits a structured event. The same event renders to the local log today and
could be pushed to a VTT later (see RollEvent docs).
"""

from __future__ import annotations

import random
from typing import Optional

from ..models import (
    Ability,
    AbilityScores,
    Action,
    RollEvent,
    RollType,
    ability_modifier,
)
from . import dice


class Roller:
    def __init__(
        self,
        owner_id: str = "local-user",
        rng: Optional[random.Random] = None,
    ):
        self.owner_id = owner_id
        self.rng = rng or random.Random()

    # --- attacks ---------------------------------------------------------- #
    def attack_roll(
        self,
        action: Action,
        source: str,
        advantage: Optional[str] = None,
        private: bool = True,
    ) -> RollEvent:
        to_hit = action.attack.to_hit if action.attack else 0
        r = dice.roll_d20(modifier=to_hit or 0, advantage=advantage, rng=self.rng)
        return RollEvent(
            owner_id=self.owner_id,
            source=source,
            roll_type=RollType.ATTACK,
            label=f"{action.name} to hit",
            expression=r.expression,
            dice_results=r.dice_results,
            modifier=r.modifier,
            total=r.total,
            advantage=advantage,
            private=private,
        )

    def damage_roll(
        self,
        action: Action,
        source: str,
        crit: bool = False,
        private: bool = True,
    ) -> RollEvent:
        all_faces: list[int] = []
        total = 0
        parts: list[str] = []
        for comp in action.damage:
            if comp.dice:
                expr = comp.dice if not crit else _double_dice(comp.dice)
                r = dice.roll(expr, rng=self.rng)
                all_faces.extend(r.dice_results)
                total += r.total + comp.bonus
                parts.append(f"{comp.dice}{comp.bonus:+d}" if comp.bonus else comp.dice)
            else:
                total += comp.bonus
                parts.append(str(comp.bonus))
        return RollEvent(
            owner_id=self.owner_id,
            source=source,
            roll_type=RollType.DAMAGE,
            label=f"{action.name} damage" + (" (crit)" if crit else ""),
            expression=" + ".join(parts),
            dice_results=all_faces,
            total=total,
            private=private,
        )

    # --- generic d20 (saves / checks / skills with a known bonus) -------- #
    def d20(
        self,
        modifier: int,
        source: str,
        label: str,
        roll_type: RollType = RollType.CHECK,
        advantage: Optional[str] = None,
        private: bool = True,
    ) -> RollEvent:
        r = dice.roll_d20(modifier=modifier, advantage=advantage, rng=self.rng)
        return RollEvent(
            owner_id=self.owner_id,
            source=source,
            roll_type=roll_type,
            label=label,
            expression=r.expression,
            dice_results=r.dice_results,
            modifier=r.modifier,
            total=r.total,
            advantage=advantage,
            private=private,
        )

    # --- saves / checks / initiative ------------------------------------- #
    def ability_check(
        self,
        scores: AbilityScores,
        ability: Ability,
        source: str,
        proficiency: int = 0,
        advantage: Optional[str] = None,
        roll_type: RollType = RollType.CHECK,
        label: str = "",
        private: bool = True,
    ) -> RollEvent:
        mod = scores.modifier(ability) + proficiency
        r = dice.roll_d20(modifier=mod, advantage=advantage, rng=self.rng)
        return RollEvent(
            owner_id=self.owner_id,
            source=source,
            roll_type=roll_type,
            label=label or f"{ability.value.upper()} {roll_type.value}",
            expression=r.expression,
            dice_results=r.dice_results,
            modifier=r.modifier,
            total=r.total,
            advantage=advantage,
            private=private,
        )

    def initiative(
        self, scores: AbilityScores, source: str, private: bool = True
    ) -> RollEvent:
        return self.ability_check(
            scores,
            Ability.DEX,
            source,
            roll_type=RollType.INITIATIVE,
            label="Initiative",
            private=private,
        )


def _double_dice(expr: str) -> str:
    """'2d6' -> '4d6' for a critical hit."""
    m = __import__("re").match(r"(\d+)d(\d+)", expr)
    if not m:
        return expr
    return f"{int(m.group(1)) * 2}d{m.group(2)}"
