"""
通过 CDP（Selenium debuggerAddress）连接本机 Chrome（默认 9222），抓取币安广场热榜/广场流，
本地缓存已见条目；发现新内容时调用 Gemini 聊天接口做简要分析。

前置：Chrome 已用远程调试启动，例如：
  chrome.exe --remote-debugging-port=9222

环境变量（可选）：
  CHROME_DEBUG_PORT       默认 9222（与 config 一致）
  BINANCE_SQUARE_URL      默认 https://www.binance.com/zh-CN/square
  BINANCE_SQUARE_CACHE    缓存 JSON 路径，默认 getinfo/.cache/binance_square_hot.json
  GEMINI_CHAT_URL         默认 https://bz.d.ezcoin.ink/gemini/chat
  BINANCE_SQUARE_WAIT     页面加载后额外等待秒数，默认 5
  BINANCE_SQUARE_LOG      是否写日志文件，默认 1；设为 0 关闭
  BINANCE_SQUARE_LOG_PATH 日志路径，默认 getinfo/logs/binance_square.log
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

try:
    import requests
except ImportError:
    requests = None

try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    try:
        from webdriver_manager.chrome import ChromeDriverManager
    except ImportError:
        ChromeDriverManager = None
except ImportError:
    webdriver = None

try:
    from config import CHROME_DEBUG_PORT
except Exception:
    CHROME_DEBUG_PORT = int(os.getenv("CHROME_DEBUG_PORT", "9222"))

DEFAULT_GEMINI_URL = "https://bz.d.ezcoin.ink/gemini/chat"
DEFAULT_SQUARE_URL = "https://www.binance.com/zh-CN/square"


def _log_path() -> Path:
    p = os.getenv("BINANCE_SQUARE_LOG_PATH", "").strip()
    if p:
        return Path(p)
    base = Path(__file__).resolve().parent
    d = base / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d / "binance_square.log"


def _append_log(text: str) -> None:
    if os.getenv("BINANCE_SQUARE_LOG", "1").strip().lower() in ("0", "false", "no"):
        return
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def log_snapshot_event(
    event: str,
    square_url: str,
    rows: List[Dict[str, Any]],
    gemini_results: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    将本次快照追加写入日志文件（UTF-8），返回日志文件路径。
    """
    if os.getenv("BINANCE_SQUARE_LOG", "1").strip().lower() in ("0", "false", "no"):
        return None
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts: List[str] = [
        "\n" + "=" * 72 + "\n",
        f"{ts} | {event} | url={square_url} | count={len(rows)}\n",
        "=" * 72 + "\n",
    ]
    for i, row in enumerate(rows, 1):
        t = (row.get("title") or "").replace("\n", " ").strip()
        h = (row.get("href") or "").strip()
        rid = (row.get("id") or "").strip()
        parts.append(f"{i:3}. [{rid}] {t}\n     {h}\n")
    if gemini_results:
        parts.append("\n--- Gemini 分析 ---\n")
        for gr in gemini_results:
            item = gr.get("item") or {}
            ok = gr.get("ok")
            analysis = gr.get("analysis") or ""
            parts.append(
                f"[{'OK' if ok else 'FAIL'}] {item.get('title', '')[:200]}\n{analysis[:2000]}\n---\n"
            )
    parts.append("\n")
    text = "".join(parts)
    _append_log(text)
    return str(_log_path())


def _cache_path() -> Path:
    p = os.getenv("BINANCE_SQUARE_CACHE", "").strip()
    if p:
        return Path(p)
    base = Path(__file__).resolve().parent
    d = base / ".cache"
    d.mkdir(parents=True, exist_ok=True)
    return d / "binance_square_hot.json"


def _load_cache() -> Dict[str, Any]:
    path = _cache_path()
    if not path.exists():
        return {"seen_ids": [], "items": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if "seen_ids" not in raw:
            raw["seen_ids"] = []
        return raw
    except Exception:
        return {"seen_ids": [], "items": []}


def _save_cache(data: Dict[str, Any]) -> None:
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _item_id(title: str, href: str) -> str:
    h = hashlib.sha256(f"{title}|{href}".encode("utf-8")).hexdigest()[:32]
    return h


def _connect_chrome_driver(port: Optional[int] = None) -> Any:
    if webdriver is None:
        raise ImportError("请安装 selenium: pip install selenium")
    port = port or CHROME_DEBUG_PORT
    opts = Options()
    opts.add_experimental_option("debuggerAddress", f"127.0.0.1:{port}")
    if ChromeDriverManager:
        try:
            service = Service(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=opts)
        except Exception:
            pass
    return webdriver.Chrome(options=opts)


def _extract_square_entries(driver: Any) -> List[Dict[str, str]]:
    """从当前页面解析币安广场相关链接与标题（页面结构可能变化，可后续调整选择器）。"""
    wait_sec = float(os.getenv("BINANCE_SQUARE_WAIT", "5"))
    time.sleep(wait_sec)
    entries: List[Dict[str, str]] = []
    seen_href = set()

    def add(href: str, title: str) -> None:
        href = (href or "").strip()
        title = (title or "").strip()
        if not href or len(title) < 2:
            return
        if "/square/" not in href.lower():
            return
        if href in seen_href:
            return
        seen_href.add(href)
        entries.append({"title": title[:500], "href": href})

    try:
        links = driver.find_elements(By.CSS_SELECTOR, "a[href*='/square/']")
        for el in links[:200]:
            try:
                href = el.get_attribute("href") or ""
                title = el.text or el.get_attribute("title") or ""
                add(href, title)
            except Exception:
                continue
    except Exception:
        pass

    if not entries:
        # 兜底：尝试任意 a 标签含 binance 与 square
        try:
            for el in driver.find_elements(By.TAG_NAME, "a")[:300]:
                try:
                    href = el.get_attribute("href") or ""
                    if "binance.com" in href and "square" in href.lower():
                        add(href, el.text or "")
                except Exception:
                    continue
        except Exception:
            pass

    return entries


def call_gemini_chat(message: str, role: str = "common", url: Optional[str] = None,
                     timeout: int = 90) -> Tuple[bool, str]:
    """POST JSON {"role","message"} 到 Gemini 聊天接口。"""
    if not requests:
        return False, "requests 未安装"
    url = (url or os.getenv("GEMINI_CHAT_URL") or DEFAULT_GEMINI_URL).strip()
    try:
        r = requests.post(
            url,
            json={"role": role, "message": message},
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        text = r.text
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}: {text[:500]}"
        try:
            j = r.json()
            msg = j.get("message") or j.get("text") or json.dumps(j, ensure_ascii=False)[:2000]
        except Exception:
            msg = text[:2000]
        return True, msg
    except Exception as e:
        return False, str(e)


def fetch_hot_and_process_new(
    driver: Optional[Any] = None,
    square_url: Optional[str] = None,
    close_driver: bool = True,
) -> Dict[str, Any]:
    """
    打开币安广场页，抓取条目，与缓存比对；对新条目调用 Gemini 分析。
    返回摘要 dict。
    """
    url = (square_url or os.getenv("BINANCE_SQUARE_URL") or DEFAULT_SQUARE_URL).strip()
    cache = _load_cache()
    seen: set = set(cache.get("seen_ids", []))

    own_driver = driver is None
    if own_driver:
        print(f"[INFO] 通过 CDP 连接 127.0.0.1:{CHROME_DEBUG_PORT} ...")
        driver = _connect_chrome_driver()

    entries: List[Dict[str, str]] = []
    try:
        print(f"[INFO] 打开 {url}")
        driver.get(url)
        WebDriverWait(driver, 25).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        entries = _extract_square_entries(driver)
    finally:
        if own_driver and close_driver and driver:
            try:
                driver.quit()
            except Exception:
                pass

    # 新条目
    new_items: List[Dict[str, str]] = []
    for e in entries:
        iid = _item_id(e["title"], e["href"])
        if iid not in seen:
            new_items.append({**e, "id": iid})

    # 首次运行：默认只写入缓存、不刷屏调 Gemini（需分析首批可设 BINANCE_SQUARE_ANALYZE_FIRST=1）
    seed_only = not seen and os.getenv("BINANCE_SQUARE_ANALYZE_FIRST", "").strip().lower() not in (
        "1", "true", "yes",
    )
    if seed_only and new_items:
        print(
            f"[INFO] 首次运行：已缓存 {len(new_items)} 条条目指纹，未调用 Gemini。"
            " 下次有新条目再分析。若要对首批也分析，请设置 BINANCE_SQUARE_ANALYZE_FIRST=1"
        )
        for item in new_items:
            seen.add(item["id"])
        cache["seen_ids"] = list(seen)[-5000:]
        cache["last_update"] = datetime.now().isoformat(timespec="seconds")
        cache["last_url"] = url
        # 保存本次抓取的完整列表，便于查看（无需再开浏览器）
        cache["last_snapshot"] = [
            {"id": it["id"], "title": it["title"], "href": it["href"]} for it in new_items
        ]
        _save_cache(cache)
        log_path = log_snapshot_event("seed", url, cache["last_snapshot"])
        return {
            "url": url,
            "fetched": len(entries),
            "new_count": 0,
            "seeded": len(new_items),
            "new_items": new_items,
            "gemini_results": [],
            "log_path": log_path,
        }

    results = []
    gemini_url = os.getenv("GEMINI_CHAT_URL") or DEFAULT_GEMINI_URL

    for item in new_items:
        prompt = (
            "请对以下币安广场热榜/动态条目做简要分析（要点、影响、风险）：\n"
            f"标题：{item['title']}\n"
            f"链接：{item['href']}"
        )
        ok, out = call_gemini_chat(prompt, role="common", url=gemini_url)
        results.append({"item": item, "ok": ok, "analysis": out})
        seen.add(item["id"])
        print(f"[{'OK' if ok else 'FAIL'}] Gemini: {item['title'][:60]}...")

    # 更新缓存（保留最近条目摘要）
    cache["seen_ids"] = list(seen)[-5000:]
    cache["last_update"] = datetime.now().isoformat(timespec="seconds")
    cache["last_url"] = url
    # 每次抓取后更新快照（当前页解析到的全部条目）
    cache["last_snapshot"] = [
        {"id": _item_id(e["title"], e["href"]), "title": e["title"], "href": e["href"]}
        for e in entries
    ]
    cache["items"] = (cache.get("items") or [])[-200:]
    for r in results:
        cache["items"].append({
            "time": cache["last_update"],
            "title": r["item"]["title"],
            "href": r["item"]["href"],
            "analysis_preview": (r["analysis"] or "")[:300],
        })
    _save_cache(cache)

    log_path = log_snapshot_event(
        "fetch",
        url,
        cache["last_snapshot"],
        gemini_results=results if results else None,
    )

    return {
        "url": url,
        "fetched": len(entries),
        "new_count": len(new_items),
        "new_items": new_items,
        "gemini_results": results,
        "log_path": log_path,
    }


def _print_snapshot(rows: List[Dict[str, Any]], title: str = "最近快照") -> None:
    print(f"\n[{title}] 共 {len(rows)} 条")
    for i, row in enumerate(rows, 1):
        t = (row.get("title") or "").replace("\n", " ")[:120]
        h = row.get("href") or ""
        print(f"  {i:2}. {t}")
        print(f"      {h}")


def show_last_snapshot_from_cache() -> bool:
    """从缓存文件打印 last_snapshot，不打开浏览器。返回是否打印成功。"""
    cache = _load_cache()
    snap = cache.get("last_snapshot")
    if not snap:
        print(
            "[INFO] 缓存中暂无 last_snapshot。请先成功运行一次抓取，或删除缓存后重跑。"
        )
        print(f"  缓存路径: {_cache_path()}")
        return False
    _print_snapshot(snap, "last_snapshot（缓存）")
    print(f"\n缓存文件: {_cache_path()}")
    return True


def run_binance_square_once() -> None:
    """命令行入口：拉取一次并处理新内容；条目明细写入日志文件。"""
    report = fetch_hot_and_process_new()
    keys = ("url", "fetched", "new_count", "seeded", "log_path")
    print(json.dumps({k: report[k] for k in keys if k in report and report[k] is not None}, ensure_ascii=False))
    lp = report.get("log_path")
    if lp:
        print(f"[INFO] 明细已写入日志: {lp}")
    if report.get("seeded"):
        return
    if report.get("new_count", 0) == 0:
        print("[INFO] 暂无新条目（或页面未解析到链接，可检查 BINANCE_SQUARE_URL / 是否需登录）")


if __name__ == "__main__":
    run_binance_square_once()
