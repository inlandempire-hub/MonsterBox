from statforge.combat import InitiativeTracker
from statforge.ingest.parser import OcrHeuristicParser
from statforge.models import Size

# Mirrors the structure of the real scanned sample pages.
SAMPLE = """\
Soulscorcher Dragon
Gargantuan Fiend, Lawful Evil
Armor Class 23 (natural armor)
Hit Points 300 (24d20 + 200)
Speed 40 ft., fly 80 ft.
STR DEX CON INT WIS CHA
30 (+10) 14 (+2) 30 (+10) 18 (+4) 15 (+2) 20 (+5)
Saving Throws Dex +9, Con +17, Wis +9
Skills Deception +12, Perception +13
Damage Immunities fire, necrotic, poison
Senses blindsight 60 ft., darkvision 120 ft., passive Perception 23
Languages Abyssal, Common, Draconic, Infernal
Challenge 20 (25000 XP) Proficiency Bonus +8
"""


def test_parses_core_fields():
    sb = OcrHeuristicParser().parse_text(SAMPLE, owner_id="t1", source="book.pdf")
    assert sb.name == "Soulscorcher Dragon"
    assert sb.size == Size.GARGANTUAN
    assert sb.creature_type == "Fiend"
    assert sb.alignment == "Lawful Evil"
    assert sb.armor_class == 23
    assert sb.hit_points == 300
    assert sb.hit_dice == "24d20 + 200"
    assert sb.speed == {"walk": 40, "fly": 80}
    assert sb.challenge_rating == "20"
    assert sb.xp == 25000
    assert sb.proficiency_bonus == 8
    assert sb.owner_id == "t1"


def test_ability_scores_and_modifier():
    sb = OcrHeuristicParser().parse_text(SAMPLE)
    assert sb.abilities.strength == 30
    assert sb.abilities.charisma == 20
    from statforge.models import Ability

    assert sb.abilities.modifier(Ability.STR) == 10
    assert sb.abilities.modifier(Ability.CHA) == 5


def test_confidence_full_when_all_fields_present():
    sb = OcrHeuristicParser().parse_text(SAMPLE)
    assert sb.parse_confidence == 1.0


def test_template_spawns_independent_instances():
    sb = OcrHeuristicParser().parse_text(SAMPLE)
    tracker = InitiativeTracker()
    a, b = tracker.spawn(sb, count=2)
    assert a.id != b.id
    assert a.display_name != b.display_name
    # damaging one instance does not affect the other
    tracker.apply_damage(a, 50)
    assert a.current_hp == 250
    assert b.current_hp == 300
