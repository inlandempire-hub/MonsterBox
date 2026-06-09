"""Core data model for MonsterBox.

Design principles baked in here:

* **Template vs. instance.** A :class:`StatBlock` is an immutable-ish *template*
  parsed from a source (a monster as printed in a book). A :class:`Combatant`
  is a live *instance* of that template inside an encounter, with its own HP,
  conditions and resource counters. Three goblins in a fight share one
  StatBlock but get three Combatants.

* **Owner-scoped from day one.** Every persistable entity carries an
  ``owner_id``. Today that can be ``"local-user"``; when the app grows into a
  multi-tenant product, this is already the tenant key. Retrofitting this later
  is the painful migration we are avoiding.

* **Readability is king / fidelity over cleverness.** Parsing scanned 3rd-party
  books is lossy. Every parsed element also keeps the ``raw_text`` it came from
  so the UI can always render the source-of-truth line even when structured
  fields are imperfect.
"""

from __future__ import annotations

import datetime as _dt
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def ability_modifier(score: int) -> int:
    """5e ability modifier: floor((score - 10) / 2)."""
    return (score - 10) // 2


# --------------------------------------------------------------------------- #
# enums (kept permissive — 3rd-party books invent their own terms)
# --------------------------------------------------------------------------- #
class Size(str, Enum):
    TINY = "Tiny"
    SMALL = "Small"
    MEDIUM = "Medium"
    LARGE = "Large"
    HUGE = "Huge"
    GARGANTUAN = "Gargantuan"


class Ability(str, Enum):
    STR = "str"
    DEX = "dex"
    CON = "con"
    INT = "int"
    WIS = "wis"
    CHA = "cha"


class ActionCategory(str, Enum):
    TRAIT = "trait"               # the italicised special abilities block
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    LEGENDARY = "legendary"


class AttackKind(str, Enum):
    MELEE_WEAPON = "melee_weapon"
    RANGED_WEAPON = "ranged_weapon"
    MELEE_SPELL = "melee_spell"
    RANGED_SPELL = "ranged_spell"


# --------------------------------------------------------------------------- #
# ability scores
# --------------------------------------------------------------------------- #
class AbilityScores(BaseModel):
    strength: int = 10
    dexterity: int = 10
    constitution: int = 10
    intelligence: int = 10
    wisdom: int = 10
    charisma: int = 10

    _MAP = {
        Ability.STR: "strength",
        Ability.DEX: "dexterity",
        Ability.CON: "constitution",
        Ability.INT: "intelligence",
        Ability.WIS: "wisdom",
        Ability.CHA: "charisma",
    }

    def score(self, ability: Ability) -> int:
        return getattr(self, self._MAP[ability])

    def modifier(self, ability: Ability) -> int:
        return ability_modifier(self.score(ability))


# --------------------------------------------------------------------------- #
# action sub-structures
# --------------------------------------------------------------------------- #
class DamageComponent(BaseModel):
    """One chunk of damage, e.g. ``7 (1d8 + 3) piercing``."""

    dice: Optional[str] = None          # "1d8"   (None for flat damage)
    bonus: int = 0                       # +3
    average: Optional[int] = None        # 7  (as printed; authoritative if set)
    damage_type: Optional[str] = None    # "piercing"
    notes: Optional[str] = None          # "when wielded with two hands"


class AttackDetail(BaseModel):
    kind: AttackKind
    to_hit: Optional[int] = None         # +7
    reach_ft: Optional[int] = None       # melee reach
    range_ft: Optional[str] = None       # "80/320" for ranged
    targets: str = "one target"


class SaveEffect(BaseModel):
    ability: Ability
    dc: int
    on_success: Optional[str] = None     # "half damage", "no effect"


class Action(BaseModel):
    """A trait, action, bonus action, reaction or legendary action.

    ``raw_text`` is always preserved so the sheet can fall back to the exact
    printed wording when the structured fields are incomplete.
    """

    name: str
    category: ActionCategory = ActionCategory.ACTION
    raw_text: str = ""

    attack: Optional[AttackDetail] = None
    damage: list[DamageComponent] = Field(default_factory=list)
    save: Optional[SaveEffect] = None

    recharge: Optional[str] = None       # "Recharge 5-6"
    usage: Optional[str] = None          # "3/Day", "1/Day"
    legendary_cost: int = 1              # "Costs 2 Actions" -> 2


class Spellcasting(BaseModel):
    """Loose container — spell linking is a later milestone."""

    raw_text: str = ""
    ability: Optional[Ability] = None
    save_dc: Optional[int] = None
    at_will: list[str] = Field(default_factory=list)
    per_day: dict[str, list[str]] = Field(default_factory=dict)  # "1/day" -> [..]


# --------------------------------------------------------------------------- #
# the StatBlock template
# --------------------------------------------------------------------------- #
class StatBlock(BaseModel):
    id: str = Field(default_factory=_uuid)
    owner_id: str = "local-user"
    created_at: str = Field(default_factory=_now)

    # identity
    name: str
    size: Optional[Size] = None
    creature_type: Optional[str] = None     # "Monstrosity", "Fiend", ...
    alignment: Optional[str] = None

    # defenses
    armor_class: int = 10
    armor_desc: Optional[str] = None         # "(natural armor)"
    hit_points: int = 1
    hit_dice: Optional[str] = None           # "23d8 + 92"
    speed: dict[str, int] = Field(default_factory=dict)  # {"walk":30,"fly":30}

    # stats
    abilities: AbilityScores = Field(default_factory=AbilityScores)
    saving_throws: dict[str, int] = Field(default_factory=dict)  # {"int":5,...}
    skills: dict[str, int] = Field(default_factory=dict)

    damage_vulnerabilities: list[str] = Field(default_factory=list)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)

    senses: dict[str, int] = Field(default_factory=dict)  # {"darkvision":60,...}
    passive_perception: Optional[int] = None
    languages: list[str] = Field(default_factory=list)

    challenge_rating: Optional[str] = None   # "20"
    xp: Optional[int] = None                 # 25000
    proficiency_bonus: Optional[int] = None  # +8

    # behaviour
    traits: list[Action] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    bonus_actions: list[Action] = Field(default_factory=list)
    reactions: list[Action] = Field(default_factory=list)
    legendary_actions: list[Action] = Field(default_factory=list)
    legendary_action_count: int = 0          # actions available per round
    spellcasting: Optional[Spellcasting] = None

    # provenance / parse quality (so the UI can flag low-confidence imports)
    source: Optional[str] = None             # original file name / book
    source_page: Optional[int] = None
    raw_text: Optional[str] = None           # full OCR/vision dump
    parse_confidence: float = 0.0            # 0..1
    parse_warnings: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# live combat instance
# --------------------------------------------------------------------------- #
class ConditionState(BaseModel):
    name: str                                # "poisoned"
    rounds_remaining: Optional[int] = None   # None = indefinite
    note: Optional[str] = None


class Combatant(BaseModel):
    """A live instance of a StatBlock inside an encounter."""

    id: str = Field(default_factory=_uuid)
    owner_id: str = "local-user"
    statblock_id: str
    display_name: str                        # "Goblin #2"

    initiative: Optional[int] = None
    max_hp: int = 1
    current_hp: int = 1
    temp_hp: int = 0
    armor_class: int = 10

    conditions: list[ConditionState] = Field(default_factory=list)
    # resource counters keyed by Action.name -> remaining uses / recharge state
    resources: dict[str, int] = Field(default_factory=dict)
    legendary_actions_remaining: int = 0
    concentrating_on: Optional[str] = None
    is_player: bool = False
    notes: str = ""


class Encounter(BaseModel):
    id: str = Field(default_factory=_uuid)
    owner_id: str = "local-user"
    created_at: str = Field(default_factory=_now)
    name: str = "Untitled Encounter"
    round: int = 0
    active_index: int = 0
    combatants: list[Combatant] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# roll log — structured events, never pre-rendered strings
# --------------------------------------------------------------------------- #
class RollType(str, Enum):
    ATTACK = "attack"
    DAMAGE = "damage"
    SAVE = "save"
    CHECK = "check"
    INITIATIVE = "initiative"
    CUSTOM = "custom"


class RollEvent(BaseModel):
    """A single dice resolution.

    Stored structured so the same event can be rendered to the local log,
    exported to a VTT, or filtered by ``private`` for DM-only visibility —
    three renderers over one event rather than three code paths.
    """

    id: str = Field(default_factory=_uuid)
    owner_id: str = "local-user"
    timestamp: str = Field(default_factory=_now)

    source: str                              # "Black Bird #1"
    roll_type: RollType
    label: str = ""                          # "Eclipse Spear to hit"
    expression: str = ""                     # "1d20+7"
    dice_results: list[int] = Field(default_factory=list)
    modifier: int = 0
    total: int = 0

    target: Optional[str] = None
    advantage: Optional[str] = None          # "advantage" | "disadvantage"
    private: bool = True                     # DM-only by default
