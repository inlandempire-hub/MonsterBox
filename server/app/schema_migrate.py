"""Tiny idempotent schema touch-ups for columns added after a table already
exists in prod. `Base.metadata.create_all` only creates *missing tables*, never
new columns, so we add them by hand here. Safe to run on every startup; works on
both Postgres (prod) and SQLite (local)."""
from sqlalchemy import inspect, select, text

from .db import SessionLocal, engine
from .models import User, generate_public_id


def ensure_schema() -> None:
    insp = inspect(engine)
    if "users" not in insp.get_table_names():
        return  # fresh DB: create_all already built the full table

    cols = {c["name"] for c in insp.get_columns("users")}
    if "public_id" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE users ADD COLUMN public_id VARCHAR"))
        # unique index (NULLs are distinct on both pg + sqlite, so pre-backfill is fine)
        with engine.begin() as conn:
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_public_id ON users (public_id)"))

    _backfill_public_ids()


def _backfill_public_ids() -> None:
    db = SessionLocal()
    try:
        rows = db.scalars(select(User).where(User.public_id.is_(None))).all()
        if not rows:
            return
        taken = set(db.scalars(select(User.public_id).where(User.public_id.is_not(None))).all())
        for u in rows:
            pid = generate_public_id()
            while pid in taken:
                pid = generate_public_id()
            taken.add(pid)
            u.public_id = pid
        db.commit()
    finally:
        db.close()
