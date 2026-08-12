"""
纯 CDP WebSocket 静默操作：不 Selenium switch_to、不 activateTarget、不 bringToFront。

供 binance/cdp_navigation.py 使用；与 news_mornitor/fetchers/cdp_raw.py 同思路。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional
from urllib.parse import urlparse, urlunparse

WORKER_HASH = "auto-deal-cdp-worker"

try:
    import websocket  # websocket-client
except ImportError:  # pragma: no cover
    websocket = None  # type: ignore


class SilentCdpError(RuntimeError):
    pass


def debug_port() -> int:
    try:
        from config import CHROME_DEBUG_PORT

        return int(CHROME_DEBUG_PORT)
    except Exception:
        try:
            return int(os.getenv("CHROME_DEBUG_PORT", "9222"))
        except Exception:
            return 9222


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
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict) and t.get("type") == "page"]


def with_worker_hash(url: str) -> str:
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


def frontmost_unix_pid() -> Optional[int]:
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


def activate_unix_pid(pid: int) -> None:
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


class SilentCdpBrowser:
    """连 browser 级 CDP；后台开页并在该页执行 JS / 派发输入。"""

    def __init__(self, port: int | None = None, *, timeout: float = 45.0) -> None:
        if websocket is None:
            raise SilentCdpError("缺少 websocket-client：pip install websocket-client")
        self.port = int(port if port is not None else debug_port())
        self.timeout = timeout
        self._lock = threading.Lock()
        self._msg_id = 0
        self._ws = websocket.create_connection(
            browser_ws_url(self.port),
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
        try:
            self.call(
                "Target.setAutoAttach",
                {
                    "autoAttach": False,
                    "waitForDebuggerOnStart": False,
                    "flatten": True,
                },
            )
        except Exception:
            pass
        return sid

    def close_target(self, target_id: str) -> None:
        try:
            self.call("Target.closeTarget", {"targetId": target_id}, timeout=8)
        except Exception:
            pass

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
        parts: list[str] = []
        for a in args:
            if isinstance(a, SilentWebElement):
                parts.append(f"({a.resolve_js})")
            else:
                parts.append(json.dumps(a, ensure_ascii=False))
        args_js = "[" + ",".join(parts) + "]"
        if await_promise:
            expr = (
                f"(async function(){{ const arguments = {args_js}; "
                f"{js_function_body} }})()"
            )
        else:
            expr = f"(function(){{ const arguments = {args_js}; {js_function_body} }})()"
        return self.evaluate(session_id, expr, await_promise=await_promise)

    def click_at(
        self,
        session_id: str,
        x: float,
        y: float,
        *,
        background_tab: bool = False,
    ) -> None:
        try:
            self.call("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": x,
                "y": y,
                "button": "none",
                "buttons": 0,
            }, session_id=session_id, timeout=8)
        except Exception:
            pass
        mods = 0
        # 2 = Ctrl (Win), macOS Chrome 用 meta；CDP modifiers: Alt=1, Ctrl=2, Meta=4, Shift=8
        if background_tab:
            mods = 4 if sys.platform == "darwin" else 2
        for typ in ("mousePressed", "mouseReleased"):
            self.call(
                "Input.dispatchMouseEvent",
                {
                    "type": typ,
                    "x": x,
                    "y": y,
                    "button": "left",
                    "buttons": 1 if typ == "mousePressed" else 0,
                    "clickCount": 1,
                    "modifiers": mods,
                },
                session_id=session_id,
                timeout=8,
            )


class SilentWebElement:
    """仅用于静默 CDP 绑定下的 find_element 结果；可交给 execute_script / 坐标点击。"""

    def __init__(self, resolve_js: str, *, binding: "SilentDriverBinding") -> None:
        self.resolve_js = resolve_js
        self._binding = binding
        self.id = f"silent-{abs(hash(resolve_js)) & 0xFFFFFFFF:08x}"

    @property
    def rect(self) -> dict[str, float]:
        box = self._binding.evaluate_fn(
            """
const el = arguments[0];
if (!el || !el.getBoundingClientRect) return {x:0,y:0,width:0,height:0};
const r = el.getBoundingClientRect();
return {x:r.x, y:r.y, width:r.width, height:r.height};
""",
            self,
        )
        if not isinstance(box, dict):
            return {"x": 0, "y": 0, "width": 0, "height": 0}
        return {
            "x": float(box.get("x") or 0),
            "y": float(box.get("y") or 0),
            "width": float(box.get("width") or 0),
            "height": float(box.get("height") or 0),
        }

    def is_displayed(self) -> bool:
        try:
            return bool(
                self._binding.evaluate_fn(
                    """
const el = arguments[0];
if (!el) return false;
const st = window.getComputedStyle(el);
if (st && (st.visibility === 'hidden' || st.display === 'none')) return false;
const r = el.getBoundingClientRect();
return r.width > 0 && r.height > 0;
""",
                    self,
                )
            )
        except Exception:
            return False

    def is_enabled(self) -> bool:
        try:
            return bool(
                self._binding.evaluate_fn(
                    "const el = arguments[0]; return !!(el && !el.disabled);",
                    self,
                )
            )
        except Exception:
            return True

    def click(self) -> None:
        self._binding.evaluate_fn(
            "const el = arguments[0]; if (el) el.click();",
            self,
        )

    def send_keys(self, *value: str) -> None:
        text = "".join(str(v) for v in value)
        self._binding.evaluate_fn(
            """
const el = arguments[0];
const t = String(arguments[1] || '');
if (!el) return;
el.focus && el.focus();
if ('value' in el) {
  el.value = (el.value || '') + t;
  el.dispatchEvent(new Event('input', {bubbles:true}));
}
""",
            self,
            text,
        )


class SilentDriverBinding:
    """把 Selenium driver 的脚本/查找/导航接到静默 CDP session，禁止 switch_to 抢焦。"""

    def __init__(
        self,
        driver: Any,
        browser: SilentCdpBrowser,
        *,
        session_id: str,
        target_id: str,
    ) -> None:
        self.driver = driver
        self.browser = browser
        self.session_id = session_id
        self.target_id = target_id
        self.worker_target_id = target_id  # 持久 worker；详情页会临时 reattach 到其它 target
        self._orig_execute = driver.execute
        self._orig_execute_script = getattr(driver, "execute_script", None)
        self._orig_get = getattr(driver, "get", None)
        self._orig_back = getattr(driver, "back", None)
        self._installed = False

    def evaluate(self, expression: str, *, await_promise: bool = False) -> Any:
        return self.browser.evaluate(
            self.session_id, expression, await_promise=await_promise
        )

    def evaluate_fn(self, body: str, *args: Any, await_promise: bool = False) -> Any:
        return self.browser.evaluate_fn(
            self.session_id, body, *args, await_promise=await_promise
        )

    def navigate(self, url: str, *, timeout: float = 35.0) -> None:
        self.browser.navigate(self.session_id, url, timeout=timeout)

    def current_url(self) -> str:
        try:
            return str(self.evaluate("location.href") or "")
        except Exception:
            return ""

    def reattach(self, target_id: str) -> None:
        self.target_id = target_id
        self.session_id = self.browser.attach(target_id)

    def install(self) -> None:
        if self._installed:
            return
        binding = self
        from selenium.webdriver.common.by import By
        from selenium.common.exceptions import NoSuchElementException
        from selenium.webdriver.remote.command import Command

        def _resolve_js(by: str, value: str, *, many: bool = False, index: int = 0) -> str:
            by_u = (by or "").upper()
            if by_u.endswith("CSS_SELECTOR") or by == By.CSS_SELECTOR:
                if many:
                    return (
                        f'(function(){{const n=document.querySelectorAll({json.dumps(value)});'
                        f"return n[{index}]||null;}})()"
                    )
                return f"document.querySelector({json.dumps(value)})"
            if by_u.endswith("TAG_NAME") or by == By.TAG_NAME:
                if many:
                    return (
                        f'(function(){{const n=document.getElementsByTagName({json.dumps(value)});'
                        f"return n[{index}]||null;}})()"
                    )
                return f"document.getElementsByTagName({json.dumps(value)})[0]"
            if by_u.endswith("XPATH") or by == By.XPATH:
                if many:
                    return (
                        f'(function(){{const r=document.evaluate({json.dumps(value)},document,null,'
                        f"XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);"
                        f"return r.snapshotItem({index});}})()"
                    )
                return (
                    f"document.evaluate({json.dumps(value)},document,null,"
                    f"XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue"
                )
            # 兜底：当 CSS 用
            return f"document.querySelector({json.dumps(value)})"

        def execute(driver_command: Any, params: Any = None):  # noqa: ANN001
            params = params or {}
            # W3C / 旧命令名兼容
            name = str(driver_command)

            if driver_command in (Command.NEW_WINDOW,) or name.endswith("newWindow"):
                # 禁止 Selenium 新开窗抢焦
                raise SilentCdpError("静默模式禁止 driver 新开窗；请用 CDP background createTarget")

            if driver_command in (
                Command.SWITCH_TO_WINDOW,
                getattr(Command, "W3C_SWITCH_TO_WINDOW", "switchToWindow"),
            ) or "switchToWindow" in name or name == "switchToWindow":
                handle = str((params or {}).get("handle") or "")
                page_ids = {
                    str(p.get("id") or "") for p in list_pages(binding.browser.port)
                }
                if handle and handle in page_ids:
                    try:
                        binding.reattach(handle)
                    except Exception:
                        if binding.worker_target_id:
                            try:
                                binding.reattach(binding.worker_target_id)
                            except Exception:
                                pass
                elif binding.worker_target_id:
                    # Selenium 句柄常是用户前台 tab：静默模式下改回 worker，绝不 activate
                    try:
                        binding.reattach(binding.worker_target_id)
                    except Exception:
                        pass
                return {"value": None}

            if driver_command in (Command.GET,):
                url = str((params or {}).get("url") or "")
                binding.navigate(url, timeout=40)
                return {"value": None}

            if driver_command in (Command.GET_CURRENT_URL,):
                return {"value": binding.current_url()}

            if driver_command in (Command.GET_TITLE,):
                try:
                    return {"value": str(binding.evaluate("document.title") or "")}
                except Exception:
                    return {"value": ""}

            if driver_command in (Command.GO_BACK,):
                binding.evaluate("window.history.back()")
                time.sleep(0.35)
                binding.browser.wait_ready(binding.session_id, timeout=20)
                return {"value": None}

            if driver_command in (Command.REFRESH,):
                binding.evaluate("location.reload()")
                binding.browser.wait_ready(binding.session_id, timeout=40)
                return {"value": None}

            if driver_command in (
                Command.W3C_EXECUTE_SCRIPT,
                Command.EXECUTE_SCRIPT,
            ):
                script = str((params or {}).get("script") or "")
                args = list((params or {}).get("args") or [])
                # Selenium 可能把 SilentWebElement 序列化坏了；绑定层走 evaluate_fn
                # 若 args 里是 dict element-6066... 则无法还原，调用方应直接传 SilentWebElement
                real_args: list[Any] = []
                for a in args:
                    if isinstance(a, SilentWebElement):
                        real_args.append(a)
                    elif isinstance(a, dict) and (
                        "element-6066-11e4-a52e-4f735466cecf" in a or "ELEMENT" in a
                    ):
                        # 已序列化的假元素：无法映射，跳过
                        real_args.append(None)
                    else:
                        real_args.append(a)
                val = binding.evaluate_fn(script, *real_args)
                return {"value": val}

            if driver_command in (
                Command.FIND_ELEMENT,
                getattr(Command, "W3C_FIND_ELEMENT", "findElement"),
            ) or name in ("findElement",):
                using = str((params or {}).get("using") or "")
                value = str((params or {}).get("value") or "")
                # using: css selector / xpath / tag name
                by_map = {
                    "css selector": By.CSS_SELECTOR,
                    "xpath": By.XPATH,
                    "tag name": By.TAG_NAME,
                }
                by = by_map.get(using, using)
                js = _resolve_js(by, value, many=False)
                exists = binding.evaluate(f"!!({js})")
                if not exists:
                    raise NoSuchElementException(f"silent: no element {using}={value}")
                el = SilentWebElement(js, binding=binding)
                return {"value": el}

            if driver_command in (
                Command.FIND_ELEMENTS,
                getattr(Command, "W3C_FIND_ELEMENTS", "findElements"),
            ) or name in ("findElements",):
                using = str((params or {}).get("using") or "")
                value = str((params or {}).get("value") or "")
                by_map = {
                    "css selector": By.CSS_SELECTOR,
                    "xpath": By.XPATH,
                    "tag name": By.TAG_NAME,
                }
                by = by_map.get(using, using)
                if by == By.CSS_SELECTOR or using == "css selector":
                    n = int(
                        binding.evaluate(
                            f"document.querySelectorAll({json.dumps(value)}).length"
                        )
                        or 0
                    )
                elif by == By.TAG_NAME or using == "tag name":
                    n = int(
                        binding.evaluate(
                            f"document.getElementsByTagName({json.dumps(value)}).length"
                        )
                        or 0
                    )
                elif by == By.XPATH or using == "xpath":
                    n = int(
                        binding.evaluate(
                            f"(function(){{const r=document.evaluate({json.dumps(value)},"
                            f"document,null,XPathResult.ORDERED_NODE_SNAPSHOT_TYPE,null);"
                            f"return r.snapshotLength;}})()"
                        )
                        or 0
                    )
                else:
                    n = 0
                out = [
                    SilentWebElement(
                        _resolve_js(by, value, many=True, index=i), binding=binding
                    )
                    for i in range(n)
                ]
                return {"value": out}

            if driver_command in (Command.CLOSE,):
                closing = binding.target_id
                binding.browser.close_target(closing)
                if (
                    binding.worker_target_id
                    and closing != binding.worker_target_id
                ):
                    try:
                        binding.reattach(binding.worker_target_id)
                    except Exception:
                        pass
                return {"value": None}

            if driver_command in (
                Command.W3C_GET_CURRENT_WINDOW_HANDLE,
                Command.CURRENT_WINDOW_HANDLE,
            ):
                return {"value": binding.target_id}

            # 其余命令仍走原 Selenium（可能抢焦）——尽量少触发
            return binding._orig_execute(driver_command, params)

        # execute_script 走 driver.execute；但 arguments 里的 SilentWebElement
        # 会被 RemoteConnection 序列化丢掉。覆盖实例方法，直达 CDP。
        def execute_script(script: str, *args: Any) -> Any:
            return binding.evaluate_fn(script, *args)

        def get(url: str) -> None:
            binding.navigate(url, timeout=40)

        def back() -> None:
            binding.evaluate("window.history.back()")
            time.sleep(0.35)
            binding.browser.wait_ready(binding.session_id, timeout=20)

        self.driver.execute = execute  # type: ignore[method-assign]
        self.driver.execute_script = execute_script  # type: ignore[method-assign]
        self.driver.get = get  # type: ignore[method-assign]
        self.driver.back = back  # type: ignore[method-assign]
        self._installed = True

    def uninstall(self) -> None:
        if not self._installed:
            return
        try:
            self.driver.execute = self._orig_execute  # type: ignore[method-assign]
        except Exception:
            pass
        if self._orig_execute_script is not None:
            try:
                self.driver.execute_script = self._orig_execute_script  # type: ignore[method-assign]
            except Exception:
                pass
        if self._orig_get is not None:
            try:
                self.driver.get = self._orig_get  # type: ignore[method-assign]
            except Exception:
                pass
        if self._orig_back is not None:
            try:
                self.driver.back = self._orig_back  # type: ignore[method-assign]
            except Exception:
                pass
        self._installed = False

    def click_element(
        self,
        el: SilentWebElement,
        *,
        dx: float = 0,
        dy: float = 0,
        background_tab: bool = False,
    ) -> bool:
        self.evaluate_fn(
            "const el = arguments[0]; if (el) el.scrollIntoView({block:'center',inline:'center'});",
            el,
        )
        time.sleep(0.12)
        rect = el.rect
        w, h = float(rect.get("width") or 0), float(rect.get("height") or 0)
        if w < 6 or h < 6:
            return False
        x = float(rect.get("x") or 0) + w / 2 + dx
        y = float(rect.get("y") or 0) + h / 2 + dy
        self.browser.click_at(
            self.session_id, x, y, background_tab=background_tab
        )
        return True


# driver id → binding
_ACTIVE_BINDINGS: dict[int, SilentDriverBinding] = {}


def get_binding(driver: Any) -> Optional[SilentDriverBinding]:
    return _ACTIVE_BINDINGS.get(id(driver))


def set_binding(driver: Any, binding: Optional[SilentDriverBinding]) -> None:
    key = id(driver)
    old = _ACTIVE_BINDINGS.pop(key, None)
    if old is not None and old is not binding:
        try:
            old.uninstall()
        except Exception:
            pass
    if binding is None:
        return
    _ACTIVE_BINDINGS[key] = binding
    binding.install()
