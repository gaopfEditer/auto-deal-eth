#!/usr/bin/env python3
"""
OpenClaw 本地网关客户端：仅 HTTP（不经系统代理，Session.trust_env=False）。

用法：
  python test/openclawApi.py run "第一条"
  python test/openclawApi.py run "任务1" "任务2" "任务3"   # 依次执行，最多 5 条

每条任务：POST webhook → 若需等待结果，则每 3s 刷新：
  - POST /api/openclaw/sessions/history（见下方 sessionKey）
  - 若有 runId，同时 GET /api/openclaw/run/{runId}，任一表明完成即结束等待

队列：同一命令内多条消息串行执行，**上一条完全结束后**才发下一条；单次提交超过 5 条会提示并退出。

环境变量（可选，.env）：
  OPENCLAW_BASE_URL              默认 http://127.0.0.1:18789
  OPENCLAW_WEBHOOK_URL           默认 BASE + /api/openclaw/webhook/webhook
  OPENCLAW_SESSION_HISTORY_KEY   sessions/history 的 sessionKey，默认 agent:main:webhook:
  OPENCLAW_HISTORY_LIMIT         history 请求 limit，默认 10
  OPENCLAW_WEBHOOK_TOKEN / OPENCLAW_TOKEN  Bearer；未设则用本地默认 webhook-secret-token
  OPENCLAW_AGENT_TIMEOUT         webhook POST 与整任务最长等待（秒），默认 300
  OPENCLAW_HISTORY_POLL_INTERVAL 刷新间隔秒，默认 3
  OPENCLAW_WEBHOOK_AUTO_POLL=0   不等待异步结果（仅 POST 即返回）
  OPENCLAW_DEBUG / OPENCLAW_QUIET
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

_REPO_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
    load_dotenv()
except ImportError:
    pass

_LOCAL_DEFAULT_BEARER = "webhook-secret-token"
QUEUE_MAX_TASKS = 5

DEFAULT_BASE = os.getenv("OPENCLAW_BASE_URL", "http://127.0.0.1:18789").rstrip("/")
AGENT_TIMEOUT_SEC = int(os.getenv("OPENCLAW_AGENT_TIMEOUT", "300").strip() or "300")
DEFAULT_POLL_SEC = float(
    os.getenv("OPENCLAW_HISTORY_POLL_INTERVAL", "3").strip() or "3"
)


def _oc_debug_enabled() -> bool:
    v = (os.getenv("OPENCLAW_DEBUG") or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _oc_progress_enabled() -> bool:
    if _oc_debug_enabled():
        return True
    q = (os.getenv("OPENCLAW_QUIET") or "").strip().lower()
    return q not in ("1", "true", "yes", "on")


def _oc_log(msg: str, *, debug_only: bool = False) -> None:
    if debug_only and not _oc_debug_enabled():
        return
    if not debug_only and not _oc_progress_enabled():
        return
    print(f"[openclaw] {msg}", flush=True)


def _default_bearer(explicit: Optional[str]) -> str:
    t = (explicit or "").strip()
    if t:
        return t
    t = (os.getenv("OPENCLAW_WEBHOOK_TOKEN") or "").strip()
    if t:
        return t
    t = (os.getenv("OPENCLAW_TOKEN") or "").strip()
    if t:
        return t
    return _LOCAL_DEFAULT_BEARER


def _session_history_key(explicit: Optional[str]) -> str:
    return (
        (explicit or "").strip()
        or "agent:main:hook:webhook:"
    )


def _history_limit() -> int:
    try:
        return max(1, int(os.getenv("OPENCLAW_HISTORY_LIMIT", "10").strip() or "10"))
    except ValueError:
        return 10


def _extract_webhook_assistant_text(obj: Any, *, _depth: int = 0) -> str:
    if _depth > 16 or obj is None:
        return ""
    if isinstance(obj, str):
        return obj.strip()
    if isinstance(obj, dict):
        choices = obj.get("choices")
        if isinstance(choices, list) and choices:
            ch0 = choices[0]
            if isinstance(ch0, dict):
                msg = ch0.get("message")
                if isinstance(msg, dict):
                    c = msg.get("content")
                    if isinstance(c, str) and c.strip():
                        return c.strip()
                delta = ch0.get("delta")
                if isinstance(delta, dict):
                    c = delta.get("content")
                    if isinstance(c, str) and c.strip():
                        return c.strip()
        for key in (
            "assistant_text",
            "output_text",
            "output",
            "response",
            "reply",
            "answer",
            "text",
            "content",
            "message",
        ):
            v = obj.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(v, (dict, list)):
                inner = _extract_webhook_assistant_text(v, _depth=_depth + 1)
                if inner:
                    return inner
        msgs = obj.get("messages")
        if isinstance(msgs, list):
            for m in reversed(msgs):
                if not isinstance(m, dict):
                    continue
                role = str(m.get("role") or "").lower()
                if role in ("assistant", "model", "agent"):
                    c = m.get("text") or m.get("content")
                    if isinstance(c, str) and c.strip():
                        return c.strip()
        for v in obj.values():
            if isinstance(v, (dict, list)):
                inner = _extract_webhook_assistant_text(v, _depth=_depth + 1)
                if inner:
                    return inner
    if isinstance(obj, list):
        best = ""
        for it in obj:
            inner = _extract_webhook_assistant_text(it, _depth=_depth + 1)
            if len(inner) > len(best):
                best = inner
        return best
    return ""


def _messages_list_from_history_body(body: Any) -> List[Dict[str, Any]]:
    """从 sessions/history 响应中取出 messages 列表（尽力兼容结构）。"""
    if not isinstance(body, dict):
        return []
    for key in ("messages", "items", "history", "entries"):
        v = body.get(key)
        if isinstance(v, list):
            return [x for x in v if isinstance(x, dict)]
    nested = body.get("data")
    if isinstance(nested, dict):
        for key in ("messages", "items", "history"):
            v = nested.get(key)
            if isinstance(v, list):
                return [x for x in v if isinstance(x, dict)]
    return []


def _last_assistant_from_history_body(body: Any) -> str:
    msgs = _messages_list_from_history_body(body)
    for m in reversed(msgs):
        role = str(m.get("role") or "").lower()
        if role in ("assistant", "model", "agent"):
            c = m.get("text") or m.get("content")
            if isinstance(c, str) and c.strip():
                return c.strip()
    return _extract_webhook_assistant_text(body)


def webhook_send(
    text: str,
    *,
    body_path: str = "webhook",
    url: Optional[str] = None,
    token: Optional[str] = None,
    timeout: float = 120.0,
) -> Dict[str, Any]:
    u = (url or os.getenv("OPENCLAW_WEBHOOK_URL") or "").strip()
    if not u:
        u = f"{DEFAULT_BASE}/api/openclaw/webhook/webhook"
    tok = _default_bearer(token)
    payload = {"path": body_path, "messages": [{"text": text}]}
    _oc_log(f"webhook POST {u!r} body.path={body_path!r}")
    with requests.Session() as s:
        s.trust_env = False
        r = s.post(
            u,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tok}",
            },
            json=payload,
            timeout=float(timeout),
        )
    body: Any
    try:
        body = r.json()
    except ValueError:
        body = {"raw": (r.text or "")[:8000]}
    return {"ok": r.ok, "status_code": r.status_code, "body": body}


def sessions_history_post(
    *,
    session_key: Optional[str] = None,
    limit: Optional[int] = None,
    token: Optional[str] = None,
    url: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """POST /api/openclaw/sessions/history，与 curl 示例一致。"""
    u = (url or "").strip() or f"{DEFAULT_BASE}/api/openclaw/sessions/history"
    sk = _session_history_key(session_key)
    lim = int(limit) if limit is not None else _history_limit()
    tok = _default_bearer(token)
    _oc_log(f"sessions/history POST sessionKey={sk!r} limit={lim}", debug_only=True)
    with requests.Session() as s:
        s.trust_env = False
        r = s.post(
            u,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {tok}",
            },
            json={"sessionKey": sk, "limit": lim},
            timeout=float(timeout),
        )
    body: Any
    try:
        body = r.json()
    except ValueError:
        body = {"raw": (r.text or "")[:8000]}
    return {"ok": r.ok, "status_code": r.status_code, "body": body}


def _run_status_body_state(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    st = data.get("state") or data.get("status")
    if isinstance(st, str) and st.strip():
        return st.strip().lower()
    nested = data.get("data")
    if isinstance(nested, dict):
        st2 = nested.get("state") or nested.get("status")
        if isinstance(st2, str) and st2.strip():
            return st2.strip().lower()
    return ""


def _run_status_result_payload(data: Any) -> Any:
    if isinstance(data, dict):
        if "result" in data:
            return data.get("result")
        if "output" in data:
            return data.get("output")
        nested = data.get("data")
        if isinstance(nested, dict):
            if "result" in nested:
                return nested.get("result")
            if "output" in nested:
                return nested.get("output")
        return data
    return data


def _normalize_run_id(run_id: str) -> str:
    rid = run_id.strip()
    if not rid or any(ch in rid for ch in "/\\?# \t\n\r"):
        raise ValueError(f"非法 runId: {run_id!r}")
    return rid


def run_status_fetch(
    run_id: str,
    *,
    url: Optional[str] = None,
    token: Optional[str] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    rid = _normalize_run_id(run_id)
    u = (url or "").strip() or f"{DEFAULT_BASE}/api/openclaw/run/{rid}"
    tok = _default_bearer(token)
    with requests.Session() as s:
        s.trust_env = False
        r = s.get(
            u,
            headers={"Authorization": f"Bearer {tok}"},
            timeout=float(timeout),
        )
    body: Any
    try:
        body = r.json()
    except ValueError:
        body = {"raw": (r.text or "")[:8000]}
    return {"ok": r.ok, "status_code": r.status_code, "body": body}


def _run_id_from_body(body: Any) -> Optional[str]:
    if not isinstance(body, dict):
        return None
    rid = body.get("runId") or body.get("run_id")
    if isinstance(rid, str) and rid.strip():
        return rid.strip()
    return None


def wait_for_task_outcome(
    *,
    run_id: Optional[str],
    token: Optional[str],
    session_key: Optional[str],
    poll_interval: float,
    max_wait: float,
) -> Dict[str, Any]:
    """
    每 poll_interval 秒：POST sessions/history；若有 runId 则同时 GET run 状态。
    完成条件：run 状态 completed/failed，或 history 中最后一条 assistant 相对首轮有更新且包含实质内容（无 runId 时兜底）。
    """
    t0 = time.time()
    poll_interval = max(1.0, float(poll_interval))
    max_wait = max(poll_interval, float(max_wait))

    baseline_hist = sessions_history_post(
        session_key=session_key, token=token, timeout=30.0
    )
    baseline_assistant = _last_assistant_from_history_body(baseline_hist.get("body"))
    last_hist = baseline_hist
    last_run: Optional[Dict[str, Any]] = None

    while True:
        elapsed = time.time() - t0
        if elapsed >= max_wait:
            raise TimeoutError(
                f"等待结果超过 {max_wait:.0f}s；最后 history HTTP {last_hist.get('status_code')} "
                f"run={last_run!r}"
            )

        time.sleep(poll_interval)

        hist = sessions_history_post(session_key=session_key, token=token, timeout=30.0)
        last_hist = hist
        hbody = hist.get("body")
        assistant_now = _last_assistant_from_history_body(hbody)

        if _oc_progress_enabled():
            line = f"[*] 刷新（{poll_interval:g}s）：history HTTP {hist.get('status_code')}"
            if run_id:
                line += f"  runId={run_id[:8]}…"
            print(line, flush=True)

        if run_id:
            last_run = run_status_fetch(run_id, token=token, timeout=30.0)
            rb = last_run.get("body")
            state = _run_status_body_state(rb)
            if _oc_progress_enabled():
                print(f"    run 状态: {state or '(无)'}  HTTP {last_run.get('status_code')}", flush=True)
            if state == "completed":
                res = _run_status_result_payload(rb) if isinstance(rb, dict) else rb
                t2 = _extract_webhook_assistant_text(res)
                if not t2 and isinstance(res, str):
                    t2 = res.strip()
                if not t2:
                    t2 = assistant_now
                return {
                    "ok": True,
                    "final_state": "completed",
                    "assistant_text": t2,
                    "result": res,
                    "last_run": last_run,
                    "last_history": hist,
                }
            if state == "failed":
                return {
                    "ok": False,
                    "final_state": "failed",
                    "assistant_text": assistant_now,
                    "result": _run_status_result_payload(rb) if isinstance(rb, dict) else rb,
                    "last_run": last_run,
                    "last_history": hist,
                }

        # 无 runId：用 history 中 assistant 相对基线变化作为完成启发式
        if not run_id and assistant_now and assistant_now != baseline_assistant:
            return {
                "ok": True,
                "final_state": "history_changed",
                "assistant_text": assistant_now,
                "last_history": hist,
            }

        # 有 runId 但 run 接口迟迟无 state：若 assistant 明显变长/变化，也可先展示（仍以 run 为准直到 timeout）
        if (
            run_id
            and assistant_now
            and assistant_now != baseline_assistant
            and len(assistant_now) > len(baseline_assistant) + 2
        ):
            if _oc_debug_enabled():
                _oc_log("history 中 assistant 已更新（run 尚未 completed，继续轮询）", debug_only=True)


def _execute_single_task(
    message: str,
    ns: argparse.Namespace,
) -> Dict[str, Any]:
    url = (ns.webhook_url or "").strip() or None
    token = (ns.webhook_token or "").strip() or None
    session_key = (ns.session_key or "").strip() or None

    try:
        raw = webhook_send(
            message,
            body_path=ns.webhook_path,
            url=url,
            token=token,
            timeout=float(ns.timeout),
        )
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": str(e), "message": message}

    body = raw.get("body")
    assistant = _extract_webhook_assistant_text(body) if body is not None else ""
    out: Dict[str, Any] = {
        **raw,
        "message": message,
        "assistant_text": assistant,
        "ok": bool(raw.get("ok")) or bool(assistant.strip()),
    }

    auto = (os.getenv("OPENCLAW_WEBHOOK_AUTO_POLL") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    rid = _run_id_from_body(body)
    need_wait = auto and not getattr(ns, "no_poll", False) and (
        (rid and not assistant.strip()) or (not rid and not assistant.strip())
    )

    if need_wait:
        if _oc_progress_enabled():
            print(
                f"[*] 等待结果：每 {float(ns.poll_interval):g}s 请求 sessions/history"
                + (f" + GET run/{rid[:8]}…" if rid else "")
                + " …",
                flush=True,
            )
        try:
            fin = wait_for_task_outcome(
                run_id=rid,
                token=token,
                session_key=session_key,
                poll_interval=float(ns.poll_interval),
                max_wait=float(AGENT_TIMEOUT_SEC) * 3,
            )
            out["wait"] = fin
            t2 = (fin.get("assistant_text") or "").strip()
            if t2:
                out["assistant_text"] = t2
            out["ok"] = bool(out.get("ok")) and bool(fin.get("ok", True))
        except TimeoutError as e:
            out["wait_error"] = str(e)

    return out


def _print_task_out(out: Dict[str, Any], *, index: int, total: int) -> int:
    txt = str(out.get("assistant_text") or "").strip()
    if txt and _oc_progress_enabled():
        print(f"=== 任务 {index}/{total} 回复正文 ===", flush=True)
        print(txt, flush=True)
        print(flush=True)
    print(json.dumps(out, indent=2, ensure_ascii=False))
    code = 0
    if not out.get("ok"):
        code = 1
    if out.get("wait_error"):
        code = 1
    if out.get("wait") and not out["wait"].get("ok", True):
        code = 1
    return code


def _webhook_flow(ns: argparse.Namespace) -> None:
    _apply_log_flags(ns)
    messages: List[str] = list(ns.messages)
    if len(messages) > QUEUE_MAX_TASKS:
        err = {
            "ok": False,
            "error": f"队列已满：单次最多 {QUEUE_MAX_TASKS} 条任务，当前 {len(messages)} 条。请分批提交。",
            "max": QUEUE_MAX_TASKS,
            "count": len(messages),
        }
        print(json.dumps(err, indent=2, ensure_ascii=False))
        raise SystemExit(2)

    exit_code = 0
    total = len(messages)
    for i, msg in enumerate(messages, start=1):
        if total > 1 and _oc_progress_enabled():
            print(f"\n{'='*60}\n[*] 队列执行 {i}/{total}（上一条完成后才开始本条）\n{'='*60}\n", flush=True)
        out = _execute_single_task(msg, ns)
        c = _print_task_out(out, index=i, total=total)
        if c != 0:
            exit_code = c
            if _oc_progress_enabled():
                print(f"[!] 任务 {i} 失败，后续任务不再执行。", flush=True)
            break

    raise SystemExit(exit_code)


def _add_log_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("-v", "--verbose", action="store_true", help="调试日志")
    p.add_argument("-q", "--quiet", action="store_true", help="安静模式")


def _apply_log_flags(ns: argparse.Namespace) -> None:
    if getattr(ns, "verbose", False):
        os.environ["OPENCLAW_DEBUG"] = "1"
    if getattr(ns, "quiet", False):
        os.environ["OPENCLAW_QUIET"] = "1"


def _add_webhook_cli(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "messages",
        nargs="+",
        help=f"一条或多条消息（依次执行，最多 {QUEUE_MAX_TASKS} 条）",
    )
    p.add_argument(
        "--url",
        default="",
        dest="webhook_url",
        help="webhook 完整 URL",
    )
    p.add_argument(
        "--token",
        default="",
        dest="webhook_token",
        help="Bearer（可选）",
    )
    p.add_argument(
        "--session-key",
        default="",
        dest="session_key",
        help="sessions/history 的 sessionKey；默认 agent:main:webhook: 或 OPENCLAW_SESSION_HISTORY_KEY",
    )
    p.add_argument(
        "--path",
        default="webhook",
        dest="webhook_path",
        help="webhook JSON path",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(AGENT_TIMEOUT_SEC),
        help=f"webhook POST 超时（秒），默认 {AGENT_TIMEOUT_SEC}",
    )
    p.add_argument(
        "--no-poll",
        action="store_true",
        dest="no_poll",
        help="不等待异步结果",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_SEC,
        dest="poll_interval",
        help=f"刷新间隔秒（默认 {DEFAULT_POLL_SEC:g}）",
    )
    _add_log_flags(p)


def main() -> None:
    p = argparse.ArgumentParser(
        description="OpenClaw：webhook + sessions/history 轮询，队列最多 5 条"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sr = sub.add_parser("run", help="发送一条或多条消息（串行队列，最多 5 条）")
    _add_webhook_cli(sr)
    sr.set_defaults(func=_webhook_flow)

    sw = sub.add_parser("webhook", help="与 run 相同")
    _add_webhook_cli(sw)
    sw.set_defaults(func=_webhook_flow)

    ns = p.parse_args()
    ns.func(ns)


if __name__ == "__main__":
    main()
