"""Small typed contracts shared by core services."""

from __future__ import annotations

from datetime import datetime
from typing import TypedDict


class SessionPayload(TypedDict):
    uid: int
    sid: str
    iat: int
    jti: str


class RingLogEntry(TypedDict):
    seq: int
    level: str
    text: str
    created_at: str


class RingScopeEntry(RingLogEntry):
    byte_size: int


class PushSendResult(TypedDict, total=False):
    sent: bool
    channel: str
    reason: str
    error: str
    response: str
    http_status: int


class PushConfigData(TypedDict):
    channel: str
    config: dict[str, str]
    title_template: str
    body_template: str
    updated_at: datetime | None
