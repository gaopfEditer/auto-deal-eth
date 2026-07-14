"""aiohttp Web 服务：动态雷达 API + React 构建产物 + SSE 推送。"""

from __future__ import annotations



import asyncio

import json

import logging

from pathlib import Path

from typing import Any



from aiohttp import web



from oi_mornitor.config import SCAN_INTERVAL_SEC, WEB_HOST, WEB_PORT

from oi_mornitor.radar import get_service



logger = logging.getLogger("OI_Web")

STATIC_DIST = Path(__file__).resolve().parent / "static" / "dist"





def _json_response(data: Any, status: int = 200) -> web.Response:

    return web.Response(

        text=json.dumps(data, ensure_ascii=False, default=str),

        content_type="application/json",

        status=status,

    )





async def handle_index(_request: web.Request) -> web.FileResponse:

    index = STATIC_DIST / "index.html"

    if not index.exists():

        raise web.HTTPNotFound(

            text="前端未构建。请运行: cd oi_mornitor/frontend && npm install && npm run build"

        )

    return web.FileResponse(index)





async def handle_snapshot(_request: web.Request) -> web.Response:

    snap = get_service().get_snapshot()

    return _json_response(snap)





async def handle_hot(_request: web.Request) -> web.Response:

    snap = get_service().get_snapshot()

    return _json_response({"hot_tickers": snap["hot_tickers"], "scan_ts": snap["scan_ts"]})





async def handle_matrix(_request: web.Request) -> web.Response:

    matrix = await get_service().get_market_matrix()

    return _json_response(matrix)





async def handle_patterns(_request: web.Request) -> web.Response:
    svc = get_service()
    return _json_response(
        svc.pattern_engine.get_payload(
            pool_meta=svc.radar.last_pool_meta,
            fallback_symbols=svc.radar.heavyweight_symbol_list,
        )
    )





async def handle_patterns_watch_post(request: web.Request) -> web.Response:

    try:

        body = await request.json()

    except json.JSONDecodeError:

        return _json_response({"ok": False, "error": "invalid json"}, status=400)

    symbol = str(body.get("symbol", "")).strip().upper()

    if not symbol:

        return _json_response({"ok": False, "error": "symbol required"}, status=400)

    ok = get_service().pattern_engine.add_symbol(symbol)

    if not ok:

        return _json_response({"ok": False, "error": "add failed or watchlist full"}, status=400)

    return _json_response({"ok": True, "watchlist": get_service().pattern_engine.get_watchlist()})





async def handle_patterns_watch_delete(request: web.Request) -> web.Response:

    symbol = request.query.get("symbol", "").strip().upper()

    if not symbol:

        return _json_response({"ok": False, "error": "symbol required"}, status=400)

    ok = get_service().pattern_engine.remove_symbol(symbol)

    return _json_response({"ok": ok, "watchlist": get_service().pattern_engine.get_watchlist()})





async def handle_patterns_random(_request: web.Request) -> web.Response:
    svc = get_service()
    rows = svc.radar.last_all_rows
    fallback = svc.radar.heavyweight_symbol_list
    if not rows and not fallback:
        return _json_response({"ok": False, "error": "雷达池未就绪，请稍后重试"}, status=503)
    picked = svc.pattern_engine.random_pick_heavyweight(rows, fallback_symbols=fallback)
    if not picked:
        return _json_response({"ok": False, "error": "大象池为空"}, status=400)
    return _json_response({
        "ok": True,
        "picked": picked,
        "watchlist": svc.pattern_engine.get_watchlist(),
    })


async def handle_patterns_chart(request: web.Request) -> web.Response:
    symbol = request.query.get("symbol", "").strip().upper()
    if not symbol:
        return _json_response({"ok": False, "error": "symbol required"}, status=400)
    interval = request.query.get("interval", "").strip() or None
    limit_raw = request.query.get("limit", "").strip()
    end_raw = request.query.get("endTime", "").strip()
    limit = int(limit_raw) if limit_raw.isdigit() else None
    end_time = int(end_raw) if end_raw.isdigit() else None
    svc = get_service()
    session = await svc._ensure_session()
    try:
        data = await svc.pattern_engine.get_chart_data(
            session,
            symbol,
            base_url=svc.radar.base_url,
            pool_rows=svc.radar.last_all_rows,
            interval=interval,
            limit=limit,
            end_time=end_time,
        )
    except Exception as exc:
        logger.exception("形态图表拉取失败 %s", symbol)
        return _json_response({"ok": False, "error": str(exc)}, status=500)
    if not data.get("candles"):
        return _json_response({"ok": False, "error": "K线数据为空"}, status=404)
    return _json_response({"ok": True, **data})


async def handle_stream(request: web.Request) -> web.StreamResponse:

    """SSE：推送最新雷达快照。"""

    resp = web.StreamResponse(

        status=200,

        headers={

            "Content-Type": "text/event-stream",

            "Cache-Control": "no-cache",

            "Connection": "keep-alive",

            "Access-Control-Allow-Origin": "*",

        },

    )

    await resp.prepare(request)

    svc = get_service()



    try:

        while True:

            payload = svc.get_snapshot()

            data = json.dumps(payload, ensure_ascii=False, default=str)

            await resp.write(f"data: {data}\n\n".encode())

            await asyncio.sleep(max(5, SCAN_INTERVAL_SEC))

    except (asyncio.CancelledError, ConnectionResetError):

        logger.info("SSE 客户端断开")

    return resp





async def on_startup(app: web.Application) -> None:

    await get_service().start_background(SCAN_INTERVAL_SEC)

    logger.info("雷达后台扫描已挂载到 Web 服务")





async def on_cleanup(app: web.Application) -> None:

    await get_service().stop()

    logger.info("雷达服务已停止")





def create_app() -> web.Application:

    app = web.Application()

    app.router.add_get("/", handle_index)

    app.router.add_get("/patterns", handle_index)

    app.router.add_get("/api/snapshot", handle_snapshot)

    app.router.add_get("/api/hot", handle_hot)

    app.router.add_get("/api/matrix", handle_matrix)

    app.router.add_get("/api/patterns", handle_patterns)

    app.router.add_post("/api/patterns/watch", handle_patterns_watch_post)

    app.router.add_delete("/api/patterns/watch", handle_patterns_watch_delete)

    app.router.add_post("/api/patterns/random", handle_patterns_random)

    app.router.add_get("/api/patterns/chart", handle_patterns_chart)

    app.router.add_get("/api/stream", handle_stream)

    if STATIC_DIST.exists():

        app.router.add_static("/assets", STATIC_DIST / "assets", show_index=False)

    app.on_startup.append(on_startup)

    app.on_cleanup.append(on_cleanup)

    return app





def main() -> None:

    logging.basicConfig(

        level=logging.INFO,

        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",

        datefmt="%Y-%m-%d %H:%M:%S",

    )

    if not STATIC_DIST.exists():

        logger.warning(

            "未找到 %s — 请先构建 React 前端: cd oi_mornitor/frontend && npm install && npm run build",

            STATIC_DIST,

        )

    web.run_app(create_app(), host=WEB_HOST, port=WEB_PORT)





if __name__ == "__main__":

    main()

