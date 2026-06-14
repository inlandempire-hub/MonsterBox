"""God-mode CLI: grant or revoke full access by email.

Run from the server/ directory:

  # give someone free, full (post-paywall) access (by email OR by account id):
  python -m scripts.grant_access --email friend@example.com --plan comp
  python -m scripts.grant_access --id MB-7Q3K2P --plan comp

  # make yourself a god account (full access + can grant from the app):
  python -m scripts.grant_access --email you@example.com --role admin

  # revoke back to the free tier:
  python -m scripts.grant_access --email friend@example.com --plan free

  # see everyone:
  python -m scripts.grant_access --list

You can grant access to an email BEFORE that person has signed up; the row is
pre-created and binds to their account automatically on first login.
"""
import argparse

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401  (register tables)
from app.models import User


def main() -> None:
    Base.metadata.create_all(bind=engine)
    ap = argparse.ArgumentParser(description="Grant/revoke MonsterBox access by email or account id.")
    ap.add_argument("--email")
    ap.add_argument("--id", dest="account_id", help="public account id, e.g. MB-7Q3K2P")
    ap.add_argument("--plan", choices=["free", "pro", "comp"])
    ap.add_argument("--role", choices=["user", "admin"])
    ap.add_argument("--list", action="store_true", help="list all users and exit")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            users = db.scalars(select(User).order_by(User.email)).all()
            if not users:
                print("(no users yet)")
            for u in users:
                print(f"{(u.public_id or '-'):11} {u.email:32} plan={u.plan:5} role={u.role:5} full_access={u.has_full_access}")
            return

        if not args.email and not args.account_id:
            ap.error("pass --email or --id (or use --list)")
        if not args.plan and not args.role:
            ap.error("nothing to do: pass --plan and/or --role")

        if args.account_id:
            aid = args.account_id.strip().upper()
            user = db.scalar(select(User).where(User.public_id == aid))
            if user is None:
                ap.error(f"no account with id {aid}")
        else:
            email = args.email.strip().lower()
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(email=email)
                db.add(user)
                print(f"(pre-created {email}; it will bind to their account on first login)")
        if args.plan:
            user.plan = args.plan
        if args.role:
            user.role = args.role
        db.commit()
        db.refresh(user)
        print(f"OK  {user.public_id or '-'}  {user.email}  plan={user.plan}  role={user.role}  full_access={user.has_full_access}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
