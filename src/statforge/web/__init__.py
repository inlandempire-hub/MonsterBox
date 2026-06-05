"""Minimal local web UI for StatForge.

A small Flask app serves one HTML page and a handful of JSON endpoints over the
existing engine (storage + roller + initiative tracker). No build step, no
Node — just `pip install statforge[web]` and `python -m statforge serve`.
"""

from .server import create_app, start_idle_watchdog

__all__ = ["create_app", "start_idle_watchdog"]
