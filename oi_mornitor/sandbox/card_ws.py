"""卡片信号 WebSocket / HTTP 接入。"""
from __future__ import annotations

import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from oi_mornitor.config import CARD_WS_ENABLED, CARD_WS_PATH

logger = logging.getLogger("OI_Radar")


def _get_sandbox():
    from oi_mornitor.radar import get_service

    return get_service().sandbox_engine


async def handle_card_ws(request: web.Request) -> web.WebSocketResponse:
    """
    入站协议（JSON text frame）:
      {"text": "...卡片原文...", "id": "BK-1024"}
      {"embed": {...Discord embed...}}
      {"card_id":"SC-1004","symbol":"BTC","side":"SHORT", ...}  # 已规范化
    回执:
      {"ok": true, "card_id": "...", "status": "watching|ordered|filled", ...}
    """
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(request)
    peer = request.remote
    logger.info("卡片 WS 已连接 %s", peer)
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                raw = msg.data
                try:
                    payload: Any = json.loads(raw)
                except json.JSONDecodeError:
                    payload = raw
                try:
                    result = _get_sandbox().ingest_card(payload)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("卡片处理失败")
                    result = {"ok": False, "error": str(exc)}
                await ws.send_json(result)
            elif msg.type == WSMsgType.ERROR:
                logger.warning("卡片 WS 错误 %s", ws.exception())
                break
    finally:
        logger.info("卡片 WS 断开 %s", peer)
    return ws


async def handle_card_ingest(request: web.Request) -> web.Response:
    """HTTP 备用：POST /api/cards 同 WS 载荷。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        text = await request.text()
        body = text
    result = _get_sandbox().ingest_card(body)
    return web.json_response(result, status=200 if result.get("ok") else 400)


def register_card_routes(app: web.Application) -> None:
    if not CARD_WS_ENABLED:
        logger.info("卡片 WS 未启用 (OI_CARD_WS_ENABLED=0)")
        return
    path = CARD_WS_PATH if CARD_WS_PATH.startswith("/") else f"/{CARD_WS_PATH}"
    app.router.add_get(path, handle_card_ws)
    app.router.add_post("/api/cards", handle_card_ingest)
    logger.info("卡片接入已挂载 WS %s · POST /api/cards", path)
