"""Minimal local web UI for MonsterBox.

A small Flask app serves one HTML page and a handful of JSON endpoints over the
existing engine (storage + roller + initiative tracker). No build step, no
Node — just `pip install monsterbox[web]` and `python -m monsterbox serve`.
"""

from .server import create_app, start_idle_watchdog

__all__ = ["create_app", "start_idle_watchdog"]
