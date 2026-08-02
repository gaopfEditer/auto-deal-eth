"""
纯 CDP WebSocket 静默抓取：不附着 Selenium、不 switch_to、不 activate。

通过 Chrome remote debugging 的 browser WebSocket：
  Target.createTarget(background=True) → attach → Page.navigate → Runtime.evaluate
全程不调用 Target.activateTarget / Page.bringToFront。

默认复用同一后台 worker 标签（#cryptopulse-cdp-worker），避免反复建 tab 触发 Dock 抢焦。
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from typing import Any, Generator, Optional
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger("CryptoPulse.CDPRaw")

WORKER_HASH = "cryptopulse-cdp-worker"

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore


class SilentCdpError(RuntimeError):
    pass


def _http_json(url: str, *, timeout: float = 3.0) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def browser_ws_url(port: int) -> str:
    try:
        data = _http_json(f"http://127.0.0.1:{port}/json/version")
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        raise SilentCdpError(f"无法读取 Chrome /json/version: {e}") from e
    ws = str(data.get("webSocketDebuggerUrl") or "").strip()
    if not ws:
        raise SilentCdpError("webSocketDebuggerUrl 为空")
    return ws.replace("localhost", "127.0.0.1")


def list_pages(port: int) -> list[dict[str, Any]]:
    try:
        data = _http_json(f"http://127.0.0.1:{port}/json", timeout=3)
    except Exception as e:
        logger.debug("list /json 失败: %s", e)
        return []
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict) and t.get("type") == "page"]


def _with_worker_hash(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return u
    if WORKER_HASH in u:
        return u
    p = urlparse(u)
    frag = p.fragment or ""
    if frag:
        frag = f"{frag}&{WORKER_HASH}" if WORKER_HASH not in frag else frag
    else:
        frag = WORKER_HASH
    return urlunparse((p.scheme, p.netloc, p.path, p.params, p.query, frag))


def _frontmost_unix_pid() -> Optional[int]:
    if sys.platform != "darwin":
        return None
    try:
        out = subprocess.check_output(
            [
                "osascript",
                "-e",
                'tell application "System Events" to get unix id of first process whose frontmost is true',
            ],
            text=True,
            timeout=2,
            stderr=subprocess.DEVNULL,
        ).strip()
        return int(out) if out.isdigit() else None
    except Exception:
        return None


def _activate_unix_pid(pid: int) -> None:
    if sys.platform != "darwin" or not pid:
        return
    try:
        subprocess.run(
            [
                "osascript",
                "-e",
                f'tell application "System Events" to set frontmost of first process whose unix id is {int(pid)} to true',
            ],
            timeout=2,
            capture_output=True,
            check=False,
        )
    except Exception:
        pass


@contextmanager
def _restore_focus() -> Generator[None, None, None]:
    """建 tab 偶尔仍会闪一下 Dock；结束后把前台还给用户。"""
    prev = _frontmost_unix_pid()
    try:
        yield
    finally:
        if prev is not None:
            time.sleep(0.05)
            _activate_unix_pid(prev)
            time.sleep(0.05)
            _activate_unix_pid(prev)


class SilentCdpBrowser:
    """连 browser 级 CDP；可后台开页并在该页执行 JS。"""

    def __init__(self, port: int, *, timeout: float = 45.0) -> None:
        if websocket is None:
            raise SilentCdpError("缺少 websocket-client：pip install websocket-client")
        self.port = port
        self.timeout = timeout
        self._lock = threading.Lock()
        self._msg_id = 0
        self._ws = websocket.create_connection(
            browser_ws_url(port),
            timeout=timeout,
            suppress_origin=True,
        )
        self._ws.settimeout(timeout)

    def close(self) -> None:
        try:
            self._ws.close()
        except Exception:
            pass

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def call(
        self,
        method: str,
        params: Optional[dict[str, Any]] = None,
        *,
        session_id: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        wait = self.timeout if timeout is None else timeout
        with self._lock:
            mid = self._next_id()
            payload: dict[str, Any] = {
                "id": mid,
                "method": method,
                "params": params or {},
            }
            if session_id:
                payload["sessionId"] = session_id
            self._ws.send(json.dumps(payload))
            deadline = time.time() + wait
            while time.time() < deadline:
                remaining = max(0.05, deadline - time.time())
                try:
                    self._ws.settimeout(remaining)
                    raw = self._ws.recv()
                except Exception as e:
                    raise SilentCdpError(f"CDP recv 超时/失败 ({method}): {e}") from e
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("id") != mid:
                    continue
                if "error" in msg:
                    raise SilentCdpError(f"{method} 失败: {msg['error']}")
                result = msg.get("result")
                return result if isinstance(result, dict) else {}
            raise SilentCdpError(f"CDP 等待 {method} 超时 ({wait}s)")

    def find_worker_target_id(self) -> Optional[str]:
        for t in list_pages(self.port):
            u = str(t.get("url") or "")
            title = str(t.get("title") or "")
            if WORKER_HASH in u or WORKER_HASH in title:
                tid = str(t.get("id") or "").strip()
                if tid:
                    return tid
        return None

    def create_background_page(self, url: str = "about:blank") -> str:
        res = self.call(
            "Target.createTarget",
            {"url": url or "about:blank", "background": True, "newWindow": False},
        )
        tid = str(res.get("targetId") or "")
        if not tid:
            raise SilentCdpError("createTarget 未返回 targetId")
        return tid

    def attach(self, target_id: str) -> str:
        res = self.call(
            "Target.attachToTarget",
            {"targetId": target_id, "flatten": True},
        )
        sid = str(res.get("sessionId") or "")
        if not sid:
            raise SilentCdpError("attachToTarget 未返回 sessionId")
        # 明确禁止抢前台（部分环境默认行为因版本而异）
        try:
            self.call(
                "Target.setAutoAttach",
                {"autoAttach": False, "waitForDebuggerOnStart": False, "flatten": True},
            )
        except Exception:
            pass
        return sid

    def close_target(self, target_id: str) -> None:
        try:
            self.call("Target.closeTarget", {"targetId": target_id}, timeout=8)
        except Exception as e:
            logger.debug("closeTarget 忽略: %s", e)

    def navigate(self, session_id: str, url: str, *, timeout: float = 35.0) -> None:
        try:
            self.call("Page.enable", {}, session_id=session_id, timeout=8)
        except Exception:
            pass
        # 绝不 bringToFront / activateTarget
        self.call(
            "Page.navigate",
            {"url": url},
            session_id=session_id,
            timeout=timeout,
        )
        self.wait_ready(session_id, timeout=timeout)

    def wait_ready(self, session_id: str, *, timeout: float = 35.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                state = self.evaluate(session_id, "document.readyState")
            except Exception:
                time.sleep(0.2)
                continue
            if state in ("interactive", "complete"):
                return
            time.sleep(0.2)
        logger.debug("wait_ready 超时，继续执行")

    def evaluate(
        self, session_id: str, expression: str, *, await_promise: bool = False
    ) -> Any:
        res = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": False,
            },
            session_id=session_id,
        )
        exc = res.get("exceptionDetails")
        if exc:
            desc = (exc.get("exception") or {}).get("description") or exc.get("text") or exc
            raise SilentCdpError(f"JS 异常: {desc}")
        result = res.get("result") or {}
        return result.get("value")

    def evaluate_fn(
        self,
        session_id: str,
        js_function_body: str,
        *args: Any,
        await_promise: bool = False,
    ) -> Any:
        args_json = json.dumps(list(args), ensure_ascii=False)
        if await_promise:
            expr = (
                f"(async function(){{ const arguments = {args_json}; "
                f"{js_function_body} }})()"
            )
        else:
            expr = f"(function(){{ const arguments = {args_json}; {js_function_body} }})()"
        return self.evaluate(session_id, expr, await_promise=await_promise)


@contextmanager
def silent_background_page(
    port: int,
    url: str,
    *,
    wait_sec: float = 4.0,
    page_load_timeout: float = 35.0,
) -> Generator[tuple[SilentCdpBrowser, str], None, None]:
    """
    后台打开/复用 worker 页，yield (browser, session_id)。
    默认不关标签（复用，减少抢焦）；CRYPTO_PULSE_CDP_CLOSE_TAB=1 时关闭。
    """
    close_tab = os_env_truthy("CRYPTO_PULSE_CDP_CLOSE_TAB", default=False)
    target_url = _with_worker_hash(url)
    browser = SilentCdpBrowser(port, timeout=max(page_load_timeout + 10, 45))
    tid = ""
    created = False
    try:
        with _restore_focus():
            tid = browser.find_worker_target_id() or ""
            if tid:
                logger.info("[cdp-raw] 复用后台 worker 标签（不抢焦点）")
            else:
                tid = browser.create_background_page("about:blank")
                created = True
                logger.info("[cdp-raw] 后台新建 worker 标签（background=true）")
            sid = browser.attach(tid)
            browser.navigate(sid, target_url, timeout=page_load_timeout)
            if wait_sec > 0:
                time.sleep(wait_sec)
        # 导航结束后再还一次焦点（navigate 偶发异步抢焦）
        prev = _frontmost_unix_pid()
        yield browser, sid
        if prev is not None:
            _activate_unix_pid(prev)
    finally:
        if close_tab and tid and created:
            browser.close_target(tid)
        elif close_tab and tid:
            browser.close_target(tid)
        browser.close()


def os_env_truthy(name: str, *, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")
