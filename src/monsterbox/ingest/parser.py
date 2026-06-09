"""Stage 3: turn a page (image or text) into a structured :class:`StatBlock`.

This module defines the **relocatable boundary** that the whole product is
built around::

    parse(page, owner_id, source) -> list[StatBlock]

Whatever implements :class:`StatBlockParser` can run locally on the DM's
machine today or behind a hosted, per-tenant endpoint tomorrow — the rest of
the app never needs to know which. A single page may hold more than one stat
block (a book page often prints two), so the boundary returns a *list*.

Two implementations ship:

* :class:`VisionLLMParser` — the **primary** path. Sends the page *image* to a
  vision model (Claude Opus) and asks for the StatBlock schema directly via
  structured outputs. This is the right tool for scanned books (see
  ``render.py``). Active whenever an API key is configured.

* :class:`OcrHeuristicParser` — the **fallback**. Regex-parses OCR text into the
  fields we reliably see in 5e stat blocks. Lower fidelity, zero external
  services, good for offline use and tests.
"""

from __future__ import annotations

import base64
import collections
import os
import re
from typing import Optional, Protocol

from pydantic import BaseModel, Field

from ..models import (
    Ability,
    AbilityScores,
    Action,
    ActionCategory,
    AttackDetail,
    AttackKind,
    DamageComponent,
    SaveEffect,
    Size,
    Spellcasting,
    StatBlock,
)
from .extract import ExtractionResult, ocr_page
from .render import PageImage


# --------------------------------------------------------------------------- #
# the boundary contract
# --------------------------------------------------------------------------- #
class StatBlockParser(Protocol):
    name: str

    def parse(
        self,
        page: PageImage,
        owner_id: str = "local-user",
        source: Optional[str] = None,
    ) -> list[StatBlock]:
        ...


# --------------------------------------------------------------------------- #
# primary path: vision LLM
# --------------------------------------------------------------------------- #
VISION_SYSTEM_PROMPT = """\
You are a Dungeons & Dragons 5e stat-block extractor. You are given a scan or
photo of a single book page that contains one or more monster stat blocks
(often two; sometimes a partial block bleeds in from a neighbouring column —
ignore fragments that are not substantially complete).

Return EVERY complete stat block on the page in `statblocks`. For each:
- Transcribe every trait / action / legendary action verbatim into its
  `raw_text`, and ALSO fill the structured fields (attack to_hit, reach_ft,
  damage components, save ability + DC, recharge, legendary cost) when present.
- Preserve printed average damage exactly (the "7" in "7 (1d8 + 3)").
- `speed`, `saving_throws`, `skills`, and `senses` are lists of {name, value}.
  Use ft for speed/senses (e.g. {"name":"fly","value":60}); for saves/skills
  use the numeric bonus (e.g. {"name":"Wisdom","value":7}).
- `abilities` are the six raw scores (e.g. strength 16), not the modifiers.
- Put spell lists under `spell_groups` ({frequency, spells}), e.g.
  {"frequency":"At Will","spells":["darkness"]}.
- Omit a field if it is absent on the page; do not invent values.
- Set `parse_confidence` to your honest 0..1 transcription-accuracy estimate.
"""


# --- structured-output target ------------------------------------------------ #
# The Messages API structured-output schema cannot express free-form maps
# (`additionalProperties` must be false), so dict-like stat-block fields are
# modelled as {name, value} lists here and folded back into dicts afterwards.
# Behaviour reuses the dict-free Action model directly.
class _NamedInt(BaseModel):
    name: str
    value: int


class _ParsedSpellGroup(BaseModel):
    frequency: str  # "At Will", "1/Day Each", "3/Day Each"
    spells: list[str] = Field(default_factory=list)


class _ParsedStatBlock(BaseModel):
    name: str
    size: Optional[Size] = None
    creature_type: Optional[str] = None
    alignment: Optional[str] = None
    armor_class: int = 10
    armor_desc: Optional[str] = None
    hit_points: int = 1
    hit_dice: Optional[str] = None
    speed: list[_NamedInt] = Field(default_factory=list)
    abilities: AbilityScores = Field(default_factory=AbilityScores)
    saving_throws: list[_NamedInt] = Field(default_factory=list)
    skills: list[_NamedInt] = Field(default_factory=list)
    damage_vulnerabilities: list[str] = Field(default_factory=list)
    damage_resistances: list[str] = Field(default_factory=list)
    damage_immunities: list[str] = Field(default_factory=list)
    condition_immunities: list[str] = Field(default_factory=list)
    senses: list[_NamedInt] = Field(default_factory=list)
    passive_perception: Optional[int] = None
    languages: list[str] = Field(default_factory=list)
    challenge_rating: Optional[str] = None
    xp: Optional[int] = None
    proficiency_bonus: Optional[int] = None
    traits: list[Action] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    bonus_actions: list[Action] = Field(default_factory=list)
    reactions: list[Action] = Field(default_factory=list)
    legendary_actions: list[Action] = Field(default_factory=list)
    legendary_action_count: int = 0
    spell_groups: list[_ParsedSpellGroup] = Field(default_factory=list)
    parse_confidence: float = 0.0


class _ParsedPage(BaseModel):
    statblocks: list[_ParsedStatBlock] = Field(default_factory=list)


def _encode_image(data: bytes) -> tuple[str, str]:
    """Return (media_type, base64) for an embedded page image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        mt = "image/png"
    elif data[:3] == b"\xff\xd8\xff":
        mt = "image/jpeg"
    elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mt = "image/webp"
    elif data[:6] in (b"GIF87a", b"GIF89a"):
        mt = "image/gif"
    else:
        mt = "image/png"  # best guess; most scans embed PNG
    return mt, base64.standard_b64encode(data).decode("ascii")


def _spellcasting_from(groups: list[_ParsedSpellGroup]) -> Optional[Spellcasting]:
    if not groups:
        return None
    sc = Spellcasting()
    for g in groups:
        if "at will" in g.frequency.lower():
            sc.at_will.extend(g.spells)
        else:
            sc.per_day[g.frequency] = list(g.spells)
    return sc


def _to_statblock(
    ps: _ParsedStatBlock,
    owner_id: str,
    source: Optional[str],
    page_number: int,
) -> StatBlock:
    return StatBlock(
        owner_id=owner_id,
        source=source,
        source_page=page_number,
        name=ps.name,
        size=ps.size,
        creature_type=ps.creature_type,
        alignment=ps.alignment,
        armor_class=ps.armor_class,
        armor_desc=ps.armor_desc,
        hit_points=ps.hit_points,
        hit_dice=ps.hit_dice,
        speed={x.name: x.value for x in ps.speed},
        abilities=ps.abilities,
        saving_throws={x.name: x.value for x in ps.saving_throws},
        skills={x.name: x.value for x in ps.skills},
        damage_vulnerabilities=ps.damage_vulnerabilities,
        damage_resistances=ps.damage_resistances,
        damage_immunities=ps.damage_immunities,
        condition_immunities=ps.condition_immunities,
        senses={x.name: x.value for x in ps.senses},
        passive_perception=ps.passive_perception,
        languages=ps.languages,
        challenge_rating=ps.challenge_rating,
        xp=ps.xp,
        proficiency_bonus=ps.proficiency_bonus,
        traits=ps.traits,
        actions=ps.actions,
        bonus_actions=ps.bonus_actions,
        reactions=ps.reactions,
        legendary_actions=ps.legendary_actions,
        legendary_action_count=ps.legendary_action_count,
        spellcasting=_spellcasting_from(ps.spell_groups),
        parse_confidence=ps.parse_confidence or 0.9,
    )


class VisionLLMParser:
    """Image -> structured StatBlocks via a Claude vision model.

    Active whenever an Anthropic client is supplied. Use :meth:`from_env` to
    construct one only if credentials are present (so a fresh install with no
    key cleanly falls back to OCR rather than erroring).
    """

    name = "vision-llm"

    def __init__(self, client=None, model: str = "claude-opus-4-8"):
        self.client = client
        self.model = model

    @classmethod
    def from_env(cls, model: str = "claude-opus-4-8") -> Optional["VisionLLMParser"]:
        """Build a parser if `anthropic` is installed and a key is set, else None."""
        try:
            import anthropic  # noqa: F401
        except ImportError:
            return None
        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            return None
        import anthropic

        return cls(client=anthropic.Anthropic(), model=model)

    def parse(
        self,
        page: PageImage,
        owner_id: str = "local-user",
        source: Optional[str] = None,
    ) -> list[StatBlock]:
        if self.client is None:
            raise NotImplementedError(
                "VisionLLMParser has no Anthropic client. Construct it via "
                "VisionLLMParser.from_env() with ANTHROPIC_API_KEY set, or fall "
                "back to OcrHeuristicParser for offline operation."
            )
        media_type, b64 = _encode_image(page.data)
        # messages.parse() validates the response against _ParsedPage and returns
        # a typed object — no brittle hand-parsing of model text. Adaptive
        # thinking suits dense two-column transcription. The static system prompt
        # carries a cache breakpoint (cheap no-op below the cache minimum today,
        # correct once the prompt grows / batches share it).
        resp = self.client.messages.parse(
            model=self.model,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=[
                {
                    "type": "text",
                    "text": VISION_SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Extract every complete stat block on this "
                            "page into the schema.",
                        },
                    ],
                }
            ],
            output_format=_ParsedPage,
        )
        parsed = resp.parsed_output
        if parsed is None:
            raise ValueError(
                f"Vision model returned no structured output for page "
                f"{page.index + 1} (stop_reason={resp.stop_reason!r})."
            )
        return [
            _to_statblock(ps, owner_id, source, page.index + 1)
            for ps in parsed.statblocks
        ]


# --------------------------------------------------------------------------- #
# fallback path: OCR text -> regex parse
# --------------------------------------------------------------------------- #
_SIZE_WORDS = {s.value.lower(): s for s in Size}

# The "<Size> <type>, <alignment>" line that opens every stat block. Anchoring
# on the fixed set of 5e creature types keeps this from firing on ordinary lore
# sentences that happen to start with a size word ("Large numbers of cultists,").
_CREATURE_TYPES = (
    "aberration|beast|celestial|construct|dragon|elemental|fey|fiend|giant|"
    "humanoid|monstrosity|ooze|plant|undead"
)
_RE_META = re.compile(
    rf"^(Tiny|Small|Medium|Large|Huge|Gargantuan)\s+"
    rf"((?:swarm of \w+ )?(?:{_CREATURE_TYPES})s?(?:\s*\([^)]*\))?)\s*,\s*(.+)$",
    re.IGNORECASE,
)
_RE_AC = re.compile(r"Armor Class\s+(\d+)\s*(\([^)]*\))?", re.IGNORECASE)
_RE_HP = re.compile(r"Hit Points\s+(\d+)\s*(?:\(([^)]*)\))?", re.IGNORECASE)
_RE_SPEED = re.compile(r"Speed\s+(.+)", re.IGNORECASE)
# Ability score + modifier, e.g. "16 (+3)" / "9 (-1)". Tolerant of any sign
# glyph inside the parens (ASCII -, Unicode minus −, or a mis-decoded char) so
# negative modifiers don't break the six-pair detection.
_RE_ABILITY_PAIR = re.compile(r"(\d+)\s*\(\s*[^)\d]*?(\d+)\s*\)")
_RE_CHALLENGE = re.compile(
    r"Challenges?\s+([0-9/]+)\s*(?:\(([\d,]+)\s*XP\)?)?", re.IGNORECASE
    # Challenges? tolerates the occasional book typo "Challenges" instead of "Challenge"
)
_RE_PROF = re.compile(r"Proficiency Bonus\s+\+?(\d+)", re.IGNORECASE)
_RE_SPEED_PART = re.compile(r"(?:(\w+)\s+)?(\d+)\s*ft", re.IGNORECASE)

# Stat-header fields (each its own line in column-ordered text).
_RE_AC_LINE = re.compile(r"^\s*Armor Class\b", re.IGNORECASE)
_RE_SAVES = re.compile(r"Saving Throws\s+(.+)", re.IGNORECASE)
_RE_SKILLS = re.compile(r"Skills\s+(.+)", re.IGNORECASE)
_RE_SENSES = re.compile(r"Senses\s+(.+)", re.IGNORECASE)
_RE_LANGS = re.compile(r"Languages\s+(.+)", re.IGNORECASE)
_RE_PASSIVE = re.compile(r"passive Perception\s+(\d+)", re.IGNORECASE)
_RE_DMG = re.compile(
    r"Damage (Vulnerabilities|Resistances|Immunities)\s+(.+)", re.IGNORECASE
)
_RE_COND = re.compile(r"Condition Immunities\s+(.+)", re.IGNORECASE)
_RE_BONUS_PAIR = re.compile(r"(.+?)\s*([+-]\d+)")
# Looser meta line so a misspelled size ("Garganutan") still yields type/alignment.
_RE_META_LOOSE = re.compile(
    rf"^\w+\s+((?:{_CREATURE_TYPES})s?(?:\s*\([^)]*\))?)\s*,\s*(.+)$",
    re.IGNORECASE,
)

# action lines: "Eclipse Spear. Melee Weapon Attack: +7 to hit, reach 10 ft.,..."
_RE_ATTACK = re.compile(
    r"(Melee|Ranged)\s+(Weapon|Spell)\s+Attack:\s*\+?(\d+)\s*to hit"
    r"(?:,\s*(?:reach\s+(\d+)\s*ft|range\s+([\d/]+)\s*ft))?",
    re.IGNORECASE,
)
_RE_DAMAGE = re.compile(
    r"(\d+)\s*\(\s*(\d+d\d+)\s*([+-]\s*\d+)?\s*\)\s*([a-zA-Z]+)?\s*damage",
    re.IGNORECASE,
)


def _parse_speed(text: str) -> dict[str, int]:
    speed: dict[str, int] = {}
    for mode, dist in _RE_SPEED_PART.findall(text):
        key = (mode or "walk").lower()
        speed[key] = int(dist)
    return speed


def _parse_abilities(text: str) -> tuple[AbilityScores, bool]:
    pairs = _RE_ABILITY_PAIR.findall(text)
    if len(pairs) < 6:
        return AbilityScores(), False
    scores = [int(p[0]) for p in pairs[:6]]
    return (
        AbilityScores(
            strength=scores[0],
            dexterity=scores[1],
            constitution=scores[2],
            intelligence=scores[3],
            wisdom=scores[4],
            charisma=scores[5],
        ),
        True,
    )


def _parse_damage(text: str) -> list[DamageComponent]:
    comps: list[DamageComponent] = []
    for avg, dice, bonus, dtype in _RE_DAMAGE.findall(text):
        comps.append(
            DamageComponent(
                dice=dice,
                bonus=int(re.sub(r"\s+", "", bonus)) if bonus else 0,
                average=int(avg),
                damage_type=dtype.lower() or None,
            )
        )
    return comps


def _parse_bonuses(text: str) -> dict[str, int]:
    """'Con +10, Wis +6' / 'Sleight of Hand +5, Perception +10' -> {name: bonus}."""
    out: dict[str, int] = {}
    for part in text.split(","):
        if m := _RE_BONUS_PAIR.search(part):
            name = m.group(1).strip()
            if name:
                out[name] = int(m.group(2))
    return out


def _parse_senses(text: str) -> tuple[dict[str, int], Optional[int]]:
    senses: dict[str, int] = {}
    for mode, dist in _RE_SPEED_PART.findall(text):
        if mode:  # "darkvision 60 ft." -> {"darkvision": 60}
            senses[mode.lower()] = int(dist)
    passive = None
    if m := _RE_PASSIVE.search(text):
        passive = int(m.group(1))
    return senses, passive


def _parse_list(text: str) -> list[str]:
    """Split a 'fire, cold; nonmagical' style field into a clean list."""
    text = text.strip()
    if text.lower() in ("none", "-", "—", "–", ""):
        return []
    parts = re.split(r"[,;]", text)
    return [p.strip() for p in parts if p.strip()]


# Book section/category headers that sit above a stat block but are NOT part of
# the monster's name (e.g. "Humanoids" over "Bullywug Potentate").
_SECTION_HEADER_WORDS = {
    "aberrations", "beasts", "celestials", "constructs", "dragons",
    "elementals", "fey", "fiends", "giants", "humanoids", "monstrosities",
    "oozes", "plants", "undead",
}


def _looks_like_title(line: str) -> bool:
    """A short, capitalised, non-sentence line — i.e. a monster-name line."""
    s = line.strip()
    if not s or len(s) > 50 or len(s.split()) > 6:
        return False
    if s[-1] in ".,:;":
        return False
    if not s[0].isupper():
        return False
    if s.lower() in _SECTION_HEADER_WORDS:
        return False
    return not _RE_AC_LINE.match(s)


def _strip_footer(body: str) -> str:
    """Drop a trailing page-number / footer left over at the column bottom."""
    return re.sub(r"[ \t\r\n]+\d{1,4}\s*$", "", body).rstrip()


_STAT_FIELD_PREFIXES = (
    "armor class", "hit points", "speed", "saving throws", "skills", "senses",
    "languages", "challenge", "damage ", "condition ", "proficiency",
)
# structural / front-matter words that are never a creature name
_NON_NAME_WORDS = {"alignment", "actions", "reactions", "traits", "description"}


def _name_like(line: str) -> bool:
    """Could this line be a creature-name header? Short, capitalised, and not a
    stat field, meta line, or section header. Accepts ALL-CAPS headers (official
    books) and Title-Case names (e.g. A5e), including lightly-garbled ones."""
    s = line.strip()
    if not s or len(s) > 45:
        return False
    words = s.split()
    if len(words) > 6 or s[-1] in ".,:;":
        return False
    low = s.lower()
    if low in _SECTION_HEADER_WORDS or low in _NON_NAME_WORDS or _RE_AC_LINE.match(s):
        return False
    if _SECTION_RE.match(s):                 # ACTIONS / REACTIONS / LEGENDARY ACTIONS …
        return False
    if _RE_META.match(s) or _RE_META_LOOSE.match(s):
        return False
    if any(low.startswith(k) for k in _STAT_FIELD_PREFIXES):
        return False
    toks = s.upper().split()                  # the ability-score header row
    if sum(1 for t in toks if t in {"STR", "DEX", "CON", "INT", "WIS", "CHA"}) >= 3:
        return False
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 2:
        return False
    if sum(c.isupper() for c in letters) / len(letters) >= 0.6:
        return True  # ALL-CAPS / small-caps header
    sig = [w for w in words if w.lower() not in _NAME_CONNECTORS]
    return bool(sig) and all(w[0].isupper() for w in sig if w[:1].isalpha())


def _find_name(lines: list[str], meta_i: int, lower: int = 0) -> str:
    """Find a stat block's name given its meta-line index.

    Two layouts: the name may sit *in the box* directly above the meta line
    (A5e / homebrew), or be a page header *above the flavor text* (official
    WotC). Try the in-box title first; otherwise search upward (past the flavor)
    for the nearest name-like header.
    """
    titles: list[str] = []
    j = meta_i - 1
    while (
        j >= lower and lines[j].strip()
        and _looks_like_title(lines[j]) and len(titles) < 3
    ):
        titles.insert(0, lines[j].strip())
        j -= 1
    if titles:
        return " ".join(titles)

    j, steps = meta_i - 1, 0
    while j >= lower and steps < 30:
        s = lines[j].strip()
        if s and _name_like(s):
            return s
        j -= 1
        steps += 1
    return ""


_ABILITY_BY_NAME = {
    "strength": Ability.STR,
    "dexterity": Ability.DEX,
    "constitution": Ability.CON,
    "intelligence": Ability.INT,
    "wisdom": Ability.WIS,
    "charisma": Ability.CHA,
}

_RE_SAVE = re.compile(
    r"DC\s*(\d+)\s*"
    r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)"
    r"\s*saving throw",
    re.IGNORECASE,
)

# Section headers, each on its own line. Longer names first so "BONUS ACTIONS"
# isn't shadowed by "ACTIONS".
_SECTION_RE = re.compile(
    r"(?im)^[ \t]*(LEGENDARY ACTIONS|BONUS ACTIONS|REACTIONS|ACTIONS)[ \t]*$"
)
_HEADER_TO_CAT = {
    "ACTIONS": ActionCategory.ACTION,
    "BONUS ACTIONS": ActionCategory.BONUS_ACTION,
    "REACTIONS": ActionCategory.REACTION,
    "LEGENDARY ACTIONS": ActionCategory.LEGENDARY,
}
_RE_LEG_COUNT = re.compile(r"(\d+)\s+legendary action", re.IGNORECASE)

# An entry begins at the start of a line with a Title-case name (≤ 6 words,
# optionally a "(...)" qualifier) followed by ". " and then a capital/"(".
# The name's word characters deliberately EXCLUDE "." so the "Name." boundary
# is unambiguous (otherwise a short line like "Slam. Reach..." gets swallowed).
_RE_ENTRY = re.compile(
    r"(?m)^[ \t>•*\-]*"
    r"([A-Z][A-Za-z0-9:’’/\-]+(?:\s+[A-Za-z0-9:’’/\-]+){0,5}?"
    r"(?:\s*\([^)]*\))?)[ \t]*\.[ \t]+(?=[A-Z(])"
    # [ \t]* before \. tolerates a space inserted between the entry name and
    # its period — a pdfplumber artefact on some ToB3 pages ("Bite . Melee…").
)


def _build_action(name: str, body: str, category: ActionCategory) -> Action:
    """Turn one '<Name>. <description>' entry into a structured Action."""
    clean_name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    action = Action(
        name=clean_name or name.strip(),
        category=category,
        raw_text=body.strip(),
    )

    # qualifiers carried in the name's parenthetical: (Recharge 5-6), (3/Day),
    # (Costs 2 Actions)
    if paren := re.search(r"\(([^)]*)\)", name):
        p = paren.group(1)
        if m := re.search(r"recharge\s+([0-9–\-]+)", p, re.IGNORECASE):
            action.recharge = f"Recharge {m.group(1)}"
        elif re.search(r"\d+\s*/\s*day", p, re.IGNORECASE):
            action.usage = p.strip()
        elif m := re.search(r"costs?\s+(\d+)\s+actions?", p, re.IGNORECASE):
            action.legendary_cost = int(m.group(1))

    if m := _RE_ATTACK.search(body):
        melee_ranged, weapon_spell, to_hit, reach, rng = m.groups()
        action.attack = AttackDetail(
            kind=AttackKind(f"{melee_ranged.lower()}_{weapon_spell.lower()}"),
            to_hit=int(to_hit),
            reach_ft=int(reach) if reach else None,
            range_ft=rng or None,
        )
    action.damage = _parse_damage(body)

    if m := _RE_SAVE.search(body):
        action.save = SaveEffect(
            ability=_ABILITY_BY_NAME[m.group(2).lower()],
            dc=int(m.group(1)),
            on_success="half damage" if "half" in body.lower() else None,
        )
    return action


_SENTENCE_END = ".!?\"')’”"
# Lone ability words are never real feature headers — they're the tail of a
# spellcasting sentence ("...spellcasting ability is Wisdom. The hag can...").
_NON_HEADER_NAMES = {
    "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma",
}
# Small words allowed to be lowercase inside a real (title-cased) feature name,
# e.g. "Swarm of Black Birds", "Speak with Animals".
_NAME_CONNECTORS = {
    "of", "with", "and", "the", "to", "a", "an", "in", "or", "from", "by",
    "for", "on", "at", "as", "into", "upon", "but",
}


def _is_feature_name(name: str) -> bool:
    """Real feature/action names are title-cased noun phrases. A candidate that
    contains a lowercase *content* word (not a small connector) is a sentence
    fragment — e.g. "Its spellcasting ability is Wisdom" — not a header."""
    words = re.sub(r"\([^)]*\)", "", name).split()
    for w in words[1:]:  # first word is capitalised by construction
        token = w.strip(".,:;'’\"")
        if token and token[0].islower() and token.lower() not in _NAME_CONNECTORS:
            return False
    return True


def has_actions_section(text: str) -> bool:
    """Return True if *text* contains a recognised action-section header.

    Used by the pipeline to detect stat blocks that were truncated at a page
    break — a block with no ACTIONS / REACTIONS / etc. header almost certainly
    continues on the next page.
    """
    return bool(_SECTION_RE.search(text))


def _parse_entries(section_text: str, category: ActionCategory) -> list[Action]:
    """Split a section into individual named entries.

    A candidate header is only accepted if it begins a new thought — i.e. it's
    the first line of the section, or the previous line ended a sentence. This
    rejects mid-paragraph wraps like "...take the / Dodge action." or
    "...ability is / Charisma." being mistaken for new entries.
    """
    if not section_text.strip():
        return []
    accepted = []
    for m in _RE_ENTRY.finditer(section_text):
        name = re.sub(r"\s*\([^)]*\)", "", m.group(1)).strip().lower()
        if name in _NON_HEADER_NAMES:
            continue
        if not _is_feature_name(m.group(1)):
            continue
        prev = section_text[: m.start()].rstrip()
        if not prev or prev[-1] in _SENTENCE_END:
            accepted.append(m)
    entries: list[Action] = []
    for i, m in enumerate(accepted):
        name = m.group(1)
        end = accepted[i + 1].start() if i + 1 < len(accepted) else len(section_text)
        body = section_text[m.end():end]
        entries.append(_build_action(name, body, category))
    return entries


def _trim_stat_header(region: str) -> str:
    """Drop the stat-block header (AC/HP/.../Challenge) so only traits remain."""
    cut = 0
    for rx in (_RE_PROF, _RE_CHALLENGE):
        last = None
        for last in rx.finditer(region):
            pass
        if last:
            nl = region.find("\n", last.end())
            cut = max(cut, nl + 1 if nl != -1 else last.end())
    return region[cut:]


def _split_sections(text: str) -> tuple[str, dict[ActionCategory, str]]:
    """Return (traits_text, {category: section_text}) from a stat block."""
    matches = list(_SECTION_RE.finditer(text))
    first = matches[0].start() if matches else len(text)
    traits_text = _trim_stat_header(text[:first])

    sections: dict[ActionCategory, str] = {}
    for i, m in enumerate(matches):
        cat = _HEADER_TO_CAT[m.group(1).upper()]
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections[cat] = text[m.end():end]
    return traits_text, sections


def split_into_blocks(
    page_text: str, fonts: Optional[list[str]] = None
) -> list[str]:
    """Split one page's (column-ordered) text into one body per stat block.

    Anchors on each "Armor Class" line (the most reliable landmark — immune to
    size-word typos like "Garganutan"). Just above it sits the "<Size> <type>,
    <alignment>" line, and above *that* the monster's name (which may span more
    than one line). Pages with no "Armor Class" line yield nothing.

    If per-line ``fonts`` are supplied, the block ends where the font stops
    matching the stat block's own font (the AC line's font) — this trims away
    surrounding lore, encounter sidebars, and art credits that would otherwise
    bleed into the last feature. Without fonts, the block simply runs to the next
    stat block or the page end (used by tests).
    """
    lines = page_text.split("\n")
    if fonts is not None and len(fonts) != len(lines):
        fonts = None  # misaligned — fall back to the font-less behaviour
    ac_idxs = [i for i, ln in enumerate(lines) if _RE_AC_LINE.match(ln)]
    if not ac_idxs:
        return []

    # meta line for each Armor Class line = nearest non-empty line above it
    specs: list[tuple[int, int]] = []  # (meta_index, ac_index)
    for ac in ac_idxs:
        meta_i = ac - 1
        while meta_i >= 0 and not lines[meta_i].strip():
            meta_i -= 1
        specs.append((meta_i, ac))

    blocks: list[str] = []
    for k, (meta_i, ac) in enumerate(specs):
        lower = specs[k - 1][1] + 1 if k > 0 else 0  # don't reach into prev block
        name = _find_name(lines, meta_i, lower) or "Unknown Creature"
        hard_end = specs[k + 1][0] if k + 1 < len(specs) else len(lines)
        if fonts is not None:
            # Keep the meta line plus every line in the stat block's own font;
            # drop lore, encounter sidebars, and art credits (other fonts) that
            # the column order interleaves *within* or after the block. Filtering
            # (rather than cutting at the first other-font line) reconnects an
            # "Actions" header with action entries separated from it by a lore
            # sidebar, and never truncates the block early.
            #
            # Use the body font of lines immediately *after* the AC line rather
            # than the AC line's own font.  On some pages the AC line (and the
            # meta line above it) sit in the lore/flavor-text font while HP,
            # Speed, and the rest of the stat block are in the correct body
            # font.  Taking the majority font of the first few post-AC lines
            # gives the right answer in both the normal and the mis-typeset case.
            _sample_end = min(ac + 8, hard_end)
            _sample = [
                fonts[j]
                for j in range(ac + 1, _sample_end)
                if j < len(fonts) and fonts[j]
            ]
            sb_font = (
                collections.Counter(_sample).most_common(1)[0][0]
                if _sample
                else fonts[ac]
            )
            kept = [lines[meta_i]] + [
                lines[i]
                for i in range(meta_i + 1, hard_end)
                # Always keep the AC line itself (its font may be the lore
                # font on mis-typeset pages; we determined sb_font from the
                # lines *after* it to avoid being fooled by that).
                if i == ac
                or fonts[i] == sb_font
                or _SECTION_RE.match(lines[i])
            ]
            rest = "\n".join(kept)
        else:
            rest = "\n".join(lines[meta_i:hard_end])
        body = _strip_footer((name + "\n" + rest).strip())
        if body:
            blocks.append(body)
    return blocks


class OcrHeuristicParser:
    """OCR text -> StatBlock via regex. Best-effort, offline, fully testable."""

    name = "ocr-heuristic"

    def __init__(self, lang: str = "eng"):
        self.lang = lang

    def parse(
        self,
        page: PageImage,
        owner_id: str = "local-user",
        source: Optional[str] = None,
    ) -> list[StatBlock]:
        extraction = ocr_page(page, lang=self.lang)
        return [
            self.parse_text(
                extraction.text,
                owner_id=owner_id,
                source=source,
                source_page=page.index + 1,
                extraction=extraction,
            )
        ]

    # split out so tests can feed text directly without OCR / images
    def parse_text(
        self,
        text: str,
        owner_id: str = "local-user",
        source: Optional[str] = None,
        source_page: Optional[int] = None,
        extraction: Optional[ExtractionResult] = None,
    ) -> StatBlock:
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        warnings = list(extraction.warnings) if extraction else []
        found = 0
        total_fields = 5

        name = lines[0].strip() if lines else "Unknown Creature"

        sb = StatBlock(
            name=name,
            owner_id=owner_id,
            source=source,
            source_page=source_page,
            raw_text=text or None,
        )

        # meta line (size / type / alignment) — usually line 2
        for ln in lines[1:5]:
            if m := _RE_META.match(ln.strip()):
                sb.size = _SIZE_WORDS.get(m.group(1).lower())
                sb.creature_type = m.group(2).title()
                sb.alignment = m.group(3).strip()
                break
            if lm := _RE_META_LOOSE.match(ln.strip()):
                # misspelled size etc. — keep type/alignment, leave size unset
                sb.creature_type = lm.group(1).title()
                sb.alignment = lm.group(2).strip()
                break

        if m := _RE_AC.search(text):
            sb.armor_class = int(m.group(1))
            sb.armor_desc = (m.group(2) or "").strip("() ") or None
            found += 1
        if m := _RE_HP.search(text):
            sb.hit_points = int(m.group(1))
            sb.hit_dice = (m.group(2) or "").strip() or None
            found += 1
        if m := _RE_SPEED.search(text):
            sb.speed = _parse_speed(m.group(1))
            found += 1
        abilities, ok = _parse_abilities(text)
        if ok:
            sb.abilities = abilities
            found += 1
        if m := _RE_CHALLENGE.search(text):
            sb.challenge_rating = m.group(1)
            if m.group(2):
                sb.xp = int(m.group(2).replace(",", ""))
            found += 1
        if m := _RE_PROF.search(text):
            sb.proficiency_bonus = int(m.group(1))

        # secondary stat-header fields
        if m := _RE_SAVES.search(text):
            sb.saving_throws = _parse_bonuses(m.group(1))
        if m := _RE_SKILLS.search(text):
            sb.skills = _parse_bonuses(m.group(1))
        if m := _RE_SENSES.search(text):
            sb.senses, _ = _parse_senses(m.group(1))
        if pm := _RE_PASSIVE.search(text):
            sb.passive_perception = int(pm.group(1))
        if m := _RE_LANGS.search(text):
            sb.languages = _parse_list(m.group(1))
        for kind, value in _RE_DMG.findall(text):
            lst = _parse_list(value)
            k = kind.lower()
            if k == "vulnerabilities":
                sb.damage_vulnerabilities = lst
            elif k == "resistances":
                sb.damage_resistances = lst
            elif k == "immunities":
                sb.damage_immunities = lst
        if m := _RE_COND.search(text):
            sb.condition_immunities = _parse_list(m.group(1))

        # behaviours: traits + actions + bonus actions + reactions + legendary
        traits_text, sections = _split_sections(text)
        sb.traits = _parse_entries(traits_text, ActionCategory.TRAIT)
        sb.actions = _parse_entries(
            sections.get(ActionCategory.ACTION, ""), ActionCategory.ACTION
        )
        sb.bonus_actions = _parse_entries(
            sections.get(ActionCategory.BONUS_ACTION, ""),
            ActionCategory.BONUS_ACTION,
        )
        sb.reactions = _parse_entries(
            sections.get(ActionCategory.REACTION, ""), ActionCategory.REACTION
        )
        leg_text = sections.get(ActionCategory.LEGENDARY, "")
        sb.legendary_actions = _parse_entries(leg_text, ActionCategory.LEGENDARY)
        if lm := _RE_LEG_COUNT.search(leg_text):
            sb.legendary_action_count = int(lm.group(1))

        sb.parse_confidence = round(found / total_fields, 2)
        if sb.parse_confidence < 1.0:
            warnings.append(
                f"Heuristic parser filled {found}/{total_fields} core fields; "
                "consider the vision parser for full fidelity."
            )
        sb.parse_warnings = warnings
        return sb
