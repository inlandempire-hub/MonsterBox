"""Vision parser tests — exercise the structured-output mapping without network.

We inject a fake Anthropic client whose `messages.parse(...)` returns a canned
`_ParsedPage`, so the real `_to_statblock` mapping logic (named-value lists ->
dicts, action passthrough, spellcasting folding, multiple blocks per page) is
verified end to end.
"""

from monsterbox.ingest.parser import (
    VisionLLMParser,
    _NamedInt,
    _ParsedPage,
    _ParsedSpellGroup,
    _ParsedStatBlock,
    _encode_image,
)
from monsterbox.models import (
    Action,
    AttackDetail,
    AttackKind,
    DamageComponent,
    Size,
)
from monsterbox.ingest.render import PageImage


class _FakeResponse:
    def __init__(self, parsed):
        self.parsed_output = parsed
        self.stop_reason = "end_turn"


class _FakeMessages:
    def __init__(self, parsed):
        self._parsed = parsed
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self._parsed)


class _FakeClient:
    def __init__(self, parsed):
        self.messages = _FakeMessages(parsed)


def _black_bird_page() -> _ParsedPage:
    spear = Action(
        name="Eclipse Spear",
        raw_text="Melee Weapon Attack: +7 to hit, reach 10 ft... 1d8+3 slashing",
        attack=AttackDetail(kind=AttackKind.MELEE_WEAPON, to_hit=7, reach_ft=10),
        damage=[
            DamageComponent(dice="1d8", bonus=3, average=7, damage_type="slashing"),
            DamageComponent(dice="1d8", average=4, damage_type="radiant"),
        ],
    )
    sb = _ParsedStatBlock(
        name="Black Bird",
        size=Size.MEDIUM,
        creature_type="Monstrosity",
        alignment="Chaotic Evil",
        armor_class=15,
        armor_desc="natural armor",
        hit_points=195,
        hit_dice="23d8 + 92",
        speed=[_NamedInt(name="walk", value=30), _NamedInt(name="fly", value=30)],
        saving_throws=[_NamedInt(name="Wisdom", value=7)],
        skills=[_NamedInt(name="Perception", value=7)],
        senses=[_NamedInt(name="darkvision", value=60)],
        passive_perception=17,
        languages=["Common", "Infernal"],
        challenge_rating="11",
        xp=7200,
        proficiency_bonus=4,
        actions=[spear],
        legendary_actions=[Action(name="Move", raw_text="moves up to its speed")],
        legendary_action_count=3,
        spell_groups=[_ParsedSpellGroup(frequency="At Will", spells=["darkness"])],
        parse_confidence=0.95,
    )
    return _ParsedPage(statblocks=[sb])


def _png_page() -> PageImage:
    return PageImage(index=0, data=b"\x89PNG\r\n\x1a\nfake", name="Im1.png")


def test_vision_maps_named_value_lists_to_dicts():
    client = _FakeClient(_black_bird_page())
    parser = VisionLLMParser(client=client)

    blocks = parser.parse(_png_page(), owner_id="t1", source="book.pdf")

    assert len(blocks) == 1
    sb = blocks[0]
    assert sb.name == "Black Bird"
    assert sb.owner_id == "t1"
    assert sb.source == "book.pdf"
    assert sb.source_page == 1
    # named-value lists folded into dicts
    assert sb.speed == {"walk": 30, "fly": 30}
    assert sb.saving_throws == {"Wisdom": 7}
    assert sb.senses == {"darkvision": 60}
    # behaviour passed through intact, raw_text preserved
    assert sb.actions[0].name == "Eclipse Spear"
    assert sb.actions[0].attack.to_hit == 7
    assert len(sb.actions[0].damage) == 2
    assert sb.actions[0].raw_text  # fidelity kept
    assert sb.legendary_action_count == 3
    # spell group folded into spellcasting
    assert sb.spellcasting is not None
    assert "darkness" in sb.spellcasting.at_will


def test_vision_sends_image_and_schema():
    client = _FakeClient(_black_bird_page())
    VisionLLMParser(client=client, model="claude-opus-4-8").parse(_png_page())
    call = client.messages.calls[0]
    assert call["model"] == "claude-opus-4-8"
    assert call["output_format"] is _ParsedPage
    # the page image is attached as a base64 block
    content = call["messages"][0]["content"]
    assert any(b.get("type") == "image" for b in content)


def test_from_env_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert VisionLLMParser.from_env() is None


def test_encode_image_detects_png():
    mt, b64 = _encode_image(b"\x89PNG\r\n\x1a\nrest")
    assert mt == "image/png"
    assert isinstance(b64, str) and b64
