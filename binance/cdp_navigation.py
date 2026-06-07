"""
CDP 远程调试下的标签页导航：不占用当前标签，优先复用同 URL 标签并刷新，否则新开。

供 binance.market_lists_selenium、gainers_top20（经 dealMsg.runner）等共用。
"""
from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Generator, Optional
from urllib.parse import parse_qs, unquote, urlparse

from selenium.common.exceptions import WebDriverException


@dataclass(frozen=True)
class CdpNavSession:
    """一次 cdp_goto 的上下文，供 cdp_restore 还原。"""

    main_handle: Optional[str]
    worker_handle: Optional[str]
    opened_new_tab: bool
    reused_tab: bool


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
        # …/trade/FF_USDT
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


def _tab_url(driver, handle: str) -> str:
    try:
        driver.switch_to.window(handle)
        return (driver.current_url or "").strip()
    except WebDriverException:
        return ""


def find_tab_handle_for_url(driver, url: str) -> Optional[str]:
    """若已有标签打开同一目标 URL，返回其 handle。"""
    target = (url or "").strip()
    if not target:
        return None
    try:
        handles = list(driver.window_handles)
    except WebDriverException:
        return None
    main = _safe_current_handle(driver)
    for h in handles:
        cur = _tab_url(driver, h)
        if cur and _urls_match(cur, target):
            if main:
                try:
                    driver.switch_to.window(main)
                except WebDriverException:
                    pass
            return h
    if main:
        try:
            driver.switch_to.window(main)
        except WebDriverException:
            pass
    return None


def _same_tab_mode() -> bool:
    v = os.getenv("CDP_NAV_SAME_TAB", "") or os.getenv("DEALMSG_TV_SAME_TAB", "")
    return v.strip().lower() in ("1", "true", "yes")


def cdp_goto(
    driver,
    url: str,
    *,
    page_load_timeout: int = 90,
    log_prefix: str = "CDP",
) -> CdpNavSession:
    """
    在 worker 标签页打开 url，绝不默认替换用户当前标签。

    - 已有同 URL 标签 → 切过去并 refresh
    - 否则 switch_to.new_window('tab') 后 get
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
        return CdpNavSession(main_handle, _safe_current_handle(driver), False, False)

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
            )
        except WebDriverException as e:
            _warn(f"复用标签刷新失败: {e}；改为新开标签", prefix=log_prefix)

    n_before = 0
    try:
        n_before = len(driver.window_handles)
    except WebDriverException:
        pass

    opened_new_tab = False
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
    )


def cdp_restore(driver, session: CdpNavSession | None, *, close_worker: bool = True) -> None:
    """回到 main 标签；仅当本次是新开的 worker 标签时才 close。"""
    if not session:
        return
    if close_worker and session.opened_new_tab and session.worker_handle:
        try:
            cur = _safe_current_handle(driver)
            if cur == session.worker_handle:
                driver.close()
            else:
                driver.switch_to.window(session.worker_handle)
                driver.close()
        except WebDriverException:
            pass
    if session.main_handle:
        try:
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
    """with 块内在 worker 标签操作，退出后自动 cdp_restore。"""
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
