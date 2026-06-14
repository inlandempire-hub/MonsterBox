"""Pydantic request/response models."""
import datetime
from typing import Any

from pydantic import BaseModel


class AccountOut(BaseModel):
    email: str
    plan: str
    role: str
    has_full_access: bool
    account_id: str | None = None      # the shareable public id (MB-XXXXXX)


class StatBlockIn(BaseModel):
    id: str                       # the client-generated id
    name: str | None = None
    data: dict[str, Any]


class StatBlockOut(BaseModel):
    id: str
    name: str
    data: dict
    updated_at: datetime.datetime


class GrantIn(BaseModel):
    email: str | None = None          # grant by email (can pre-create before signup)
    account_id: str | None = None     # ...or by the public account id (MB-XXXXXX)
    plan: str | None = None           # free | pro | comp
    role: str | None = None           # user | admin
