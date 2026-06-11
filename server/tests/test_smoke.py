"""Smoke tests: health, dev auth, entitlement gating, and admin grant flow.

Uses a throwaway SQLite DB and DEV_AUTH so no Supabase project is needed.
"""
import os

os.environ["DEV_AUTH"] = "true"
os.environ["DATABASE_URL"] = "sqlite:///./test_smoke.db"

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

client = TestClient(app)


def setup_module(_):
    # fresh schema for the test run
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_free_user_is_blocked_from_pro_features():
    h = {"X-Dev-User": "free@test.com"}
    me = client.get("/api/auth/me", headers=h).json()
    assert me["plan"] == "free" and me["has_full_access"] is False
    # cloud sync (Pro) is gated -> 402
    assert client.get("/api/statblocks", headers=h).status_code == 402


def test_comp_account_gets_full_access():
    # pre-grant comp access by email (as the founder would), then "log in"
    db = SessionLocal()
    db.add(User(email="comp@test.com", plan="comp"))
    db.commit()
    db.close()
    h = {"X-Dev-User": "comp@test.com"}
    assert client.get("/api/auth/me", headers=h).json()["has_full_access"] is True
    # sync works now
    sb = {"id": "abc123", "name": "Goblin", "data": {"name": "Goblin", "armor_class": 15}}
    assert client.put("/api/statblocks/abc123", json=sb, headers=h).status_code == 200
    listed = client.get("/api/statblocks", headers=h).json()
    assert len(listed) == 1 and listed[0]["name"] == "Goblin"


def test_admin_can_grant_and_god_account_has_full_access():
    db = SessionLocal()
    db.add(User(email="god@test.com", role="admin"))
    db.commit()
    db.close()
    god = {"X-Dev-User": "god@test.com"}
    assert client.get("/api/auth/me", headers=god).json()["has_full_access"] is True
    # admin grants comp to a new email via the API
    r = client.post("/api/admin/grant", json={"email": "newfriend@test.com", "plan": "comp"}, headers=god)
    assert r.status_code == 200 and r.json()["has_full_access"] is True
    # a non-admin cannot grant
    assert client.post("/api/admin/grant", json={"email": "x@test.com", "plan": "comp"},
                       headers={"X-Dev-User": "free@test.com"}).status_code == 403
