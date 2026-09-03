"""
CDP 远程调试下的标签页导航：真正静默、不抢焦点。

默认策略：
  1. 纯 WebSocket CDP：Target.createTarget(background=True) 开专用 worker
  2. attach + Page.navigate + Runtime.evaluate（绝不 Target.activateTarget / switch_to）
  3. 把 Selenium driver 的 get / execute_script / find_* 绑到该 worker
  4. restore 时只卸绑定，不 switch_to 用户标签（避免 Chrome 抢前台）

旧路径（Selenium switch_to）已废弃：那会「切到 Chrome 再 osascript 切回」，正是抢焦来源。

环境变量：
  CDP_NAV_SAME_TAB=1          仅在当前标签导航（旧行为，会抢焦点）
  CDP_SILENT=0                关闭静默，回退 Selenium new_window（会抢焦）
  CDP_PERSISTENT_WORKER=0     关闭「单 worker 复用」
  CDP_CLOSE_WORKER=1          restore 时关闭 worker
  CDP_PRESERVE_FOCUS=1        仅在「创建新 worker」后轻量还焦（默认关，避免来回切）
"""
from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator, Optional
from urllib.parse import parse_qs, unquote, urlparse

from selenium.common.exceptions import WebDriverException

from binance.cdp_silent import (
    SilentCdpBrowser,
    SilentCdpError,
    SilentDriverBinding,
    activate_unix_pid,
    debug_port,
    frontmost_unix_pid,
    get_binding,
    set_binding,
    with_worker_hash,
)

# driver 对象 id → 持久 worker（同一次 Chrome 附着会话内复用）
_PERSISTENT_WORKERS: dict[int, dict[str, Any]] = {}
# driver id → 复用的 SilentCdpBrowser（保持 WS 连接）
_PERSISTENT_BROWSERS: dict[int, SilentCdpBrowser] = {}


@dataclass
class CdpNavSession:
    """一次 cdp_goto 的上下文，供 cdp_restore 还原。"""

    main_handle: Optional[str]
    worker_handle: Optional[str]
    opened_new_tab: bool
    reused_tab: bool
    target_id: Optional[str] = None
    keep_worker: bool = True
    binding: Optional[SilentDriverBinding] = None


def _log(msg: str, *, prefix: str = "CDP") -> None:
    print(f"[INFO] {prefix} {msg}", file=sys.stderr, flush=True)


def _warn(msg: str, *, prefix: str = "CDP") -> None:
    print(f"[WARN] {prefix} {msg}", file=sys.stderr, flush=True)


def _normalize_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    p = urlparse(u)
    path = (p.path or "/").rstrip("/") or "/"
    return f"{(p.scheme or 'https').lower()}://{(p.netloc or '').lower()}{path}"


def _url_match_key(url: str) -> str:
    norm = _normalize_url(url)
    if not norm:
        return ""
    p = urlparse(url.strip())
    host = (p.netloc or "").lower()
    path = (p.path or "").lower()
    qs = parse_qs(p.query, keep_blank_values=False)

    if "tradingview.com" in host:
        sym = unquote((qs.get("symbol") or [""])[0]).upper()
        interval = (qs.get("interval") or [""])[0]
        return f"tv|{sym}|{interval}"

    if "binance.com" in host and "/trade/" in path:
        parts = [x for x in path.split("/") if x]
        for i, seg in enumerate(parts):
            if seg == "trade" and i + 1 < len(parts):
                return f"bn-trade|{parts[i + 1].upper()}"
        return f"bn-trade|{path}"

    return norm


def _urls_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    ka, kb = _url_match_key(a), _url_match_key(b)
    if ka and kb and ka == kb:
        return True
    return _normalize_url(a) == _normalize_url(b)


def _safe_current_handle(driver) -> Optional[str]:
    try:
        return driver.current_window_handle
    except WebDriverException:
        return None


def _same_tab_mode() -> bool:
    v = os.getenv("CDP_NAV_SAME_TAB", "") or os.getenv("DEALMSG_TV_SAME_TAB", "")
    return v.strip().lower() in ("1", "true", "yes")


def _silent_mode() -> bool:
    v = os.getenv("CDP_SILENT", "1")
    return v.strip().lower() not in ("0", "false", "no")


def _persistent_worker_mode() -> bool:
    v = os.getenv("CDP_PERSISTENT_WORKER", "1")
    return v.strip().lower() not in ("0", "false", "no")


def _close_worker_on_restore() -> bool:
    v = os.getenv("CDP_CLOSE_WORKER", "0")
    return v.strip().lower() in ("1", "true", "yes")


def _preserve_focus_enabled() -> bool:
    # 默认关闭：真正静默后不应再 osascript 来回切
    v = os.getenv("CDP_PRESERVE_FOCUS", "0")
    return v.strip().lower() in ("1", "true", "yes")


@contextmanager
def preserve_os_focus() -> Generator[None, None, None]:
    """仅在显式开启时还焦；真正静默路径默认不走这里。"""
    if not _preserve_focus_enabled() or sys.platform != "darwin":
        yield
        return
    prev = frontmost_unix_pid()
    try:
        yield
    finally:
        if prev is not None:
            time.sleep(0.05)
            activate_unix_pid(prev)


def _driver_key(driver) -> int:
    return id(driver)


def _parse_debug_port(raw: Any) -> Optional[int]:
    s = str(raw or "").strip()
    if not s:
        return None
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0]
    if s.isdigit():
        port = int(s)
        return port if 1 <= port <= 65535 else None
    if ":" in s:
        tail = s.rsplit(":", 1)[-1]
        if tail.isdigit():
            port = int(tail)
            return port if 1 <= port <= 65535 else None
    return None


def _driver_debug_port(driver) -> int:
    """静默 CDP 必须跟 Selenium debuggerAddress 同一端口，不能用全局 CHROME_DEBUG_PORT。"""
    candidates: list[Any] = [
        getattr(driver, "_cdp_debugger_url", None),
        getattr(driver, "_cdp_debug_port", None),
    ]
    opts = getattr(driver, "options", None)
    if opts is not None:
        exp = getattr(opts, "experimental_options", None) or {}
        if isinstance(exp, dict):
            candidates.append(exp.get("debuggerAddress"))
    caps = getattr(driver, "capabilities", None) or {}
    if isinstance(caps, dict):
        for key in ("goog:chromeOptions", "chromeOptions"):
            goog = caps.get(key) or {}
            if isinstance(goog, dict):
                candidates.append(goog.get("debuggerAddress"))
    for raw in candidates:
        port = _parse_debug_port(raw)
        if port:
            return port
    return debug_port()


def clear_persistent_worker(driver) -> None:
    """手动清掉该 driver 的持久 worker 记录（不关标签）。"""
    key = _driver_key(driver)
    _PERSISTENT_WORKERS.pop(key, None)
    browser = _PERSISTENT_BROWSERS.pop(key, None)
    if browser:
        try:
            browser.close()
        except Exception:
            pass


def _get_or_create_browser(driver, *, timeout: float) -> SilentCdpBrowser:
    key = _driver_key(driver)
    port = _driver_debug_port(driver)
    browser = _PERSISTENT_BROWSERS.get(key)
    if browser is not None:
        if int(getattr(browser, "port", -1) or -1) == port:
            return browser
        _warn(
            f"静默 CDP 端口变更 {getattr(browser, 'port', '?')} → {port}，重建连接"
        )
        try:
            browser.close()
        except Exception:
            pass
        _PERSISTENT_BROWSERS.pop(key, None)
    browser = SilentCdpBrowser(port, timeout=timeout)
    _PERSISTENT_BROWSERS[key] = browser
    _log(f"静默 CDP WebSocket 127.0.0.1:{port}")
    return browser


def _resolve_selenium_last_target_id(driver, port: int) -> Optional[str]:
    """用 Selenium window_handles[-1] 对齐「最后一个页签」，再映射到 CDP targetId。"""
    from binance.cdp_silent import list_pages

    try:
        handles = list(driver.window_handles or [])
    except Exception:
        handles = []
    if not handles:
        return None
    cand = str(handles[-1] or "").strip()
    if not cand:
        return None
    pages = list_pages(port)
    ids = {str(p.get("id") or "") for p in pages}
    if cand in ids:
        return cand
    raw = cand[9:] if cand.startswith("CDwindow-") else cand
    if raw in ids:
        return raw
    for p in pages:
        pid = str(p.get("id") or "")
        if pid and (pid in cand or cand in pid):
            return pid
    return None


def _ensure_silent_worker(
    driver,
    url: str,
    *,
    page_load_timeout: int,
    log_prefix: str,
    persistent: bool,
    last_tab: bool = False,
) -> CdpNavSession:
    """纯 CDP 建/复用 worker 并导航；绑定 driver；不 switch_to。

    last_tab=True：强制附着「最后一个可用页签」（Gemini/TTI），
    不用旧的持久 worker，也不给 URL 强加 worker hash。
    """
    main_handle = _safe_current_handle(driver)
    keep = not _close_worker_on_restore()
    browser = _get_or_create_browser(
        driver, timeout=float(max(page_load_timeout + 15, 45))
    )
    key = _driver_key(driver)
    created = False
    tid: Optional[str] = None

    if last_tab:
        from binance.cdp_silent import pick_last_usable_page

        tid = _resolve_selenium_last_target_id(driver, browser.port)
        if tid:
            prev_url = ""
            try:
                from binance.cdp_silent import list_pages

                for p in list_pages(browser.port):
                    if str(p.get("id") or "") == tid:
                        prev_url = str(p.get("url") or "")
                        break
            except Exception:
                pass
            _log(
                f"last_tab 附着 Selenium 末页签 {tid[:16]}…（当前: {prev_url[:80] or '空'}）",
                prefix=log_prefix,
            )
        else:
            last = pick_last_usable_page(browser.port)
            if last:
                tid = str(last.get("id") or "") or None
                prev_url = str(last.get("url") or "")
                _log(
                    f"last_tab 附着 /json 末可用页 {tid and tid[:16]}…（当前: {prev_url[:80] or '空'}）",
                    prefix=log_prefix,
                )
        if not tid:
            prev = frontmost_unix_pid() if _preserve_focus_enabled() else None
            tid = browser.create_background_page("about:blank")
            created = True
            _log("last_tab 无可用页签，后台新建一次", prefix=log_prefix)
            if prev is not None:
                time.sleep(0.05)
                activate_unix_pid(prev)
    else:
        if persistent:
            entry = _PERSISTENT_WORKERS.get(key)
            if entry and entry.get("target_id"):
                tid = str(entry["target_id"])
                from binance.cdp_silent import list_pages

                pages = {str(p.get("id") or "") for p in list_pages(browser.port)}
                if tid not in pages:
                    _warn("持久 worker 标签已失效，将重新选择", prefix=log_prefix)
                    _PERSISTENT_WORKERS.pop(key, None)
                    tid = None

        if not tid:
            from binance.cdp_silent import pick_last_usable_page

            last = pick_last_usable_page(browser.port)
            if last:
                tid = str(last.get("id") or "") or None
                created = False
                _log(
                    f"复用页签导航 :{browser.port}（{str(last.get('url') or '')[:60]}）",
                    prefix=log_prefix,
                )
            if not tid:
                prev = frontmost_unix_pid() if _preserve_focus_enabled() else None
                tid = browser.create_background_page("about:blank")
                created = True
                _log("无可用页签，后台新建静默 worker（仅此一次）", prefix=log_prefix)
                if prev is not None:
                    time.sleep(0.05)
                    activate_unix_pid(prev)
        else:
            _log("复用静默 worker 标签跳转", prefix=log_prefix)

    sid = browser.attach(tid)
    # last_tab / Gemini：不加 worker hash，避免 SPA 路由异常
    target_url = url if last_tab else with_worker_hash(url)
    _log(f"CDP Page.navigate → {target_url[:100]}", prefix=log_prefix)
    browser.navigate(sid, target_url, timeout=float(page_load_timeout))

    try:
        href = str(browser.evaluate(sid, "location.href") or "")
    except Exception:
        href = ""
    _log(f"导航后 location.href = {href[:120] or '(空)'}", prefix=log_prefix)
    want_host = (urlparse(url).netloc or "").lower()
    got_host = (urlparse(href).netloc or "").lower()
    if want_host and got_host and want_host not in got_host and got_host not in want_host:
        raise SilentCdpError(
            f"静默导航未落地：期望 {want_host}，实际 {got_host or href or '空'}"
        )

    # last_tab：必须 activate，否则 Chrome 不切可见页签，Gemini SPA 也可能不完成渲染
    if last_tab and tid:
        from binance.cdp_silent import capture_os_focus, restore_os_focus

        prev_focus = capture_os_focus()
        try:
            browser.activate_target(tid)
            _log("已 Target.activateTarget（页签应可见）", prefix=log_prefix)
        except Exception as e:
            _warn(f"activateTarget 失败: {e}", prefix=log_prefix)
        finally:
            restore_os_focus(prev_focus)

    if persistent or last_tab:
        _PERSISTENT_WORKERS[key] = {"handle": tid, "target_id": tid}

    binding = SilentDriverBinding(
        driver, browser, session_id=sid, target_id=tid
    )
    set_binding(driver, binding)

    return CdpNavSession(
        main_handle=main_handle,
        worker_handle=tid,
        opened_new_tab=created,
        reused_tab=not created,
        target_id=tid,
        keep_worker=keep,
        binding=binding,
    )


def find_tab_handle_for_url(driver, url: str) -> Optional[str]:
    """CDP Target 列表匹配 URL（不 switch_to）。"""
    target = (url or "").strip()
    if not target:
        return None
    try:
        from binance.cdp_silent import list_pages

        for t in list_pages(_driver_debug_port(driver)):
            cur = str(t.get("url") or "").strip()
            if cur and _urls_match(cur, target):
                return str(t.get("id") or "") or None
    except Exception as e:
        _warn(f"find_tab_handle_for_url 失败: {e}")
    return None


def find_target_id_for_url(driver, url: str) -> Optional[str]:
    return find_tab_handle_for_url(driver, url)


def cdp_goto(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
    persistent: Optional[bool] = None,
    last_tab: bool = False,
) -> CdpNavSession:
    """
    静默打开 url，不 Selenium switch_to。
    last_tab=True：在最后一个可用页签打开（Gemini/TTI 用）。
    """
    chart_url = (url or "").strip()
    if not chart_url:
        raise ValueError("URL 为空")

    use_persistent = _persistent_worker_mode() if persistent is None else bool(persistent)

    if _same_tab_mode() and not last_tab:
        _log("CDP_NAV_SAME_TAB=1：在当前标签导航（会抢焦点）", prefix=log_prefix)
        driver.set_page_load_timeout(page_load_timeout)
        driver.get(chart_url)
        return CdpNavSession(
            _safe_current_handle(driver),
            _safe_current_handle(driver),
            False,
            False,
            None,
            keep_worker=False,
        )

    if not _silent_mode():
        _warn("CDP_SILENT=0：回退 Selenium（可能抢焦点）", prefix=log_prefix)
        main_handle = _safe_current_handle(driver)
        handles = list(driver.window_handles or [])
        if handles:
            try:
                driver.switch_to.window(handles[-1])
            except Exception:
                pass
        else:
            driver.switch_to.new_window("tab")
        driver.set_page_load_timeout(page_load_timeout)
        driver.get(chart_url)
        return CdpNavSession(
            main_handle,
            _safe_current_handle(driver),
            True,
            False,
            None,
            keep_worker=not _close_worker_on_restore(),
        )

    try:
        return _ensure_silent_worker(
            driver,
            chart_url,
            page_load_timeout=page_load_timeout,
            log_prefix=log_prefix,
            persistent=use_persistent,
            last_tab=last_tab,
        )
    except SilentCdpError as e:
        _warn(f"静默 CDP 失败，回退 Selenium（会抢焦点）: {e}", prefix=log_prefix)
        main_handle = _safe_current_handle(driver)
        try:
            handles = list(driver.window_handles or [])
            if handles:
                driver.switch_to.window(handles[-1])
            else:
                driver.switch_to.new_window("tab")
            driver.set_page_load_timeout(page_load_timeout)
            driver.get(chart_url)
            return CdpNavSession(
                main_handle,
                _safe_current_handle(driver),
                True,
                False,
                None,
                keep_worker=not _close_worker_on_restore(),
            )
        except WebDriverException:
            raise e


def cdp_restore(
    driver,
    session: CdpNavSession | None,
    *,
    close_worker: Optional[bool] = None,
) -> None:
    """
    卸下静默绑定。默认不关 worker、不 switch_to（避免抢焦）。
    """
    if not session:
        return
    do_close = _close_worker_on_restore() if close_worker is None else bool(close_worker)

    binding = session.binding or get_binding(driver)
    if do_close and session.target_id and binding:
        try:
            binding.browser.close_target(session.target_id)
        except Exception:
            pass
        clear_persistent_worker(driver)
    # 只卸绑定，绝不 switch_to.window(main) —— 那会把 Chrome 拉到前台
    set_binding(driver, None)


@contextmanager
def cdp_worker_tab(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
    persistent: Optional[bool] = None,
) -> Generator[CdpNavSession, None, None]:
    """with 块内在静默 worker 操作；退出只卸绑定，不切回前台标签。"""
    session = cdp_goto(
        driver,
        url,
        page_load_timeout=page_load_timeout,
        log_prefix=log_prefix,
        persistent=persistent,
    )
    try:
        yield session
    finally:
        cdp_restore(driver, session)


def cdp_get(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
    persistent: Optional[bool] = None,
) -> CdpNavSession:
    """等价于 cdp_goto；调用方需自行 cdp_restore。"""
    return cdp_goto(
        driver,
        url,
        page_load_timeout=page_load_timeout,
        log_prefix=log_prefix,
        persistent=persistent,
    )
