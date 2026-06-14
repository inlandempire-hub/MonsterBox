"""Database models.

The entitlement model lives entirely in OUR database (not the auth provider),
so god accounts and free comp accounts are just a column you set:

  role  : "user" | "admin"          admin = god account (full access + can grant)
  plan  : "free" | "pro" | "comp"   comp  = free full access for chosen people

has_full_access == admin OR pro OR comp. Everything paywalled checks that.
"""
import datetime
import secrets

from sqlalchemy import Boolean, DateTime, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# Human-friendly public account id (e.g. "MB-7Q3K2P"). No 0/O/1/I/L so it can't
# be misread when someone reads it aloud or copies it to be granted comp access.
_ID_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def generate_public_id() -> str:
    return "MB-" + "".join(secrets.choice(_ID_ALPHABET) for _ in range(6))


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The Supabase user id (JWT "sub"). Null until the user first signs in — lets
    # us pre-grant access by email before someone has even created their account.
    supabase_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)

    # Short shareable id so people can be granted comp by code, not email.
    public_id: Mapped[str | None] = mapped_column(String, unique=True, index=True, nullable=True)

    plan: Mapped[str] = mapped_column(String, default="free")   # free | pro | comp
    role: Mapped[str] = mapped_column(String, default="user")   # user | admin

    # Forward-compat for the Stripe phase (P1 part 4) — unused for now.
    stripe_customer_id: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    @property
    def has_full_access(self) -> bool:
        return self.role == "admin" or self.plan in ("pro", "comp")


class StatBlock(Base):
    """A user's synced stat block. The full client JSON is stored verbatim in
    `data`; `client_id` is the id the browser generated, unique per user."""
    __tablename__ = "statblocks"
    __table_args__ = (UniqueConstraint("user_id", "client_id", name="uq_statblock_user_client"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    client_id: Mapped[str] = mapped_column(String, index=True)
    name: Mapped[str] = mapped_column(String, default="")
    data: Mapped[dict] = mapped_column(JSON)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
