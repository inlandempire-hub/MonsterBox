"""Command-line entry point for the skeleton.

    python -m monsterbox ingest <file.pdf> [--owner ID]
    python -m monsterbox list [--owner ID]
    python -m monsterbox show <statblock-id> [--owner ID]
    python -m monsterbox demo

``demo`` runs the whole loop without needing a real PDF or OCR: it parses a
bundled sample stat block (the kind of text OCR would yield), spawns combatants,
rolls initiative + an attack, and prints the structured roll log.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from .combat import InitiativeTracker, Roller
from .ingest import ingest_pdf
from .ingest.parser import OcrHeuristicParser
from .storage import Repository

# A representative OCR dump (mirrors the "Black Bird" sample page structure).
SAMPLE_TEXT = """\
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
ACTIONS
Multiattack. Black Bird makes two attacks with the Eclipse Spear.
Eclipse Spear. Melee Weapon Attack: +7 to hit, reach 10 ft., one target. \
Hit: 7 (1d8 + 3) slashing damage plus 4 (1d8) radiant damage.
"""


def _cmd_ingest(args) -> int:
    parser = None
    if args.parser == "vision":
        from .ingest.parser import VisionLLMParser

        parser = VisionLLMParser.from_env()
        if parser is None:
            print(
                "  ! --parser vision requested but no Anthropic client available "
                "(install `monsterbox[llm]` and set ANTHROPIC_API_KEY)."
            )
            return 1
    elif args.parser == "ocr":
        parser = OcrHeuristicParser()

    result = ingest_pdf(args.path, owner_id=args.owner, parser=parser)
    repo = Repository(args.data)
    print(f"Source       : {result.source}")
    print(f"Pages        : {result.page_count}")
    print(f"Input kind   : {result.input_kind}")
    print(f"Parser used  : {result.parser_used}")
    for w in result.warnings:
        print(f"  ! {w}")
    for sb in result.statblocks:
        path = repo.save_statblock(sb)
        print(
            f"  + {sb.name}  CR {sb.challenge_rating}  "
            f"AC {sb.armor_class}  HP {sb.hit_points}  "
            f"(confidence {sb.parse_confidence:.0%})  -> {path}"
        )
    return 0


def _cmd_list(args) -> int:
    repo = Repository(args.data)
    blocks = repo.list_statblocks(args.owner)
    if not blocks:
        print("(no stat blocks stored for this owner)")
        return 0
    for sb in blocks:
        print(f"{sb.id}  {sb.name:<24} CR {sb.challenge_rating or '?':<4} "
              f"HP {sb.hit_points}")
    return 0


def _cmd_show(args) -> int:
    repo = Repository(args.data)
    sb = repo.get_statblock(args.owner, args.id)
    print(sb.model_dump_json(indent=2))
    return 0


def _cmd_demo(args) -> int:
    owner = "local-user"
    print("=== 1. parse a stat block (OCR-text heuristic) ===")
    parser = OcrHeuristicParser()
    sb = parser.parse_text(SAMPLE_TEXT, owner_id=owner, source="demo")
    print(f"  {sb.name}: AC {sb.armor_class}, HP {sb.hit_points}, "
          f"CR {sb.challenge_rating}, confidence {sb.parse_confidence:.0%}")
    print(f"  actions parsed: {[a.name for a in sb.actions] or '(none yet)'}")

    print("\n=== 2. spawn combatants (template -> instances) ===")
    repo = Repository(args.data)
    repo.save_statblock(sb)
    tracker = InitiativeTracker()
    tracker.spawn(sb, count=2)
    roller = Roller(owner_id=owner)
    tracker.roll_initiative({sb.id: sb}, roller)
    for c in tracker.encounter.combatants:
        print(f"  {c.display_name}: init {c.initiative}, "
              f"HP {c.current_hp}/{c.max_hp}")

    print("\n=== 3. resolve an attack (structured roll events) ===")
    # use the Eclipse Spear action parsed straight from the text above —
    # no hand-building; this is what the parser produced.
    spear = next(a for a in sb.actions if a.name == "Eclipse Spear")
    print(f"  using parsed action: {spear.name} "
          f"(+{spear.attack.to_hit} to hit, {len(spear.damage)} damage parts)")
    attacker = tracker.encounter.combatants[0].display_name
    atk = roller.attack_roll(spear, source=attacker)
    dmg = roller.damage_roll(spear, source=attacker)
    repo.append_roll(atk)
    repo.append_roll(dmg)
    print(f"  {atk.source}: {atk.label} = {atk.total} "
          f"(d20 {atk.dice_results} {atk.modifier:+d})")
    print(f"  {dmg.source}: {dmg.label} = {dmg.total} "
          f"({dmg.expression}, dice {dmg.dice_results})")

    print("\n=== 4. roll log (DM-private events persisted) ===")
    for ev in repo.read_rolls(owner):
        print(f"  [{ev.roll_type.value}] {ev.source}: {ev.label} = {ev.total}")
    return 0


# Sample monsters for `seed` — verified against the source pages. Black Bird is
# the full rich block (traits + actions + legendary); the dragon is core stats.
SEED_MONSTERS = [
    """\
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
""",
    """\
Soulscorcher Dragon
Gargantuan Fiend, Lawful Evil
Armor Class 23 (natural armor)
Hit Points 300 (24d20 + 200)
Speed 40 ft., fly 80 ft.
STR DEX CON INT WIS CHA
30 (+10) 14 (+2) 30 (+10) 18 (+4) 15 (+2) 20 (+5)
Saving Throws Dex +9, Con +17, Wis +9
Skills Deception +12, Perception +13
Senses blindsight 60 ft., darkvision 120 ft., passive Perception 23
Languages Abyssal, Common, Draconic, Infernal
Challenge 20 (25000 XP) Proficiency Bonus +8
ACTIONS
Multiattack. The dragon makes three attacks: one with its bite and two with \
its claws.
Bite. Melee Weapon Attack: +18 to hit, reach 15 ft., one target. Hit: 17 \
(2d8 + 10) piercing damage plus 3 (1d6) necrotic damage.
Claw. Melee Weapon Attack: +18 to hit, reach 10 ft., one target. Hit: 17 \
(2d6 + 10) slashing damage.
""",
]


def _cmd_seed(args) -> int:
    repo = Repository(args.data)
    if args.reset:
        sb_dir = Path(args.data) / args.owner / "statblocks"
        if sb_dir.exists():
            shutil.rmtree(sb_dir)
            print(f"  reset: cleared {sb_dir}")
    parser = OcrHeuristicParser()
    for text in SEED_MONSTERS:
        sb = parser.parse_text(text, owner_id=args.owner, source="seed")
        repo.save_statblock(sb)
        print(f"  + seeded {sb.name} (CR {sb.challenge_rating}, "
              f"{len(sb.actions)} actions)")
    return 0


def _cmd_serve(args) -> int:
    from .web import create_app, start_idle_watchdog

    app = create_app(data_dir=args.data, owner=args.owner)
    if args.shutdown_on_idle and args.shutdown_on_idle > 0:
        # Used by the windowless launcher: exit once the page stops pinging.
        start_idle_watchdog(app, float(args.shutdown_on_idle))
    url = f"http://127.0.0.1:{args.port}"
    print(f"MonsterBox UI running at {url}  (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="monsterbox", description="MonsterBox skeleton")
    p.add_argument("--data", default="data", help="data root directory")
    p.add_argument("--owner", default="local-user", help="owner/tenant id")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("ingest", help="parse a PDF into stat blocks")
    pi.add_argument("path")
    pi.add_argument(
        "--parser",
        choices=["auto", "vision", "ocr"],
        default="auto",
        help="parser to use (auto: vision if ANTHROPIC_API_KEY set, else ocr)",
    )
    pi.set_defaults(func=_cmd_ingest)

    pl = sub.add_parser("list", help="list stored stat blocks")
    pl.set_defaults(func=_cmd_list)

    ps = sub.add_parser("show", help="print a stored stat block as JSON")
    ps.add_argument("id")
    ps.set_defaults(func=_cmd_show)

    pd = sub.add_parser("demo", help="run the end-to-end loop on sample data")
    pd.set_defaults(func=_cmd_demo)

    pseed = sub.add_parser("seed", help="load sample monsters into the library")
    pseed.add_argument("--reset", action="store_true",
                       help="clear existing stat blocks first")
    pseed.set_defaults(func=_cmd_seed)

    pserve = sub.add_parser("serve", help="run the local web UI")
    pserve.add_argument("--port", type=int, default=8000)
    pserve.add_argument(
        "--shutdown-on-idle", type=float, default=0,
        help="exit if the page stops sending heartbeats for N seconds "
             "(used by the windowless launcher; 0 = never)",
    )
    pserve.set_defaults(func=_cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
