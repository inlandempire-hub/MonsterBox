"""Dice expression evaluation.

Small and dependency-free. Supports ``NdM``, flat modifiers and advantage /
disadvantage on a single d20. Returns the individual die faces so callers can
build a structured :class:`~statforge.models.RollEvent` (we never throw away the
breakdown — the roll log shows each die).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

_TERM = re.compile(r"([+-]?)\s*(\d*)d(\d+)|([+-]?\s*\d+)", re.IGNORECASE)


@dataclass
class RollResult:
    expression: str
    dice_results: list[int] = field(default_factory=list)
    modifier: int = 0
    total: int = 0


def roll(expression: str, rng: random.Random | None = None) -> RollResult:
    """Evaluate an expression like ``"2d6+3"`` or ``"1d20 - 1"``."""
    rng = rng or random
    res = RollResult(expression=expression.replace(" ", ""))
    total = 0
    for sign, count, sides, flat in _TERM.findall(expression):
        if sides:  # a dice term
            n = int(count) if count else 1
            mult = -1 if sign == "-" else 1
            for _ in range(n):
                face = rng.randint(1, int(sides))
                res.dice_results.append(face)
                total += mult * face
        elif flat:  # a flat modifier
            value = int(flat.replace(" ", ""))
            res.modifier += value
            total += value
    res.total = total
    return res


def roll_d20(
    modifier: int = 0,
    advantage: str | None = None,
    rng: random.Random | None = None,
) -> RollResult:
    """Roll a d20 with an optional modifier and advantage/disadvantage."""
    rng = rng or random
    faces = [rng.randint(1, 20)]
    if advantage in ("advantage", "disadvantage"):
        faces.append(rng.randint(1, 20))
        chosen = max(faces) if advantage == "advantage" else min(faces)
    else:
        chosen = faces[0]
    return RollResult(
        expression=f"1d20{modifier:+d}" if modifier else "1d20",
        dice_results=faces,
        modifier=modifier,
        total=chosen + modifier,
    )
