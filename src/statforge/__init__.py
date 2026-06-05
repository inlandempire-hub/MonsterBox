"""StatForge — scan a stat block, run the encounter.

Skeleton package layout:

* :mod:`statforge.models`        — the data model (template vs. instance, roll events)
* :mod:`statforge.ingest`        — PDF -> page image -> structured StatBlock (the boundary)
* :mod:`statforge.combat`        — dice, roll engine, initiative tracker
* :mod:`statforge.storage`       — owner-scoped, local-first persistence
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
