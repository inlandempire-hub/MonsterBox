"""Pydantic request/response models."""
import datetime
from typing import Any

from pydantic import BaseModel


class AccountOut(BaseModel):
    email: str
    plan: str
    role: str
    has_full_access: bool


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
    email: str
    plan: str | None = None       # free | pro | comp
    role: str | None = None       # user | admin
