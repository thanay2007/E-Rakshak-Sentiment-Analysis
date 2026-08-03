"""WebSocket /ws/live — real-time feed items + alerts pushed by ingestion.

Two gates before a socket joins the broadcast pool:

  1. Origin. Browsers do not apply the same-origin policy to WebSockets and do
     not preflight them, so CORS middleware never sees this handshake. Without
     an explicit check, any website an officer has open could connect and read
     the live threat stream — cross-site WebSocket hijacking. Non-browser
     clients (no Origin header) are allowed through; they are not the ones the
     same-origin policy would have protected anyway.

  2. Identity. The token arrives in the first frame rather than the query
     string: query strings land in access logs, proxy logs and browser history,
     and a session token in a log file is a session token in an incident report.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status

from app.config import settings
from app.database import session_scope
from app.security.deps import authenticate
from app.services.websocket_manager import manager

log = logging.getLogger("sentinel.ws")
router = APIRouter()

_AUTH_TIMEOUT_SECONDS = 10


def _origin_allowed(origin: str) -> bool:
    if not origin:
        return True          # non-browser client
    return origin.rstrip("/") in {o.rstrip("/") for o in settings.CORS_ORIGINS}


@router.websocket("/ws/live")
async def live(ws: WebSocket) -> None:
    if not _origin_allowed(ws.headers.get("origin", "")):
        # Rejected before accept(), so the handshake itself fails.
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws.accept()

    # First frame must be {"type": "auth", "token": "..."}.
    try:
        raw = await asyncio.wait_for(ws.receive_json(), timeout=_AUTH_TIMEOUT_SECONDS)
    except (asyncio.TimeoutError, WebSocketDisconnect, ValueError, TypeError):
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    token = (raw or {}).get("token", "") if isinstance(raw, dict) else ""
    if not token:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        with session_scope() as session:
            user = authenticate(token, session)
            username, must_change = user.username, user.must_change_password
    except HTTPException:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if must_change:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.register(ws)
    await ws.send_json({"type": "auth_ok", "user": username})
    log.info("ws connected user=%s", username)

    try:
        while True:
            await ws.receive_text()  # keepalive pings from the client
    except WebSocketDisconnect:
        await manager.disconnect(ws)
    except Exception:
        await manager.disconnect(ws)
