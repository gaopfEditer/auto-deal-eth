"""
通知模块 - 第1部分：导入和配置
"""
import json
import os
import sys
import time

import requests

from image_llm_analyzer import extract_json_from_gemini_text
from config import DINGTALK_WEBHOOK, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_dingtalk_message(content: str):
    """发送钉钉消息"""
    if not DINGTALK_WEBHOOK:
        print("钉钉Webhook未配置")
        return False
    
    try:
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        response = requests.post(DINGTALK_WEBHOOK, json=data)
        return response.status_code == 200
    except Exception as e:
        print(f"钉钉消息发送失败: {e}")
        return False

# 第2部分：Telegram通知
def _telegram_caption_trim(text: str, max_len: int = 1024) -> str:
    """Telegram 图片 caption 最长 1024 字符。"""
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _telegram_post_with_retry(
    url: str,
    *,
    json_data: dict | None = None,
    form_data: dict | None = None,
    files: dict | None = None,
) -> tuple[requests.Response | None, dict | None]:
    connect_timeout = int(os.getenv("TELEGRAM_CONNECT_TIMEOUT", "20"))
    read_timeout = int(os.getenv("TELEGRAM_READ_TIMEOUT", "120"))
    max_retries = max(1, int(os.getenv("TELEGRAM_SEND_RETRIES", "4")))
    retry_delay = float(os.getenv("TELEGRAM_SEND_DELAY_SEC", "5"))

    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.post(
                url,
                json=json_data,
                data=form_data,
                files=files,
                timeout=(connect_timeout, read_timeout),
            )
            body = None
            try:
                body = r.json()
            except Exception:
                body = None
            if r.status_code in (502, 503, 504) and attempt < max_retries - 1:
                print(
                    f"[Telegram] HTTP {r.status_code}，{retry_delay * (attempt + 1):.0f}s 后重试 "
                    f"({attempt + 1}/{max_retries})…"
                )
                time.sleep(retry_delay * (attempt + 1))
                continue
            return r, body
        except requests.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                wait = retry_delay * (attempt + 1)
                print(
                    f"[Telegram] 网络异常 ({attempt + 1}/{max_retries}): {e}\n"
                    f"[Telegram] 等待 {wait:.0f}s 后重试…"
                )
                time.sleep(wait)
            else:
                print(f"[Telegram] 已达最大重试次数，放弃: {last_exc}")
                return None, None
    return None, None


def send_telegram_message(content: str, chat_id: str | None = None):
    """发送Telegram消息。

    Telegram 常返回 HTTP 200 但 body 里 ok=false（例如 Markdown 解析失败），
    必须解析 JSON 的 ok/description，不能只看 status_code。

    网络慢时：加长读超时，并对连接/读超时/5xx 自动重试（环境变量可配）。

    :param chat_id: 目标群/用户 ID；默认 config.TELEGRAM_CHAT_ID
    """
    target_chat = (chat_id or TELEGRAM_CHAT_ID or "").strip()
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print("[Telegram] 配置未完成: 缺少 TELEGRAM_BOT_TOKEN 或 chat_id")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        # 先尝试 Markdown（与历史行为一致）
        data = {
            "chat_id": target_chat,
            "text": content,
            "parse_mode": "Markdown",
        }
        response, j = _telegram_post_with_retry(url, json_data=data)
        if response is None:
            return False
        print(
            f"[Telegram] HTTP {response.status_code}, "
            f"ok={j.get('ok') if isinstance(j, dict) else '?'}"
        )
        if isinstance(j, dict) and j.get("ok"):
            print("[Telegram] sendMessage 成功, message_id=", j.get("result", {}).get("message_id"))
            return True

        err_desc = (j or {}).get("description", "") if isinstance(j, dict) else ""
        err_code = (j or {}).get("error_code", "") if isinstance(j, dict) else ""
        print(f"[Telegram] API 未成功: description={err_desc!r} error_code={err_code}")
        if response.text and len(response.text) < 2000:
            print(f"[Telegram] 原始响应: {response.text[:1500]}")

        # 常见：JSON/下划线等触发 Markdown 解析失败 → 去掉 parse_mode 重试
        if "parse" in err_desc.lower() or "markdown" in err_desc.lower() or err_code == 400:
            print("[Telegram] 尝试不使用 parse_mode 重发纯文本…")
            data_plain = {"chat_id": target_chat, "text": content}
            response2, j2 = _telegram_post_with_retry(url, json_data=data_plain)
            if response2 is None:
                return False
            print(
                f"[Telegram] 重试 HTTP {response2.status_code}, "
                f"ok={j2.get('ok') if isinstance(j2, dict) else '?'}"
            )
            if isinstance(j2, dict) and j2.get("ok"):
                print("[Telegram] 纯文本发送成功")
                return True
            if isinstance(j2, dict):
                print(f"[Telegram] 重试仍失败: {j2.get('description', j2)!r}")

        return False
    except requests.RequestException as e:
        print(f"[Telegram] 请求异常（网络/超时）: {e}")
        return False
    except Exception as e:
        print(f"[Telegram] 发送失败: {e}")
        return False


def send_telegram_photo(
    photo_path: str,
    caption: str = "",
    *,
    use_markdown: bool = True,
    chat_id: str | None = None,
) -> bool:
    """发送 Telegram 图片；caption 为配图说明（与文本一起展示）。"""
    target_chat = (chat_id or TELEGRAM_CHAT_ID or "").strip()
    if not TELEGRAM_BOT_TOKEN or not target_chat:
        print("[Telegram] 配置未完成: 缺少 TELEGRAM_BOT_TOKEN 或 chat_id")
        return False
    path = (photo_path or "").strip()
    if not path or not os.path.isfile(path):
        print(f"[Telegram] 图片不存在: {photo_path!r}")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    cap = _telegram_caption_trim(caption)

    def _send(*, markdown: bool) -> bool:
        form = {"chat_id": target_chat}
        if cap:
            form["caption"] = cap
        if markdown and cap:
            form["parse_mode"] = "Markdown"
        try:
            with open(path, "rb") as f:
                response, j = _telegram_post_with_retry(
                    url,
                    form_data=form,
                    files={"photo": f},
                )
        except OSError as e:
            print(f"[Telegram] 读取图片失败: {e}")
            return False
        if response is None:
            return False
        print(
            f"[Telegram] sendPhoto HTTP {response.status_code}, "
            f"ok={j.get('ok') if isinstance(j, dict) else '?'}"
        )
        if isinstance(j, dict) and j.get("ok"):
            print(
                "[Telegram] 图片+配文发送成功, message_id=",
                j.get("result", {}).get("message_id"),
            )
            return True
        err_desc = (j or {}).get("description", "") if isinstance(j, dict) else ""
        err_code = (j or {}).get("error_code", "") if isinstance(j, dict) else ""
        print(f"[Telegram] sendPhoto 未成功: description={err_desc!r} error_code={err_code}")
        return False

    try:
        if _send(markdown=use_markdown and bool(cap)):
            return True
        if use_markdown and cap:
            print("[Telegram] sendPhoto 尝试不使用 parse_mode 重发…")
            return _send(markdown=False)
        return False
    except Exception as e:
        print(f"[Telegram] sendPhoto 失败: {e}")
        return False


def send_telegram_message_with_photo(
    content: str,
    photo_path: str | None = None,
    *,
    use_markdown: bool = True,
    chat_id: str | None = None,
) -> bool:
    """有图则 sendPhoto+caption，无图则 sendMessage。"""
    if photo_path and os.path.isfile(photo_path):
        return send_telegram_photo(
            photo_path,
            caption=content,
            use_markdown=use_markdown,
            chat_id=chat_id,
        )
    return send_telegram_message(content, chat_id=chat_id)


def format_tv_message(data: dict) -> str:
    """将 WebSocket message_received（TradingView 告警）格式化为 Telegram 文本（Markdown）。"""
    try:
        if data.get("type") == "message_received" and isinstance(data.get("message"), dict):
            msg = data["message"]
            metadata = msg.get("metadata") or {}
            title = msg.get("title") or msg.get("type") or "交易信号"
            lines = [f"📊 *{title}*", ""]
            if msg.get("content"):
                lines.append(str(msg["content"]))
                lines.append("")
            if metadata.get("ticker"):
                lines.append(f"💰 *交易对*: {metadata['ticker']}")
            if metadata.get("type"):
                lines.append(f"📈 *类型*: {metadata['type']}")
            if metadata.get("period"):
                lines.append(f"⏰ *周期*: {metadata['period']}")
            if metadata.get("time"):
                lines.append(f"⏰ *时间*: {metadata['time']}")
            if metadata.get("close"):
                lines.append(f"💵 *价格*: {metadata['close']}")
            if metadata.get("high"):
                lines.append(f"📈 *最高*: {metadata['high']}")
            if metadata.get("low"):
                lines.append(f"📉 *最低*: {metadata['low']}")
            if msg.get("sender"):
                lines.append("")
                lines.append(f"👤 *来源*: {msg['sender']}")
            return "\n".join(lines)
    except Exception as e:
        print(f"[format_tv_message] {e}", file=sys.stderr)
    return (
        "📨 *收到消息*\n\n"
        f"```json\n{json.dumps(data, ensure_ascii=False, indent=2)}\n```"
    )


def format_tv_signal_plain(data: dict) -> str:
    """
    TradingView 告警标准纯文本（用于 publish/signal，无 Markdown 星号）。
    示例::

        📊 MYXUSDT 看跌吞没

        触发信号

        💰 交易对: MYXUSDT
        ...
    """
    try:
        if data.get("type") == "message_received" and isinstance(data.get("message"), dict):
            msg = data["message"]
            metadata = msg.get("metadata") or {}
            title = (msg.get("title") or msg.get("type") or "交易信号").strip()
            lines = [f"📊 {title}", ""]
            if msg.get("content"):
                lines.append(str(msg["content"]).strip())
                lines.append("")
            if metadata.get("ticker"):
                lines.append(f"💰 交易对: {metadata['ticker']}")
            if metadata.get("type"):
                lines.append(f"📈 类型: {metadata['type']}")
            if metadata.get("period"):
                lines.append(f"⏰ 周期: {metadata['period']}")
            if metadata.get("time"):
                lines.append(f"⏰ 时间: {metadata['time']}")
            if metadata.get("close") is not None and metadata.get("close") != "":
                lines.append(f"💵 价格: {metadata['close']}")
            if metadata.get("high") is not None and metadata.get("high") != "":
                lines.append(f"📈 最高: {metadata['high']}")
            if metadata.get("low") is not None and metadata.get("low") != "":
                lines.append(f"📉 最低: {metadata['low']}")
            if msg.get("sender"):
                lines.append("")
                lines.append(f"👤 来源: {msg['sender']}")
            return "\n".join(lines)
    except Exception as e:
        print(f"[format_tv_signal_plain] {e}", file=sys.stderr)
    return f"📨 收到消息\n\n{json.dumps(data, ensure_ascii=False, indent=2)}"


def _warn_unexpected_square_publish(body: dict, *, requested_publish: bool) -> None:
    """客户端 publish=false 但服务端仍发广场时告警。"""
    if requested_publish:
        return
    for key in ("published", "publish", "did_publish", "square_published"):
        val = body.get(key)
        if val is True or (isinstance(val, str) and val.lower() in ("true", "1", "yes")):
            print(
                f"[publish][WARN] 请求 publish=false，但响应 {key}={val!r}；"
                "请检查 8000 服务是否忽略 publish 字段",
                file=sys.stderr,
            )
            return
    result = body.get("result")
    if isinstance(result, dict):
        for key in ("published", "publish", "did_publish"):
            val = result.get(key)
            if val is True:
                print(
                    f"[publish][WARN] 请求 publish=false，但响应 result.{key}=True；"
                    "请检查 8000 服务",
                    file=sys.stderr,
                )
                return


def publish_signal_to_hub(
    signal: str,
    *,
    publish_url: str | None = None,
    style_ids: list | None = None,
    strategy_id: str | None = None,
    compose_mode: str | None = None,
    publish: bool | None = None,
    timeout_sec: int | None = None,
) -> tuple[bool, dict | None]:
    """
    POST /api/publish/signal 派发到内容服务。
  环境变量:
    SIGNAL_PUBLISH_URL（默认 http://127.0.0.1:8000/api/publish/signal）
    SIGNAL_PUBLISH_STYLE_IDS（逗号分隔，默认 style_tianya_classic）
    SIGNAL_PUBLISH_STRATEGY_ID（默认 strategy_left_ambush）
    SIGNAL_PUBLISH_COMPOSE_MODE（默认 manual）
    SIGNAL_PUBLISH_DO_PUBLISH（默认 false；仅 publish 参数未传时读环境变量）
    """
    url = (publish_url or os.getenv(
        "SIGNAL_PUBLISH_URL", "http://127.0.0.1:8000/api/publish/signal"
    )).strip()
    if not url:
        print("[publish] SIGNAL_PUBLISH_URL 未配置", file=sys.stderr)
        return False, None

    raw_styles = os.getenv("SIGNAL_PUBLISH_STYLE_IDS", "style_tianya_classic").strip()
    styles = style_ids if style_ids is not None else [
        s.strip() for s in raw_styles.split(",") if s.strip()
    ]
    strategy = (
        strategy_id
        if strategy_id is not None
        else os.getenv("SIGNAL_PUBLISH_STRATEGY_ID", "strategy_left_ambush").strip()
    )
    mode = (
        compose_mode
        if compose_mode is not None
        else os.getenv("SIGNAL_PUBLISH_COMPOSE_MODE", "manual").strip() or "manual"
    )
    if publish is None:
        publish = os.getenv("SIGNAL_PUBLISH_DO_PUBLISH", "false").strip().lower() in (
            "1",
            "true",
            "yes",
        )
    timeout = timeout_sec if timeout_sec is not None else int(
        os.getenv("SIGNAL_PUBLISH_TIMEOUT_SEC", "60").strip() or "60"
    )

    payload = {
        "signal": signal,
        "style_ids": styles,
        "strategy_id": strategy,
        "compose_mode": mode,
        "publish": publish,
    }
    print(
        f"[publish] POST {url} strategy={strategy!r} styles={styles} "
        f"publish={publish} signal_len={len(signal)}",
        file=sys.stderr,
    )
    if not publish:
        print("[publish] publish=false：仅润色/预览，不会发布到广场", file=sys.stderr)
    try:
        session = requests.Session()
        session.trust_env = False
        r = session.post(
            url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        if not r.ok:
            print(
                f"[publish] HTTP {r.status_code}: {(r.text or '')[:500]}",
                file=sys.stderr,
            )
            return False, None
        print(f"[publish] 已派发 strategy={strategy} styles={styles}")
        body: dict | None = None
        try:
            body = r.json()
            from promat_publish import describe_publish_response

            print("[publish] 响应（润色正文已分行）:\n" + describe_publish_response(body))
            if isinstance(body, dict):
                _warn_unexpected_square_publish(body, requested_publish=bool(publish))
        except Exception:
            print(f"[publish] 响应: {(r.text or '')[:500]}")
        return True, body if isinstance(body, dict) else None
    except requests.RequestException as e:
        print(f"[publish] 请求失败: {e}", file=sys.stderr)
        return False, None


# 第3部分：格式化消息和统一发送接口
def format_analysis_message(analysis_results: dict):
    """格式化分析结果为消息（支持多币种）"""
    message = "[REPORT] 加密货币交易策略分析报告\n\n"
    
    for symbol, result in analysis_results.items():
        message += f"【{symbol}】\n"
        if result.get('status') == 'success':
            raw = result.get("analysis") or ""
            parsed = extract_json_from_gemini_text(raw) if raw else None
            if parsed is not None:
                message += json.dumps(parsed, ensure_ascii=False, indent=2) + "\n\n"
            else:
                message += f"{raw}\n\n"
        else:
            message += f"[ERROR] 分析失败: {result.get('error', '未知错误')}\n\n"
    
    return message

def send_notification(content: str):
    """统一发送通知（尝试所有可用渠道）"""
    success_count = 0
    
    if send_dingtalk_message(content):
        success_count += 1
        print("[OK] 钉钉消息发送成功")
    
    if send_telegram_message(content):
        success_count += 1
        print("[OK] Telegram消息发送成功")
    
    if success_count == 0:
        print("[WARNING] 所有通知渠道都未配置或发送失败")
    
    return success_count > 0
