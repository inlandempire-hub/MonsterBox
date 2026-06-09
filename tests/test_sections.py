"""Section parsing: pull traits / actions / legendary actions out of stat-block
text (the digital-PDF and OCR fallback path)."""

from monsterbox.ingest.columns import _lines_from_words
from monsterbox.ingest.parser import OcrHeuristicParser, split_into_blocks
from monsterbox.models import Ability, AttackKind

BLACK_BIRD = """\
Black Bird
Medium Monstrosity, Chaotic Evil
Armor Class 15 (natural armor)
Hit Points 195 (23d8 + 92)
Speed 30 ft., fly 30 ft.
STR DEX CON INT WIS CHA
16 (+3) 16 (+3) 18 (+4) 13 (+1) 16 (+3) 20 (+5)
Saving Throws Int +5, Wis +7, Cha +8
Skills Acrobatics +7, Perception +7
Condition Immunities charmed
Senses darkvision 60 ft., passive Perception 17
Languages Common, Infernal
Challenge 11 (7200 XP) Proficiency Bonus +4
Legendary Resistance (3/Day). If Black Bird fails a saving throw, he can \
choose to succeed instead.
Swarm of Black Birds. Any creature that starts its turn within 10 feet must \
make a DC 17 Constitution saving throw, taking 7 (2d6) piercing damage on a \
failure, or half as much on a success.
ACTIONS
Multiattack. Black Bird makes two attacks with the Eclipse Spear.
Eclipse Spear. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. \
Hit: 7 (1d8 + 3) slashing damage plus 4 (1d8) radiant damage.
LEGENDARY ACTIONS
Black Bird can take 3 legendary actions. Black Bird regains spent legendary \
actions at the start of its turn.
Move. Black Bird moves up to his speed.
Swarm (Costs 3 Actions). Black Bird directs his swarm at one creature within \
60 feet. DC 17 Dexterity saving throw, taking 28 (8d6) piercing damage.
"""


def _parse():
    return OcrHeuristicParser().parse_text(BLACK_BIRD, owner_id="dm")


def test_traits_parsed_with_usage():
    sb = _parse()
    names = [t.name for t in sb.traits]
    assert "Legendary Resistance" in names
    assert "Swarm of Black Birds" in names
    lr = next(t for t in sb.traits if t.name == "Legendary Resistance")
    assert lr.usage == "3/Day"
    swarm = next(t for t in sb.traits if t.name == "Swarm of Black Birds")
    assert swarm.save is not None
    assert swarm.save.ability == Ability.CON
    assert swarm.save.dc == 17


def test_actions_parsed_with_attack_and_damage():
    sb = _parse()
    names = [a.name for a in sb.actions]
    assert names == ["Multiattack", "Eclipse Spear"]
    spear = sb.actions[1]
    assert spear.attack is not None
    assert spear.attack.kind == AttackKind.MELEE_WEAPON
    assert spear.attack.to_hit == 7
    assert spear.attack.reach_ft == 10
    assert len(spear.damage) == 2
    assert spear.damage[0].dice == "1d8"
    assert spear.damage[0].bonus == 3
    assert spear.damage[1].damage_type == "radiant"


def test_legendary_actions_and_count():
    sb = _parse()
    assert sb.legendary_action_count == 3
    names = [a.name for a in sb.legendary_actions]
    assert "Move" in names
    assert "Swarm" in names
    swarm = next(a for a in sb.legendary_actions if a.name == "Swarm")
    assert swarm.legendary_cost == 3
    assert swarm.save is not None
    assert swarm.save.ability == Ability.DEX
    assert swarm.damage[0].dice == "8d6"


def test_header_stats_not_misread_as_traits():
    sb = _parse()
    # the stat-header lines (Saving Throws, Senses, ...) must not become traits
    trait_names = [t.name for t in sb.traits]
    assert "Saving Throws Int +5, Wis +7, Cha +8" not in trait_names
    assert all("Senses" not in n for n in trait_names)


def test_secondary_fields_parsed():
    sb = _parse()
    assert sb.saving_throws == {"Int": 5, "Wis": 7, "Cha": 8}
    assert sb.skills == {"Acrobatics": 7, "Perception": 7}
    assert sb.senses == {"darkvision": 60}
    assert sb.passive_perception == 17
    assert sb.languages == ["Common", "Infernal"]
    assert sb.condition_immunities == ["charmed"]


# --- page splitting (column-ordered text -> one body per monster) ----------- #
PAGE_TWO_MONSTERS = """\
Humanoids
Bullywug Potentate
Medium humanoid (bullywug), neutral evil
Armor Class 16 (breastplate)
Hit Points 58 (9d8 + 18)
Speed 20 ft., swim 30 ft.
STR DEX CON INT WIS CHA
14 (+2) 12 (+1) 14 (+2) 11 (+0) 12 (+1) 15 (+2)
Challenge 5 (1,800 XP)
some flavour text that should be ignored entirely.
Animated Armor of
Invulnerability
Large construct, unaligned
Armor Class 18 (natural armor)
Hit Points 127 (17d10 + 34)
Speed 30 ft.
STR DEX CON INT WIS CHA
18 (+4) 11 (+0) 15 (+2) 1 (-5) 11 (+0) 1 (-5)
Challenge 10 (5,900 XP)
17
"""


def test_split_handles_multiple_monsters_and_names():
    blocks = split_into_blocks(PAGE_TWO_MONSTERS)
    assert len(blocks) == 2
    sbs = [OcrHeuristicParser().parse_text(b) for b in blocks]
    names = [s.name for s in sbs]
    # section header "Humanoids" must NOT be glued onto the name
    assert names[0] == "Bullywug Potentate"
    # multi-line name must be joined
    assert names[1] == "Animated Armor of Invulnerability"
    # trailing page-number footer ("17") must be stripped from the last block
    assert "\n17" not in blocks[1]
    assert sbs[1].armor_class == 18


def test_wrapped_sentence_not_a_false_action():
    # "Dodge action." is the tail of Multiattack on its own line; it must not be
    # promoted to a separate action just because the next line starts capitalised.
    text = """\
Goblin Test
Medium humanoid, neutral evil
Armor Class 15
Hit Points 10 (3d6)
Speed 30 ft.
STR DEX CON INT WIS CHA
10 (+0) 14 (+2) 10 (+0) 10 (+0) 8 (-1) 8 (-1)
Challenge 1 (200 XP)
ACTIONS
Multiattack. The goblin makes two attacks. It can then take the
Dodge action.
Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 damage.
"""
    sb = OcrHeuristicParser().parse_text(text)
    names = [a.name for a in sb.actions]
    assert names == ["Multiattack", "Scimitar"]
    assert "Dodge action" not in names


def test_spellcasting_not_oversplit():
    # A spellcasting feature's internal sentences must not become extra features.
    text = """\
Hag Test
Medium fey, neutral evil
Armor Class 15
Hit Points 50 (10d8)
Speed 30 ft.
STR DEX CON INT WIS CHA
14 (+2) 12 (+1) 12 (+1) 13 (+1) 14 (+2) 16 (+3)
Challenge 4 (1,100 XP)
Innate Spellcasting. The hag is a powerful innate caster.
Its spellcasting ability is Charisma. The hag can innately cast spells.
Mimicry. The hag can mimic animal sounds and humanoid voices.
"""
    sb = OcrHeuristicParser().parse_text(text)
    names = [t.name for t in sb.traits]
    assert "Innate Spellcasting" in names
    assert "Mimicry" in names                       # real feature still found
    assert not any("ability is" in n for n in names)
    assert not any(n.lower() == "charisma" for n in names)


def test_abilities_with_unicode_minus():
    # negative modifiers in real books use a Unicode minus (−), not ASCII -.
    text = (
        "Imp\nTiny fiend, lawful evil\nArmor Class 13\nHit Points 10 (3d6)\n"
        "Speed 20 ft.\nSTR DEX CON INT WIS CHA\n"
        "6 (−2) 17 (+3) 13 (+1) 11 (+0) 12 (+1) 14 (+2)\n"
        "Challenge 1 (200 XP)\n"
    )
    sb = OcrHeuristicParser().parse_text(text)
    assert sb.abilities.strength == 6        # was lost before the fix
    assert sb.abilities.charisma == 14


def test_split_keeps_section_header_in_other_font():
    # ToB3 sets the "ACTIONS" header in a decorative font; the font filter must
    # keep it (else actions get dumped into traits).
    lines = [
        "GOBLIN", "Small humanoid, neutral evil", "Armor Class 15",
        "Hit Points 7 (2d6)", "Speed 30 ft.", "STR DEX CON INT WIS CHA",
        "8 (-1) 14 (+2) 10 (+0) 10 (+0) 8 (-1) 8 (-1)", "Challenge 1/4 (50 XP)",
        "Nimble Escape. The goblin can disengage as a bonus action.",
        "ACTIONS",
        "Scimitar. Melee Weapon Attack: +4 to hit, reach 5 ft. Hit: 5 damage.",
    ]
    fonts = (["Display"] + ["Body"] * 8 + ["Display"] + ["Body"])  # ACTIONS = Display
    blocks = split_into_blocks("\n".join(lines), fonts)
    assert len(blocks) == 1
    sb = OcrHeuristicParser().parse_text(blocks[0])
    assert sb.name == "GOBLIN"
    assert [a.name for a in sb.actions] == ["Scimitar"]


def test_multipage_statblock_continuation_whole_page():
    """A stat block whose ACTIONS section is on the *next* page must be stitched
    into a single, fully-parsed block — pattern A: the continuation page has
    no new stat blocks at all (e.g. Iorvensiav in ToB3).
    """
    from monsterbox.ingest.pipeline import IngestResult, _blocks_from_pages

    body_font = "SegoeUI"
    deco_font = "Biondi"

    # Page 1: full stat-block header + traits, NO section headers.
    page1: list[tuple[str, str]] = [
        ("Iorvensiav", body_font),
        ("Gargantuan Fiend (Devil), Lawful Evil", body_font),
        ("Armor Class 21 (natural armor)", body_font),
        ("Hit Points 362 (25d20 + 100)", body_font),
        ("Speed 50 ft., fly 90 ft.", body_font),
        ("STR DEX CON INT WIS CHA", body_font),
        ("28 (+9) 18 (+4) 19 (+4) 22 (+6) 20 (+5) 27 (+8)", body_font),
        ("Challenge 24 (62,000 XP) Proficiency Bonus +7", body_font),
        ("Amphibious. Iorvensiav can breathe air and water.", body_font),
    ]

    # Page 2: continuation with traits + ACTIONS (no Armor Class line at all).
    page2: list[tuple[str, str]] = [
        ("Iorvensiav rules a portion of the plane.", "VerdigrisMVBProText"),  # lore – filtered
        ("Legendary Resistance (3/Day). If Iorvensiav fails a saving throw, she can choose to succeed instead.", body_font),
        ("Magic Resistance. Iorvensiav has advantage on saving throws against spells.", body_font),
        ("ACTIONS", deco_font),
        ("Multiattack. Iorvensiav makes one Bite and two Claw attacks.", body_font),
        ("Bite. Melee Weapon Attack: +16 to hit, reach 15 ft., one target. Hit: 20 (2d10 + 9) piercing damage.", body_font),
        ("LEGENDARY ACTIONS", deco_font),
        ("Iorvensiav can take 3 legendary actions.", body_font),
        ("Detect. Iorvensiav makes a Wisdom (Perception) check.", body_font),
    ]

    result = IngestResult(source="test.pdf", page_count=2,
                          is_scanned=False, input_kind="digital", parser_used="test")
    _blocks_from_pages([page1, page2], result, "dm", "test.pdf")

    assert len(result.statblocks) == 1
    sb = result.statblocks[0]
    assert sb.name == "Iorvensiav"
    trait_names = [t.name for t in sb.traits]
    assert "Amphibious" in trait_names
    assert "Legendary Resistance" in trait_names
    assert "Magic Resistance" in trait_names
    action_names = [a.name for a in sb.actions]
    assert "Multiattack" in action_names
    assert "Bite" in action_names
    leg_names = [a.name for a in sb.legendary_actions]
    assert "Detect" in leg_names
    assert sb.legendary_action_count == 3
    assert not any("Efrizarr" in n for n in trait_names), "lore sidebar leaked into traits"


def test_multipage_statblock_continuation_shared_page():
    """Pattern B: the continuation content sits at the TOP of a page that
    *also* starts a completely separate new stat block further down.

    Example: Hala'ath's ACTIONS + LEGENDARY ACTIONS are the first things on
    the page, then the HALADRON stat block starts (with its own Armor Class).
    Both must be parsed correctly.
    """
    from monsterbox.ingest.pipeline import IngestResult, _blocks_from_pages

    body_font = "SegoeUI"
    deco_font = "Biondi"

    # Page 1: Hala'ath header + 2 traits, no ACTIONS.
    page1: list[tuple[str, str]] = [
        ("Hala'ath, the Sentinel of Progress", body_font),
        ("Huge Celestial, Lawful Good", body_font),
        ("Armor Class 19 (natural armor)", body_font),
        ("Hit Points 100 (10d12 + 30)", body_font),
        ("Speed 0 ft., fly 150 ft.", body_font),
        ("STR DEX CON INT WIS CHA", body_font),
        ("19 (+4) 14 (+2) 18 (+4) 22 (+6) 18 (+4) 20 (+5)", body_font),
        ("Challenge 22 (41,000 XP) Proficiency Bonus +7", body_font),
        ("Magic Resistance. Hala'ath has advantage on saves against spells.", body_font),
        # stat block truncated — no ACTIONS section yet
    ]

    # Page 2: Hala'ath's ACTIONS / LEGENDARY ACTIONS FIRST, then a new Haladron block.
    page2: list[tuple[str, str]] = [
        # --- Hala'ath continuation (before Haladron's AC line) ---
        ("ACTIONS", deco_font),
        ("Multiattack. Hala'ath makes three Titanium Wings attacks.", body_font),
        ("Titanium Wings. Melee Weapon Attack: +12 to hit, reach 10 ft. Hit: 14 (2d8 + 5) slashing damage.", body_font),
        ("LEGENDARY ACTIONS", deco_font),
        ("Hala'ath can take 3 legendary actions.", body_font),
        ("Move. Hala'ath moves up to half its speed.", body_font),
        # --- Haladron name + meta appear before the AC line ---
        ("Haladron", body_font),
        ("Tiny Celestial, Lawful Good", body_font),
        # ← _pre_ac_continuation_text must stop here ↓
        ("Armor Class 13 (natural armor)", body_font),   # NEW stat block starts
        ("Hit Points 28 (8d4 + 8)", body_font),
        ("Speed 0 ft., fly 60 ft.", body_font),
        ("STR DEX CON INT WIS CHA", body_font),
        ("13 (+1) 12 (+1) 12 (+1) 15 (+2) 15 (+2) 10 (+0)", body_font),
        ("Challenge 1/2 (100 XP) Proficiency Bonus +2", body_font),
        ("Flyby. The haladron doesn't provoke opportunity attacks.", body_font),
        ("ACTIONS", deco_font),
        ("Bolt of Law. Ranged Spell Attack: +4 to hit, range 60 ft. Hit: 6 (1d8 + 2) radiant.", body_font),
    ]

    result = IngestResult(source="test.pdf", page_count=2,
                          is_scanned=False, input_kind="digital", parser_used="test")
    _blocks_from_pages([page1, page2], result, "dm", "test.pdf")

    assert len(result.statblocks) == 2, (
        f"Expected 2 stat blocks, got {len(result.statblocks)}: "
        f"{[s.name for s in result.statblocks]}"
    )
    halath, haladron = result.statblocks[0], result.statblocks[1]

    # Hala'ath should have its trait AND actions from both pages
    assert "Magic Resistance" in [t.name for t in halath.traits]
    assert "Multiattack" in [a.name for a in halath.actions]
    assert "Titanium Wings" in [a.name for a in halath.actions]
    assert "Move" in [a.name for a in halath.legendary_actions]
    assert halath.legendary_action_count == 3

    # Haladron should be fully intact too
    assert haladron.name == "Haladron"
    assert haladron.armor_class == 13
    assert "Flyby" in [t.name for t in haladron.traits]
    assert "Bolt of Law" in [a.name for a in haladron.actions]


def test_space_before_period_in_entry_name():
    """pdfplumber sometimes inserts a space between an entry name and its
    period: "False Appearance . While the nariphon …".  Both the trait name
    and the action name must be parsed correctly despite the extra space.
    """
    text = """\
Nariphon
Huge Plant, Neutral
Armor Class 10 (natural armor)
Hit Points 195 (17d12 + 85)
Speed 15 ft.
STR DEX CON INT WIS CHA
24 (+7) 6 (-3) 21 (+5) 6 (-1) 14 (+2) 9 (-1)
Challenge 13 (10,000 XP)
False Appearance . While the nariphon remains motionless, it is indistinguishable from a tree.
Vegetative Clone . A vegetative clone resembles the creature hit by the nariphon's attack.
ACTIONS
Multiattack . The nariphon makes four Roots or Thorns attacks.
Roots . Melee Weapon Attack: +12 to hit, reach 15 ft., one target. Hit: 18 (2d10 + 7) bludgeoning damage.
Thorns . Ranged Weapon Attack: +12 to hit, range 30/120 ft., one target. Hit: 17 (3d6 + 7) piercing damage.
BONUS ACTIONS
Bury . One creature grappled by the nariphon is knocked prone.
"""
    sb = OcrHeuristicParser().parse_text(text)
    trait_names = [t.name for t in sb.traits]
    action_names = [a.name for a in sb.actions]
    bonus_names = [a.name for a in sb.bonus_actions]
    assert "False Appearance" in trait_names,  "space-before-period trait not parsed"
    assert "Vegetative Clone" in trait_names,  "space-before-period trait not parsed"
    assert "Multiattack" in action_names,      "space-before-period action not parsed"
    assert "Roots" in action_names,            "space-before-period action not parsed"
    assert "Thorns" in action_names,           "space-before-period action not parsed"
    assert "Bury" in bonus_names,              "space-before-period bonus action not parsed"


def test_ac_line_in_wrong_font_does_not_poison_filter():
    """If the Armor Class line (and the meta line above it) happen to be
    rendered in the lore/flavour font rather than the stat-block body font,
    the font filter must still use the body font — not the AC line's font.

    This mirrors the ToB3 Pyrite Pile page where 'Large Elemental, Unaligned'
    and 'Armor Class 18 (natural armor)' are in VerdigrisMVBProText while
    every other stat-block line is in SegoeUI.
    """
    lore_font = "VerdigrisMVBProText"
    body_font = "SegoeUI"
    deco_font = "Biondi"

    lines = [
        "Pyrite Pile lore text here.",         # lore column — filtered out
        "PYRITE PILE",                          # name (body font)
        "Large Elemental, Unaligned",           # meta — WRONG FONT (lore)
        "Armor Class 18 (natural armor)",       # AC   — WRONG FONT (lore)
        "Hit Points 136 (13d10 + 65)",
        "Speed 30 ft.",
        "STR DEX CON INT WIS CHA",
        "20 (+5) 10 (+0) 20 (+5) 5 (-3) 8 (-1) 19 (+4)",
        "Challenge 6 (2,300 XP) Proficiency Bonus +3",
        "False Appearance. While the pyrite pile remains motionless, it is indistinguishable.",
        "Gold Fever. A humanoid within 60 ft. must succeed on a DC 15 Wisdom saving throw.",
        "ACTIONS",
        "Multiattack. The pyrite pile makes two Slam attacks.",
        "Slam. Melee Weapon Attack: +8 to hit, reach 5 ft. Hit: 15 (3d6 + 5) bludgeoning damage.",
    ]
    fonts = [
        lore_font,  # lore text
        body_font,  # PYRITE PILE
        lore_font,  # Large Elemental (wrong font — the bug case)
        lore_font,  # Armor Class 18 (wrong font — the bug case)
        body_font,  # Hit Points
        body_font,  # Speed
        body_font,  # STR DEX CON
        body_font,  # scores
        body_font,  # Challenge
        body_font,  # False Appearance
        body_font,  # Gold Fever
        deco_font,  # ACTIONS
        body_font,  # Multiattack
        body_font,  # Slam
    ]
    blocks = split_into_blocks("\n".join(lines), fonts)
    assert len(blocks) == 1
    sb = OcrHeuristicParser().parse_text(blocks[0])
    assert sb.name == "PYRITE PILE"
    assert sb.armor_class == 18
    assert sb.hit_points == 136
    trait_names = [t.name for t in sb.traits]
    assert "False Appearance" in trait_names, "trait filtered out by wrong-font AC line"
    assert "Gold Fever" in trait_names,       "trait filtered out by wrong-font AC line"
    action_names = [a.name for a in sb.actions]
    assert "Multiattack" in action_names,     "action filtered out by wrong-font AC line"
    assert "Slam" in action_names,            "action filtered out by wrong-font AC line"


def test_line_words_ordered_left_to_right_despite_baseline_jitter():
    # an italic label a sub-pixel off the baseline must not scramble word order
    words = [
        {"text": "Melee", "x0": 60, "x1": 90, "top": 99.6, "fontname": "Body"},
        {"text": "Slam.", "x0": 10, "x1": 40, "top": 100.4, "fontname": "Body"},
        {"text": "+5", "x0": 120, "x1": 140, "top": 100.1, "fontname": "Body"},
    ]
    lines = _lines_from_words(words)
    assert len(lines) == 1
    assert lines[0][0] == "Slam. Melee +5"


# ---------------------------------------------------------------------------
# Running-header / footer ("page chrome") stripping.  Some books print the
# book title, a thumb-index letter, and the page number in the SAME decorative
# font as the monster names, directly above a stat block in column-reading
# order (Tome of Beasts 3).  Without stripping, the name detector swallows them
# ("C TOME OF BEASTS 3 RAZORBACK CRAB"); over-stripping the repeated meta line
# instead loses the name entirely ("Unknown Creature").
# ---------------------------------------------------------------------------
from monsterbox.ingest.pipeline import strip_page_chrome, _blocks_from_pages, IngestResult


def _grolar_page(i):
    """A minimal complete stat block, preceded by the page chrome that ToB3
    renders right above the name (index letter + book title), and a trailing
    page number — all in the title font."""
    return [
        ("C", "Biondi"),                              # thumb-index letter (furniture)
        ("TOME OF BEASTS 3", "Biondi"),               # running footer (chrome)
        (f"GROLAR BEAR {i}", "SegoeUI"),              # the real name (body font)
        ("Large Beast, Unaligned", "SegoeUI"),        # meta — repeats every page!
        ("Armor Class 14 (natural armor)", "SegoeUI"),
        ("Hit Points 68 (8d10 + 24)", "SegoeUI"),
        ("Speed 40 ft.", "SegoeUI"),
        ("STR DEX CON INT WIS CHA", "SegoeUI"),
        ("20 (+5) 12 (+1) 16 (+3) 3 (-4) 12 (+1) 8 (-1)", "SegoeUI"),
        ("Challenge 3 (700 XP) Proficiency Bonus +2", "SegoeUI"),
        ("Keen Smell. The bear has advantage on Wisdom (Perception) checks.", "SegoeUI"),
        ("ACTIONS", "Biondi"),
        ("Multiattack. The bear makes two Claw attacks.", "SegoeUI"),
        ("Claw. Melee Weapon Attack: +7 to hit, reach 5 ft., one target. "
         "Hit: 11 (2d6 + 5) slashing damage.", "SegoeUI"),
        ("98", "Biondi"),                             # page number (furniture)
    ]


def test_strip_page_chrome_removes_footer_keeps_structure():
    pages = [_grolar_page(i) for i in range(6)]
    cleaned = strip_page_chrome(pages)
    flat = [t for page in cleaned for t, _ in page]
    # running footer + furniture gone …
    assert "TOME OF BEASTS 3" not in flat
    assert "C" not in flat
    assert "98" not in flat
    # … but the repeated meta line and ability row (structural) are kept …
    assert "Large Beast, Unaligned" in flat
    assert "STR DEX CON INT WIS CHA" in flat
    # … and the unique names survive
    assert "GROLAR BEAR 0" in flat


def test_page_footer_not_swallowed_into_name():
    pages = [_grolar_page(i) for i in range(6)]
    result = IngestResult(source="t.pdf", page_count=6, is_scanned=False,
                          input_kind="digital", parser_used="text")
    _blocks_from_pages(pages, result, owner_id="t", source="t.pdf")
    assert len(result.statblocks) == 6
    names = [sb.name for sb in result.statblocks]
    # the footer/index letter must NOT be glued onto the name …
    assert all("TOME OF BEASTS" not in n for n in names)
    # … and protecting the repeated meta line keeps the name detectable
    assert all("Unknown" not in n for n in names)
    assert "GROLAR BEAR 0" in names
