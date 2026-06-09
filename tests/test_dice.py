import random

from monsterbox.combat import dice


def test_roll_is_deterministic_with_seed():
    rng = random.Random(42)
    r = dice.roll("2d6+3", rng=rng)
    assert len(r.dice_results) == 2
    assert all(1 <= d <= 6 for d in r.dice_results)
    assert r.modifier == 3
    assert r.total == sum(r.dice_results) + 3


def test_flat_only_expression():
    r = dice.roll("+5")
    assert r.dice_results == []
    assert r.total == 5


def test_advantage_takes_higher():
    rng = random.Random(1)
    r = dice.roll_d20(modifier=2, advantage="advantage", rng=rng)
    assert len(r.dice_results) == 2
    assert r.total == max(r.dice_results) + 2


def test_disadvantage_takes_lower():
    rng = random.Random(1)
    r = dice.roll_d20(modifier=0, advantage="disadvantage", rng=rng)
    assert r.total == min(r.dice_results)
