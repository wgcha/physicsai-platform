"""감사 이벤트(§17.6)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.engine import Connection

from ..tables import audit_events


def record(conn: Connection, *, user_id: str, username: str | None, action: str, target_type: str,
           target_id: str | None, detail: dict[str, Any] | None = None, request_id: str | None = None,
           client_ip: str | None = None) -> None:
    conn.execute(
        audit_events.insert().values(
            id=str(uuid.uuid4()), user_id=user_id, username=username, action=action, target_type=target_type,
            target_id=target_id, detail=detail or {}, request_id=request_id, client_ip=client_ip,
        )
    )
