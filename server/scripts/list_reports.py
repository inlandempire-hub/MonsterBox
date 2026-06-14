"""Print stored issue reports (newest first). Reports are always saved to the DB
even when SMTP email isn't configured, so nothing is ever lost.

  python -m scripts.list_reports
  python -m scripts.list_reports --limit 50
"""
import argparse

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.models import Report


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ap = argparse.ArgumentParser(description="List MonsterBox issue reports.")
    ap.add_argument("--limit", type=int, default=30)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.scalars(select(Report).order_by(Report.created_at.desc()).limit(args.limit)).all()
        if not rows:
            print("(no reports yet)")
            return
        for r in rows:
            when = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "?"
            shot = " [screenshot]" if r.had_screenshot else ""
            sent = "emailed" if r.emailed else "stored"
            print(f"--- #{r.id}  {when}  from={r.email or '(none)'}  {sent}{shot}")
            print(r.message)
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
