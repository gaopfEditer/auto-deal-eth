"""
CDP 远程调试下的标签页导航：静默、不抢焦点。

默认策略（供 market_lists_selenium / news_mornitor 等）：
  1. 第一次：Target.createTarget(background=True) 开一个专用 worker 标签
  2. 之后：始终在同一 worker 里 driver.get 跳转，不再新开
  3. restore 时回到用户原标签，默认不关 worker
  4. macOS 操作前后恢复前台 App

环境变量：
  CDP_NAV_SAME_TAB=1          仅在当前标签导航（旧行为，会抢焦点）
  CDP_SILENT=0                关闭静默建 tab，回退 new_window
  CDP_PERSISTENT_WORKER=0     关闭「单 worker 复用」（每次按 URL 匹配/新开）
  CDP_PRESERVE_FOCUS=0        关闭 macOS 前台恢复
  CDP_CLOSE_WORKER=1          restore 时关闭本次新开的 worker（破坏复用）
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Generator, Optional
from urllib.parse import parse_qs, unquote, urlparse

from selenium.common.exceptions import WebDriverException

# driver 对象 id → 持久 worker（同一次 Chrome 附着会话内复用）
_PERSISTENT_WORKERS: dict[int, dict[str, Any]] = {}


@dataclass(frozen=True)
class CdpNavSession:
    """一次 cdp_goto 的上下文，供 cdp_restore 还原。"""

    main_handle: Optional[str]
    worker_handle: Optional[str]
    opened_new_tab: bool
    reused_tab: bool
    target_id: Optional[str] = None
    keep_worker: bool = True


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
    """用于跨标签匹配：TradingView 看 symbol+interval，币安 trade 看 trade 路径。"""
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
    v = os.getenv("CDP_PRESERVE_FOCUS", "1")
    return v.strip().lower() not in ("0", "false", "no")


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
def preserve_os_focus() -> Generator[None, None, None]:
    """操作 Chrome 前后恢复 macOS 前台应用，避免 CDP 抢焦点。"""
    if not _preserve_focus_enabled() or sys.platform != "darwin":
        yield
        return
    prev = _frontmost_unix_pid()
    try:
        yield
    finally:
        if prev is not None:
            time.sleep(0.08)
            _activate_unix_pid(prev)
            time.sleep(0.05)
            _activate_unix_pid(prev)


def _cdp_cmd(driver, cmd: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return driver.execute_cdp_cmd(cmd, params or {}) or {}


def _list_page_targets(driver) -> list[dict[str, Any]]:
    try:
        data = _cdp_cmd(driver, "Target.getTargets", {})
        infos = data.get("targetInfos") or []
        return [
            t
            for t in infos
            if isinstance(t, dict) and t.get("type") == "page" and t.get("targetId")
        ]
    except Exception as e:
        _warn(f"Target.getTargets 失败: {e}")
        return []


def _handle_for_target(
    driver, target_id: str, *, before_handles: Optional[set[str]] = None
) -> Optional[str]:
    if not target_id:
        return None
    try:
        handles = list(driver.window_handles)
    except WebDriverException:
        return None
    if target_id in handles:
        return target_id
    if before_handles is not None:
        new = [h for h in handles if h not in before_handles]
        if len(new) == 1:
            return new[0]
        if new:
            return new[-1]
    for _ in range(20):
        try:
            handles = list(driver.window_handles)
        except WebDriverException:
            return None
        if target_id in handles:
            return target_id
        if before_handles is not None:
            new = [h for h in handles if h not in before_handles]
            if new:
                return new[-1]
        time.sleep(0.05)
    return None


def find_tab_handle_for_url(driver, url: str) -> Optional[str]:
    """若已有标签打开同一目标 URL，返回其 handle（优先 CDP，不轮询 switch）。"""
    target = (url or "").strip()
    if not target:
        return None

    for t in _list_page_targets(driver):
        cur = str(t.get("url") or "").strip()
        if cur and _urls_match(cur, target):
            tid = str(t.get("targetId") or "")
            h = _handle_for_target(driver, tid)
            if h:
                return h

    try:
        handles = list(driver.window_handles)
    except WebDriverException:
        return None
    main = _safe_current_handle(driver)
    found: Optional[str] = None
    for h in handles:
        try:
            driver.switch_to.window(h)
            cur = (driver.current_url or "").strip()
        except WebDriverException:
            continue
        if cur and _urls_match(cur, target):
            found = h
            break
    if main:
        try:
            driver.switch_to.window(main)
        except WebDriverException:
            pass
    return found


def find_target_id_for_url(driver, url: str) -> Optional[str]:
    target = (url or "").strip()
    if not target:
        return None
    for t in _list_page_targets(driver):
        cur = str(t.get("url") or "").strip()
        if cur and _urls_match(cur, target):
            return str(t.get("targetId") or "") or None
    return None


def _create_background_tab(
    driver, url: str, *, log_prefix: str
) -> tuple[Optional[str], Optional[str]]:
    try:
        before = set(driver.window_handles)
    except WebDriverException:
        before = set()
    try:
        res = _cdp_cmd(
            driver,
            "Target.createTarget",
            {"url": url or "about:blank", "background": True, "newWindow": False},
        )
    except Exception as e:
        _warn(f"Target.createTarget 失败: {e}", prefix=log_prefix)
        return None, None
    tid = str(res.get("targetId") or "") or None
    handle = _handle_for_target(driver, tid or "", before_handles=before)
    if handle:
        _log("已后台新开专用 worker 标签（不抢焦点）", prefix=log_prefix)
        return handle, tid
    _warn("后台标签已创建但未能映射 window handle", prefix=log_prefix)
    return None, tid


def _close_target(driver, target_id: Optional[str], worker_handle: Optional[str]) -> None:
    if target_id:
        try:
            _cdp_cmd(driver, "Target.closeTarget", {"targetId": target_id})
            return
        except Exception:
            pass
    if not worker_handle:
        return
    try:
        cur = _safe_current_handle(driver)
        if cur != worker_handle:
            driver.switch_to.window(worker_handle)
        driver.close()
    except WebDriverException:
        pass


def _driver_key(driver) -> int:
    return id(driver)


def clear_persistent_worker(driver) -> None:
    """手动清掉该 driver 的持久 worker 记录（不关标签）。"""
    _PERSISTENT_WORKERS.pop(_driver_key(driver), None)


def _worker_handle_alive(driver, handle: Optional[str]) -> bool:
    if not handle:
        return False
    try:
        return handle in list(driver.window_handles)
    except WebDriverException:
        return False


def _ensure_persistent_worker(
    driver, *, log_prefix: str
) -> tuple[str, Optional[str], bool]:
    """
    返回 (worker_handle, target_id, newly_created)。
    首次 background 建 tab；之后复用同一 handle。
    """
    key = _driver_key(driver)
    entry = _PERSISTENT_WORKERS.get(key)
    if entry:
        h = entry.get("handle")
        tid = entry.get("target_id")
        if _worker_handle_alive(driver, h):
            return str(h), tid, False
        _warn("持久 worker 标签已失效，将重新创建", prefix=log_prefix)
        _PERSISTENT_WORKERS.pop(key, None)

    worker: Optional[str] = None
    tid: Optional[str] = None
    if _silent_mode():
        worker, tid = _create_background_tab(driver, "about:blank", log_prefix=log_prefix)

    if not worker:
        # 回退 new_window（仍尽量包在 focus guard 外层）
        main = _safe_current_handle(driver)
        n_before = 0
        try:
            n_before = len(driver.window_handles)
        except WebDriverException:
            pass
        try:
            before = set(driver.window_handles)
        except WebDriverException:
            before = set()
        driver.switch_to.new_window("tab")
        worker = _safe_current_handle(driver)
        if not worker:
            after = set(driver.window_handles) - before
            worker = after.pop() if after else None
        if not worker:
            if main:
                try:
                    driver.switch_to.window(main)
                except WebDriverException:
                    pass
            raise WebDriverException("无法创建 worker 标签")
        _log("回退 new_window 创建 worker 标签", prefix=log_prefix)
        if n_before and len(driver.window_handles) <= n_before:
            _warn("new_window 后标签数未增加", prefix=log_prefix)

    _PERSISTENT_WORKERS[key] = {"handle": worker, "target_id": tid}
    return worker, tid, True


def _navigate_worker(
    driver,
    worker: str,
    url: str,
    *,
    page_load_timeout: int,
    log_prefix: str,
) -> None:
    driver.switch_to.window(worker)
    driver.set_page_load_timeout(page_load_timeout)
    # 优先 CDP Page.navigate（不 bringToFront）；失败再 driver.get
    try:
        _cdp_cmd(driver, "Page.enable", {})
        _cdp_cmd(driver, "Page.navigate", {"url": url})
        # 等 ready
        deadline = time.time() + max(8, min(page_load_timeout, 40))
        while time.time() < deadline:
            try:
                state = driver.execute_script("return document.readyState")
            except Exception:
                time.sleep(0.15)
                continue
            if state in ("interactive", "complete"):
                break
            time.sleep(0.15)
        _log(f"worker 内 CDP 跳转 → {url}", prefix=log_prefix)
        return
    except Exception as e:
        _warn(f"Page.navigate 失败，改用 driver.get: {e}", prefix=log_prefix)
    driver.get(url)
    _log(f"worker 内 get → {url}", prefix=log_prefix)


def cdp_goto(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
    persistent: Optional[bool] = None,
) -> CdpNavSession:
    """
    在 worker 标签打开 url，不替换用户当前前台标签。

    默认 persistent：全脚本共用一个后台 worker，后续只在该页跳转。
    """
    chart_url = (url or "").strip()
    if not chart_url:
        raise ValueError("URL 为空")

    main_handle = _safe_current_handle(driver)
    use_persistent = _persistent_worker_mode() if persistent is None else bool(persistent)
    keep = not _close_worker_on_restore()

    if _same_tab_mode():
        _log("CDP_NAV_SAME_TAB=1：在当前标签导航", prefix=log_prefix)
        driver.set_page_load_timeout(page_load_timeout)
        driver.get(chart_url)
        return CdpNavSession(
            main_handle, _safe_current_handle(driver), False, False, None, keep_worker=False
        )

    # —— 持久 worker：第一次开，之后同 tab 跳转 ——
    if use_persistent:
        worker, tid, created = _ensure_persistent_worker(driver, log_prefix=log_prefix)
        if created:
            _log("首次创建静默 worker，后续跳转复用此标签", prefix=log_prefix)
        else:
            _log("复用静默 worker 标签跳转", prefix=log_prefix)
        _navigate_worker(
            driver,
            worker,
            chart_url,
            page_load_timeout=page_load_timeout,
            log_prefix=log_prefix,
        )
        return CdpNavSession(
            main_handle,
            worker,
            opened_new_tab=created,
            reused_tab=not created,
            target_id=tid,
            keep_worker=keep,
        )

    # —— 非持久：按 URL 复用或新开（旧逻辑） ——
    existing_tid = find_target_id_for_url(driver, chart_url)
    existing = find_tab_handle_for_url(driver, chart_url)
    if existing:
        try:
            driver.switch_to.window(existing)
            _log(f"复用已有同 URL 标签并刷新 → {chart_url}", prefix=log_prefix)
            driver.set_page_load_timeout(page_load_timeout)
            driver.refresh()
            return CdpNavSession(
                main_handle,
                existing,
                opened_new_tab=False,
                reused_tab=True,
                target_id=existing_tid,
                keep_worker=True,
            )
        except WebDriverException as e:
            _warn(f"复用标签刷新失败: {e}；改为新开标签", prefix=log_prefix)

    worker = None
    tid = None
    opened_new_tab = False
    if _silent_mode():
        worker, tid = _create_background_tab(driver, chart_url, log_prefix=log_prefix)
        if worker:
            opened_new_tab = True
            _navigate_worker(
                driver,
                worker,
                chart_url,
                page_load_timeout=page_load_timeout,
                log_prefix=log_prefix,
            )
            return CdpNavSession(
                main_handle,
                worker,
                opened_new_tab=True,
                reused_tab=False,
                target_id=tid,
                keep_worker=keep,
            )

    n_before = 0
    try:
        n_before = len(driver.window_handles)
    except WebDriverException:
        pass
    try:
        driver.switch_to.new_window("tab")
        opened_new_tab = True
        _log("已新开 worker 标签", prefix=log_prefix)
    except WebDriverException as e:
        _warn(f"新开标签失败: {e}", prefix=log_prefix)
        if main_handle:
            try:
                driver.switch_to.window(main_handle)
            except WebDriverException:
                pass
        raise

    if n_before and len(driver.window_handles) <= n_before:
        _warn("new_window 后标签数未增加，仍在新上下文导航", prefix=log_prefix)

    driver.set_page_load_timeout(page_load_timeout)
    driver.get(chart_url)
    worker = _safe_current_handle(driver)
    return CdpNavSession(
        main_handle,
        worker,
        opened_new_tab=opened_new_tab,
        reused_tab=False,
        target_id=None,
        keep_worker=keep,
    )


def cdp_restore(
    driver,
    session: CdpNavSession | None,
    *,
    close_worker: Optional[bool] = None,
) -> None:
    """
    回到 main 标签。
    默认不关 worker（保持下次复用）；仅 CDP_CLOSE_WORKER=1 或 close_worker=True 时关闭。
    """
    if not session:
        return
    do_close = _close_worker_on_restore() if close_worker is None else bool(close_worker)
    with preserve_os_focus():
        if do_close:
            _close_target(driver, session.target_id, session.worker_handle)
            clear_persistent_worker(driver)
        if session.main_handle:
            try:
                handles = list(driver.window_handles)
                if session.main_handle in handles:
                    driver.switch_to.window(session.main_handle)
            except WebDriverException:
                pass


@contextmanager
def cdp_worker_tab(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
    persistent: Optional[bool] = None,
) -> Generator[CdpNavSession, None, None]:
    """with 块内在静默 worker 操作；退出回到原标签，默认保留 worker 供下次复用。"""
    with preserve_os_focus():
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
    """等价于 cdp_goto；调用方需自行 cdp_restore。全程包一层 OS 焦点保护。"""
    with preserve_os_focus():
        return cdp_goto(
            driver,
            url,
            page_load_timeout=page_load_timeout,
            log_prefix=log_prefix,
            persistent=persistent,
        )
