"""
CDP 远程调试下的标签页导航：后台开页、不抢用户焦点。

优先：
  - Target.getTargets 查已有标签（不 switch 轮询）
  - Target.createTarget(background=True) 后台新开
  - macOS 操作前后恢复前台 App
绝不默认替换用户当前标签；供 binance / news_mornitor 等共用。

环境变量：
  CDP_NAV_SAME_TAB=1     仅在当前标签导航（旧行为，会抢焦点）
  CDP_PRESERVE_FOCUS=0   关闭 macOS 前台恢复（默认开）
  CDP_SILENT=0           关闭静默策略，回退 new_window（默认开）
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


@dataclass(frozen=True)
class CdpNavSession:
    """一次 cdp_goto 的上下文，供 cdp_restore 还原。"""

    main_handle: Optional[str]
    worker_handle: Optional[str]
    opened_new_tab: bool
    reused_tab: bool
    target_id: Optional[str] = None


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
            # 导航/切 tab 常异步抢焦，稍等再还
            time.sleep(0.08)
            _activate_unix_pid(prev)
            time.sleep(0.05)
            _activate_unix_pid(prev)


def _cdp_cmd(driver, cmd: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return driver.execute_cdp_cmd(cmd, params or {}) or {}


def _list_page_targets(driver) -> list[dict[str, Any]]:
    """用 CDP 列页面目标，避免 switch_to 轮询抢焦点。"""
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


def _handle_for_target(driver, target_id: str, *, before_handles: Optional[set[str]] = None) -> Optional[str]:
    """把 CDP targetId 映射到 Selenium window handle。"""
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
        # 多新标签时：再扫一遍 targets 对齐 url 较难，取最后一个新的
        if new:
            return new[-1]
    # 有的 chromedriver 用 targetId 作 handle，有的用其他 id——再试一次 getTargets 后短等
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

    # CDP 不可用时的旧回退（会短暂切 tab，外层有 focus guard）
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


def _create_background_tab(driver, url: str, *, log_prefix: str) -> tuple[Optional[str], Optional[str]]:
    """
    Target.createTarget(background=True) → (window_handle, target_id)。
    不激活前台标签。
    """
    try:
        before = set(driver.window_handles)
    except WebDriverException:
        before = set()
    try:
        res = _cdp_cmd(
            driver,
            "Target.createTarget",
            {"url": url, "background": True, "newWindow": False},
        )
    except Exception as e:
        _warn(f"Target.createTarget 失败: {e}", prefix=log_prefix)
        return None, None
    tid = str(res.get("targetId") or "") or None
    handle = _handle_for_target(driver, tid or "", before_handles=before)
    if handle:
        _log("已后台新开 worker 标签（不抢焦点）", prefix=log_prefix)
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


def cdp_goto(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
) -> CdpNavSession:
    """
    在 worker 标签页打开 url，绝不默认替换用户当前标签。

    - 已有同 URL 标签 → 切到 worker（外层 preserve_os_focus）并刷新
    - 否则 CDP background 新开；失败再 switch_to.new_window
    - CDP_NAV_SAME_TAB=1 时仅在当前标签导航（兼容旧行为）
    """
    chart_url = (url or "").strip()
    if not chart_url:
        raise ValueError("URL 为空")

    main_handle = _safe_current_handle(driver)

    if _same_tab_mode():
        _log("CDP_NAV_SAME_TAB=1：在当前标签导航", prefix=log_prefix)
        driver.set_page_load_timeout(page_load_timeout)
        driver.get(chart_url)
        return CdpNavSession(main_handle, _safe_current_handle(driver), False, False, None)

    existing_tid = find_target_id_for_url(driver, chart_url)
    existing = find_tab_handle_for_url(driver, chart_url)
    if existing:
        try:
            driver.switch_to.window(existing)
            _log(f"复用已有标签并刷新 → {chart_url}", prefix=log_prefix)
            driver.set_page_load_timeout(page_load_timeout)
            driver.refresh()
            return CdpNavSession(
                main_handle,
                existing,
                opened_new_tab=False,
                reused_tab=True,
                target_id=existing_tid,
            )
        except WebDriverException as e:
            _warn(f"复用标签刷新失败: {e}；改为新开标签", prefix=log_prefix)

    worker: Optional[str] = None
    tid: Optional[str] = None
    opened_new_tab = False

    if _silent_mode():
        worker, tid = _create_background_tab(driver, chart_url, log_prefix=log_prefix)
        if worker:
            opened_new_tab = True
            try:
                driver.switch_to.window(worker)
            except WebDriverException as e:
                _warn(f"切到后台 worker 失败: {e}", prefix=log_prefix)
            driver.set_page_load_timeout(page_load_timeout)
            # createTarget 已带 url；若仍 about:blank 再 get
            try:
                cur = (driver.current_url or "").strip()
            except WebDriverException:
                cur = ""
            if not cur or cur == "about:blank" or not _urls_match(cur, chart_url):
                # 若已在加载目标域则不强制 get，减少二次激活
                if not cur or cur == "about:blank":
                    _log(f"后台导航 → {chart_url}", prefix=log_prefix)
                    driver.get(chart_url)
            return CdpNavSession(
                main_handle,
                worker,
                opened_new_tab=opened_new_tab,
                reused_tab=False,
                target_id=tid,
            )

    # 静默创建失败 / 关闭静默：旧路径
    n_before = 0
    try:
        n_before = len(driver.window_handles)
    except WebDriverException:
        pass

    try:
        driver.switch_to.new_window("tab")
        if n_before and len(driver.window_handles) > n_before:
            opened_new_tab = True
            _log("已新开 worker 标签", prefix=log_prefix)
        else:
            _warn("new_window 后标签数未增加，仍在新上下文导航", prefix=log_prefix)
            opened_new_tab = True
    except WebDriverException as e:
        _warn(f"新开标签失败: {e}", prefix=log_prefix)
        if main_handle:
            try:
                driver.switch_to.window(main_handle)
            except WebDriverException:
                pass
        raise

    _log(f"导航 → {chart_url}", prefix=log_prefix)
    driver.set_page_load_timeout(page_load_timeout)
    driver.get(chart_url)
    worker = _safe_current_handle(driver)
    return CdpNavSession(
        main_handle,
        worker,
        opened_new_tab=opened_new_tab,
        reused_tab=False,
        target_id=None,
    )


def cdp_restore(driver, session: CdpNavSession | None, *, close_worker: bool = True) -> None:
    """回到 main 标签；仅当本次是新开的 worker 标签时才 close。"""
    if not session:
        return
    if close_worker and session.opened_new_tab and (session.target_id or session.worker_handle):
        _close_target(driver, session.target_id, session.worker_handle)
    if session.main_handle:
        try:
            # 仅当 main 仍在时切回，避免无意义激活
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
) -> Generator[CdpNavSession, None, None]:
    """with 块内在 worker 标签操作，退出后自动 cdp_restore；默认不抢 OS 焦点。"""
    with preserve_os_focus():
        session = cdp_goto(
            driver, url, page_load_timeout=page_load_timeout, log_prefix=log_prefix
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
) -> CdpNavSession:
    """等价于 cdp_goto；命名对齐 driver.get 语义。"""
    return cdp_goto(
        driver, url, page_load_timeout=page_load_timeout, log_prefix=log_prefix
    )
