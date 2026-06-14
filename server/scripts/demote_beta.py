"""Demote all comp (beta) accounts to free. Run when you leave Beta for Live.

Only touches plan == "comp" accounts (your beta testers). Admin accounts and
anyone already on free/pro are left alone, so you keep your own god account.

  python -m scripts.demote_beta            # dry run: list who WOULD change
  python -m scripts.demote_beta --apply     # actually flip comp -> free
"""
import argparse

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401  (register tables)
from app.models import User


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ap = argparse.ArgumentParser(description="Demote comp (beta) accounts to free.")
    ap.add_argument("--apply", action="store_true", help="apply the change (otherwise dry run)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        comps = db.scalars(select(User).where(User.plan == "comp")).all()
        if not comps:
            print("No comp accounts to demote.")
            return
        for u in comps:
            print(("demoting " if args.apply else "would demote ") + f"{u.email} (role={u.role})")
            if args.apply:
                u.plan = "free"
        if args.apply:
            db.commit()
            print(f"Done: {len(comps)} account(s) set to free.")
        else:
            print(f"\nDry run: {len(comps)} comp account(s) would become free. Re-run with --apply.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
