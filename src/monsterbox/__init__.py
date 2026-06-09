"""MonsterBox — scan a stat block, run the encounter.

Skeleton package layout:

* :mod:`monsterbox.models`        — the data model (template vs. instance, roll events)
* :mod:`monsterbox.ingest`        — PDF -> page image -> structured StatBlock (the boundary)
* :mod:`monsterbox.combat`        — dice, roll engine, initiative tracker
* :mod:`monsterbox.storage`       — owner-scoped, local-first persistence
"""

from .models import (
    Action,
    Combatant,
    Encounter,
    RollEvent,
    StatBlock,
)

__version__ = "0.1.0"

__all__ = [
    "StatBlock",
    "Combatant",
    "Encounter",
    "Action",
    "RollEvent",
    "__version__",
]
