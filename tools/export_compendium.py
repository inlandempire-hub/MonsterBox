"""Bundle the desktop app's stat blocks into a single JSON array that the
web (PWA) build can import via its "Import JSON" button.

Usage:
    py tools/export_compendium.py                      # -> compendium.json
    py tools/export_compendium.py --out my-monsters.json
    py tools/export_compendium.py --data data --owner local-user

Hand the resulting file to a DM (or import it yourself) in the web app.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="Export stat blocks to one JSON array.")
    ap.add_argument("--data", default="data", help="data root (default: data)")
    ap.add_argument("--owner", default="local-user", help="owner id (default: local-user)")
    ap.add_argument("--out", default="compendium.json", help="output file")
    args = ap.parse_args()

    src = Path(args.data) / args.owner / "statblocks"
    if not src.is_dir():
        print(f"No stat blocks found at {src}")
        return 1

    blocks = []
    for f in sorted(src.glob("*.json")):
        try:
            blocks.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            print(f"  skipped {f.name}: {e}")

    Path(args.out).write_text(json.dumps(blocks, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(blocks)} stat blocks -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
