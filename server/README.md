# MonsterBox API (P1 backend)

FastAPI backend for MonsterBox: accounts, entitlements, and per-user cloud sync.
Identity is provided by **Supabase Auth** (a verified JWT); all app-level
authorization (who is Pro, who is a god account) lives in this service's own
database, so you keep full control of access.

This is the P1 skeleton — backend + account system. Stripe billing and the
frontend sync wiring come in later parts.

## Quick start (local, no Supabase needed yet)

From the `server/` directory:

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate     macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                 # (cp on macOS/Linux); DEV_AUTH=true is fine for local
uvicorn app.main:app --reload --port 8090
```

Open http://127.0.0.1:8090/docs for the interactive API. With `DEV_AUTH=true`
you can authenticate by sending a header `X-Dev-User: you@example.com` instead
of a real token, so you can try everything before wiring up Supabase.

Run the tests:

```bash
pytest -q
```

## Accounts & entitlements

Each user row carries:

| field | values | meaning |
|-------|--------|---------|
| `plan` | `free` \| `pro` \| `comp` | `comp` = free full access you granted |
| `role` | `user` \| `admin` | `admin` = god account (full access + can grant) |

`has_full_access = admin OR pro OR comp`. Every paywalled route depends on
`require_full_access`; free users get HTTP 402.

## God / comp accounts

Grant or revoke access by email with the CLI (from `server/`):

```bash
# free, full access for someone you choose:
python -m scripts.grant_access --email friend@example.com --plan comp

# make yourself a god account:
python -m scripts.grant_access --email you@example.com --role admin

# revoke back to free:
python -m scripts.grant_access --email friend@example.com --plan free

# list everyone:
python -m scripts.grant_access --list
```

You can grant access **before** the person signs up — the row is pre-created and
binds to their Supabase account automatically on first login (matched by email).
Admins can also grant from inside the app via `POST /api/admin/grant`.

## Wiring up Supabase (when ready)

1. Create a project at supabase.com (free tier is fine).
2. Settings -> API -> copy the **JWT Secret** into `.env` as `SUPABASE_JWT_SECRET`,
   and set `DEV_AUTH=false`.
3. Use the same project's Postgres connection string as `DATABASE_URL`
   (`postgresql+psycopg://...`) for production.
4. The frontend signs in with `@supabase/supabase-js`, then sends the session's
   access token as `Authorization: Bearer <token>` to this API. (Frontend wiring
   is the next P1 part.)

## Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/health` | none | liveness |
| GET | `/api/auth/me` | user | identity + entitlement |
| GET | `/api/statblocks` | full access | list synced stat blocks |
| PUT | `/api/statblocks/{id}` | full access | upsert a stat block |
| DELETE | `/api/statblocks/{id}` | full access | soft-delete (tombstone) |
| POST | `/api/admin/grant` | admin | grant plan/role by email |

## Project layout

```
server/
  app/
    main.py        app factory + CORS + routers
    config.py      env settings
    db.py          SQLAlchemy engine/session
    models.py      User, StatBlock (entitlement model)
    schemas.py     request/response shapes
    auth.py        Supabase JWT verify + entitlement dependencies
    routers/       health, account, statblocks, admin
  scripts/
    grant_access.py   god-mode CLI
  tests/test_smoke.py
```

## Going to production

- Swap `DATABASE_URL` to Supabase Postgres; replace `create_all` with Alembic
  migrations.
- `DEV_AUTH=false`, set `SUPABASE_JWT_SECRET`, lock `CORS_ORIGINS` to your PWA origin.
- Deploy on any container host (Render / Railway / Fly):
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
