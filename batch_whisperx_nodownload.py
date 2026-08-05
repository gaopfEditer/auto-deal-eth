"""
批量流式转写脚本 - 无需下载，直接获取 URL 音视频流并转写中文字稿

技术方案：yt-dlp 获取真实流地址 → FFmpeg 管道转 16k 单声道 PCM → faster-whisper 推理
配置文件：未传 --url/--link/--item/--content-id 时读取 videos.json（与 batch_whisperx 共用）；
  --item/--json 可直接传 videos.json 同结构的 JSON 对象/数组；
  传了 --url/--link 则仅从命令行取任务；仅传 --name 时从 videos.json 按 name 筛选；
  --content-id 会拼成 https://www.binance.com/zh-CN/square/audio/replay?id={contentId}，
  输出文件命名为「作者_年月日时分秒.txt」（如 颜驰Bit_20260804221530.txt）

依赖：yt-dlp, ffmpeg, faster-whisper, numpy, requests, websockets
  pip install -r requirements-whisperx-nodownload.txt
  # 或：pip install yt-dlp faster-whisper numpy requests websockets

若报错 cudnn_ops64_9.dll / cudnnCreateTensorDescriptor：说明缺 cuDNN 或未加入 PATH，
  可加 --cpu 强制 CPU，或设置环境变量 USE_CPU=1
  PowerShell: python batch_whisperx_nodownload.py --cpu
"""
import argparse
import asyncio
import json
import os
import re
import socket
import sys
import urllib.parse
import urllib.request
import shutil
import subprocess
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np
import websockets


def get_ffmpeg_path() -> str:
    """解析 ffmpeg 可执行路径（PATH 或常见安装位置）。"""
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    for path in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    raise FileNotFoundError(
        "未找到 ffmpeg。请安装：macOS 用 brew install ffmpeg，Windows 从 https://ffmpeg.org 下载并加入 PATH"
    )


def _get_http_proxy_url() -> str:
    """
    与 requests/urllib 一致的代理发现顺序。
    macOS 系统代理（如 Clash 127.0.0.1:7890）常只在 urllib.request.getproxies() 里，不在环境变量中。
    """
    url = os.environ.get("FFMPEG_HTTP_PROXY", "").strip()
    if not url:
        for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            url = os.environ.get(k, "").strip()
            if url:
                break
    if not url:
        for k in ("ALL_PROXY", "all_proxy"):
            url = os.environ.get(k, "").strip()
            if url:
                break
    if not url:
        try:
            proxies = urllib.request.getproxies()
            url = (proxies.get("https") or proxies.get("http") or "").strip()
        except Exception:
            pass
    return url


def _ffmpeg_proxy_cli_args() -> list[str]:
    """
    FFmpeg 拉取 https 输入时不会自动使用 HTTPS_PROXY（与 curl 不同），需显式传入 -http_proxy / -socks_proxy。
    读取顺序：FFMPEG_HTTP_PROXY → 环境变量 → urllib.request.getproxies()（系统/Clash 代理）。
    """
    url = _get_http_proxy_url()
    if not url:
        return []
    low = url.lower()
    if low.startswith("socks5://") or low.startswith("socks://"):
        return ["-socks_proxy", url]
    return ["-http_proxy", url]


def _is_hostname_dns_blocked(hostname: str) -> bool:
    """部分网络/去广告 DNS 会把 bin.bnbstatic.com 解析到 0.0.0.0，直连 FFmpeg 会 Connection refused。"""
    try:
        ip = socket.gethostbyname(hostname)
    except OSError:
        return True
    return ip in ("0.0.0.0", "127.0.0.1")


def _warn_if_bnbstatic_needs_proxy(stream_url: str) -> None:
    global _ffmpeg_proxy_logged
    if "bnbstatic.com" not in stream_url:
        return
    host = urllib.parse.urlparse(stream_url).hostname or ""
    if not host or not _is_hostname_dns_blocked(host):
        return
    proxy = _get_http_proxy_url()
    if proxy:
        if not _ffmpeg_proxy_logged:
            _ffmpeg_proxy_logged = True
            print(
                f">>> 检测到 {host} 被本地 DNS 拦截（解析到 0.0.0.0），"
                f"FFmpeg 将通过代理拉流: {proxy}",
                flush=True,
            )
        return
    raise RuntimeError(
        f"无法直连 {host}：本地 DNS 将其解析为 0.0.0.0（常见于去广告 DNS），"
        "而 FFmpeg 未配置代理。\n"
        "处理：开启 Clash/V2Ray 系统代理，或执行 export HTTPS_PROXY=http://127.0.0.1:7890 后重试。"
    )


import requests
import yt_dlp
from faster_whisper import WhisperModel

# 配置文件路径（与 batch_whisperx 共用）
CONFIG_PATH = Path("videos.json")
# 本脚本所在目录（Cookie 等文件放这里时，不依赖运行时的 cwd）
_SCRIPT_DIR = Path(__file__).resolve().parent

# YouTube Cookie（Netscape 格式）：优先 YOUTUBE_COOKIES_FILE，其次项目根 youtube_cookies.txt，再其次本路径（与 batch_or_single_download 一致）
YOUTUBE_COOKIES_FILE_DEFAULT = Path(r"D:\frontend\main\tools\youtube_cookies.txt")
# 主配置失败时回退；默认同脚本目录下 macstudioyoutube.com_cookies.txt（可用 YOUTUBE_MACSTUDIO_COOKIES_FILE 覆盖为绝对路径）
_macstudio_env = os.environ.get("YOUTUBE_MACSTUDIO_COOKIES_FILE", "").strip()
YOUTUBE_MACSTUDIO_COOKIES_FILE = (
    Path(_macstudio_env).expanduser()
    if _macstudio_env
    else (_SCRIPT_DIR / "macstudioyoutube.com_cookies.txt")
)

# 输出目录
TRANSCRIPT_DIR = Path("subtitles")
LOG_DIR = Path("logs")
OUTPUT_DIR = Path("output")
REALTIME_HOST = "127.0.0.1"
REALTIME_PORT = 3333

# FFmpeg 代理提示只打一次（stream_to_audio_array）
_ffmpeg_proxy_logged = False
# YouTube Cookie 文件缺字段警告只打一次
_youtube_cookie_thin_warned = False

# faster-whisper 参数
WHISPER_MODEL = "large-v3-turbo"
WHISPER_LANGUAGE = "zh"
WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE_TYPE = "int8"
_whisper_device_configured = False


def _detect_device(*, force_cpu: bool = False) -> str:
    """默认优先 GPU（CUDA）；--cpu 或 USE_CPU=1 时用 CPU。WHISPER_DEVICE 环境变量可显式指定。"""
    if force_cpu:
        return "cpu"
    if os.environ.get("USE_CPU", "").strip().lower() in ("1", "true", "yes"):
        return "cpu"
    env_dev = os.environ.get("WHISPER_DEVICE", "").strip().lower()
    if env_dev:
        return env_dev
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda"
    except Exception:
        pass
    return "cpu"


def _compute_type_for_device(device: str) -> str:
    use_float16 = os.environ.get("USE_FLOAT16", "").strip().lower() in ("1", "true", "yes")
    if device == "cuda" and use_float16:
        return "float16"
    return "int8"


def configure_whisper_device(*, force_cpu: bool = False) -> None:
    """在 main 解析 --cpu 后调用；未调用时 get_whisper_model 首次加载前会自动 configure（默认 GPU）。"""
    global WHISPER_DEVICE, WHISPER_COMPUTE_TYPE, _whisper_device_configured, _whisper_model
    WHISPER_DEVICE = _detect_device(force_cpu=force_cpu)
    WHISPER_COMPUTE_TYPE = _compute_type_for_device(WHISPER_DEVICE)
    _whisper_device_configured = True
    _whisper_model = None

# 通义千问配置（与 batch_whisperx 相同）
QWEN_API_KEY = os.environ.get("QWEN_API_KEY", "sk-40fc3963ae51439db02c07d7b9995042")
QWEN_ENDPOINT = "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation"
QWEN_MODEL = "qwen-turbo"
# 整理全文：单段 max_tokens 再大也可能不够整期口播，故按字数切块多次调用再拼接（见 _split_plain_text_into_refine_chunks）
QWEN_REFINE_MAX_TOKENS = int(os.environ.get("QWEN_REFINE_MAX_TOKENS", "8192"))
QWEN_REFINE_CHUNK_CHARS = int(os.environ.get("QWEN_REFINE_CHUNK_CHARS", "5000"))
QWEN_SUMMARY_MAX_TOKENS = int(os.environ.get("QWEN_SUMMARY_MAX_TOKENS", "1024"))
# 摘要只读整理后全文开头若干字（主旨多在前部，避免把超长正文塞进摘要接口）
QWEN_SUMMARY_SOURCE_CHARS = int(os.environ.get("QWEN_SUMMARY_SOURCE_CHARS", "2000"))
QWEN_REFINE_TIMEOUT_SEC = int(os.environ.get("QWEN_REFINE_TIMEOUT_SEC", "300"))

# 全局模型实例（避免每次重复加载）
_whisper_model: WhisperModel | None = None


def _is_cuda_runtime_missing_error(e: BaseException) -> bool:
    msg = str(e).lower()
    keys = (
        "cublas64_12.dll",
        "cudnn",
        "cublas",
        "cuda runtime",
        "cannot be loaded",
        "is not found",
    )
    return any(k in msg for k in keys)


def get_whisper_model() -> WhisperModel:
    global _whisper_model, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE, _whisper_device_configured
    if not _whisper_device_configured:
        configure_whisper_device(force_cpu=False)
    if _whisper_model is None:
        print(f"\n>>> 加载 Whisper 模型: {WHISPER_MODEL} ({WHISPER_DEVICE}, {WHISPER_COMPUTE_TYPE})")
        try:
            _whisper_model = WhisperModel(
                WHISPER_MODEL,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
            )
        except Exception as e:
            if WHISPER_DEVICE == "cuda" and _is_cuda_runtime_missing_error(e):
                print("⚠ CUDA 运行库缺失，自动回退到 CPU 模式继续本次任务。")
                WHISPER_DEVICE = "cpu"
                WHISPER_COMPUTE_TYPE = "int8"
                _whisper_model = WhisperModel(
                    WHISPER_MODEL,
                    device=WHISPER_DEVICE,
                    compute_type=WHISPER_COMPUTE_TYPE,
                )
            else:
                raise
    return _whisper_model


def load_config():
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"配置文件不存在: {CONFIG_PATH}")
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _default_name_from_url(url: str, index: int) -> str:
    """从 URL 生成可用作 output 文件名的片段（无 --name 时使用）。"""
    try:
        p = urllib.parse.urlparse(url)
        seg = (p.path or "").rstrip("/").split("/")[-1] or "video"
        seg = seg.split("?")[0]
        seg = re.sub(r"[^\w\u4e00-\u9fff\-]", "_", seg).strip("_")
        if not seg:
            seg = f"url_{index}"
        return seg[:120]
    except Exception:
        return f"url_{index}"


def build_items_from_cli_urls(
    urls: list[str],
    names: list[str],
    titles: list[str] | None = None,
    shottitles: list[str] | None = None,
) -> list[dict]:
    """
    由命令行 --url/--link / --name 构建任务列表；字段与 videos.json 条目对齐。
    name / title / shottitle 与 url 按下标对齐，缺省 name 时从 URL 推断。
    """
    titles = titles or []
    shottitles = shottitles or []
    items: list[dict] = []
    for i, link in enumerate(urls):
        link = (link or "").strip()
        if not link:
            continue
        if i < len(names) and (names[i] or "").strip():
            name = (names[i] or "").strip()
        else:
            name = _default_name_from_url(link, i + 1)
        item: dict = {"name": name, "link": link}
        if i < len(titles) and (titles[i] or "").strip():
            item["title"] = (titles[i] or "").strip()
        if i < len(shottitles) and (shottitles[i] or "").strip():
            item["shottitle"] = (shottitles[i] or "").strip()
        items.append(item)
    return items


def filter_config_by_names(config: list, names: list[str]) -> list[dict]:
    """从 videos.json 列表中按 name 筛选（顺序与 --name 一致；允许重复名取首次）。"""
    by_name: dict[str, dict] = {}
    for item in config:
        if not isinstance(item, dict):
            continue
        n = (item.get("name") or "").strip()
        if n and n not in by_name:
            by_name[n] = item
    selected: list[dict] = []
    missing: list[str] = []
    for raw in names:
        n = (raw or "").strip()
        if not n:
            continue
        hit = by_name.get(n)
        if hit is None:
            missing.append(n)
        else:
            selected.append(hit)
    if missing:
        raise ValueError(
            "videos.json 中找不到这些 name: " + ", ".join(missing)
            + "；可用 name: "
            + (", ".join(by_name.keys()) if by_name else "(空)")
        )
    return selected


def _normalize_task_payload(payload) -> list[dict]:
    """将 JSON 入参规范为 [{name, link, ...}, ...]（与 WebSocket / videos.json 条目一致）。"""
    raw_items: list[dict] = []
    if isinstance(payload, list):
        raw_items = [x for x in payload if isinstance(x, dict)]
    elif isinstance(payload, dict):
        if any(k in payload for k in ("name", "link", "content_id", "contentId", "url")):
            raw_items = [payload]
        else:
            for key in ("videos", "data", "items"):
                v = payload.get(key)
                if isinstance(v, list):
                    raw_items = [x for x in v if isinstance(x, dict)]
                    break
                if isinstance(v, dict):
                    raw_items = [v]
                    break
    out: list[dict] = []
    for it in raw_items:
        try:
            out.append(normalize_task_item(it))
        except ValueError as e:
            print(f">>> 跳过无效任务: {e}", flush=True)
    return out


def parse_cli_json_items(raw_list: list[str]) -> list[dict]:
    """
    解析 --item / --json 入参：
    - JSON 对象：{"name","link","title","shottitle"}
    - JSON 数组：[{...}, ...]
    - 也可传 .json 文件路径
    """
    items: list[dict] = []
    for i, raw in enumerate(raw_list or []):
        text = (raw or "").strip()
        if not text:
            continue
        path = Path(text)
        if path.is_file() and path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                raise ValueError(f"--item 第 {i + 1} 个参数读取 JSON 文件失败 ({path}): {e}") from e
        else:
            try:
                payload = json.loads(text)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"--item 第 {i + 1} 个参数不是合法 JSON（对象/数组）或 .json 文件路径: {e}"
                ) from e
        normalized = _normalize_task_payload(payload)
        if not normalized:
            raise ValueError(
                f"--item 第 {i + 1} 个参数结构无效，需为 "
                '{"name","link",...} 或 [{...}, ...] 或含 videos/data/items 的对象'
            )
        for item in normalized:
            name = (item.get("name") or "").strip()
            link = (item.get("link") or "").strip()
            if not name or not link:
                raise ValueError(
                    f"--item 第 {i + 1} 个参数缺少 name/link: {item!r}"
                )
            out = dict(item)
            out["name"] = name
            out["link"] = link
            items.append(out)
    return items


def ensure_dirs():
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _is_youtube_link(link: str) -> bool:
    low = link.lower()
    return "youtube.com" in low or "youtu.be" in low or "m.youtube.com" in low


def _is_binance_square_link(link: str) -> bool:
    low = (link or "").lower()
    return "binance.com" in low and "/square/" in low


def _parse_binance_square_content_id(link: str) -> str | None:
    """从币安广场链接解析内容 id，如 square/audio/replay?id=…、square/post/{id}。"""
    raw = (link or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return raw
    parsed = urllib.parse.urlparse(raw)
    if "binance.com" not in parsed.netloc.lower() or "/square/" not in parsed.path.lower():
        # 允许只传 query：id=4396… 或 contentId=…
        qs = urllib.parse.parse_qs(parsed.query)
        for key in ("id", "contentId", "content_id"):
            vals = qs.get(key)
            if vals and str(vals[0]).strip().isdigit():
                return str(vals[0]).strip()
        m0 = re.search(r"(?:^|[?&])(?:id|contentId|content_id)=(\d+)", raw, re.I)
        return m0.group(1) if m0 else None
    qs = urllib.parse.parse_qs(parsed.query)
    for key in ("id", "contentId", "content_id"):
        vals = qs.get(key)
        if vals and str(vals[0]).strip().isdigit():
            return str(vals[0]).strip()
    m = re.search(
        r"/square/(?:post|audio|video|live)(?:/replay)?/(\d+)",
        parsed.path,
        re.I,
    )
    if m:
        return m.group(1)
    return None


def build_binance_audio_replay_url(content_id: str, *, locale: str | None = None) -> str:
    """
    contentId → 语音空间回放页。
    例：43965784467818 → https://www.binance.com/zh-CN/square/audio/replay?id=43965784467818
    """
    cid = str(content_id or "").strip()
    if not cid.isdigit():
        raise ValueError(f"无效 contentId（需纯数字）: {content_id!r}")
    loc = (locale or os.environ.get("BINANCE_SQUARE_LANG", "zh-CN") or "zh-CN").strip()
    return f"https://www.binance.com/{loc}/square/audio/replay?id={cid}"


def _sanitize_filename_part(s: str, *, max_len: int = 80) -> str:
    text = (s or "").strip()
    text = re.sub(r'[\\/:*?"<>|\s]+', "_", text)
    text = re.sub(r"_+", "_", text).strip("._")
    return (text or "unknown")[:max_len]


def make_output_name_author_now(author: str, *, when: datetime | None = None) -> str:
    """输出名：作者 + 当日年月日时分秒，如 颜驰Bit_20260804221530。"""
    dt = when or datetime.now()
    return f"{_sanitize_filename_part(author)}_{dt.strftime('%Y%m%d%H%M%S')}"


def _author_from_binance_detail(data: dict) -> str:
    if not isinstance(data, dict):
        return ""
    for key in (
        "authorNickName",
        "authorNickname",
        "nickName",
        "nickname",
        "displayName",
        "authorName",
        "username",
    ):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    author = data.get("author")
    if isinstance(author, dict):
        for key in ("nickname", "nickName", "displayName", "name", "username"):
            v = author.get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
    if isinstance(author, str) and author.strip():
        return author.strip()
    return ""


def normalize_task_item(item: dict, *, force_author_ts_name: bool | None = None) -> dict:
    """
    规范化单条任务：
    - 有 content_id / contentId / 纯数字 id → 拼 audio/replay?id=… 链接
    - 输出 name 默认改为「作者_年月日时分秒」
    """
    if not isinstance(item, dict):
        raise ValueError(f"任务必须是对象: {item!r}")
    out = dict(item)
    cid = str(
        out.get("content_id")
        or out.get("contentId")
        or out.get("contentid")
        or ""
    ).strip()
    link = str(out.get("link") or out.get("url") or "").strip()

    if not cid and link.isdigit():
        cid = link
        link = ""
    if not cid and link:
        cid = _parse_binance_square_content_id(link) or ""

    use_cid_naming = bool(cid)
    if force_author_ts_name is not None:
        use_cid_naming = bool(force_author_ts_name)

    if cid:
        out["content_id"] = cid
        out["link"] = build_binance_audio_replay_url(cid)
        author = str(
            out.get("author")
            or out.get("author_name")
            or out.get("nick")
            or out.get("nickname")
            or ""
        ).strip()
        if not author:
            try:
                detail = _binance_square_fetch_content_detail(cid)
                author = _author_from_binance_detail(detail)
            except Exception as e:
                print(f">>> contentId={cid} 拉取作者名失败（将用兜底名）: {e}", flush=True)
        if not author:
            author = str(
                out.get("author_slug") or out.get("name") or f"binance_{cid}"
            ).strip()
        out["author"] = author
        if use_cid_naming or not str(out.get("name") or "").strip():
            out["name"] = make_output_name_author_now(author)
        print(
            f">>> contentId={cid} → {out['link']} ；输出名={out['name']}",
            flush=True,
        )
    else:
        if not link:
            raise ValueError(f"任务缺少 link/url/content_id: {item}")
        out["link"] = link
        if not str(out.get("name") or "").strip():
            out["name"] = _default_name_from_url(link, 1)
    return out


def build_items_from_content_ids(
    content_ids: list[str],
    authors: list[str] | None = None,
) -> list[dict]:
    """由 --content-id / --author 构建任务（作者可缺省，稍后从 API 补）。"""
    authors = authors or []
    items: list[dict] = []
    for i, raw in enumerate(content_ids):
        cid = str(raw or "").strip()
        if not cid:
            continue
        parsed = _parse_binance_square_content_id(cid) or cid
        item: dict = {"content_id": parsed}
        if i < len(authors) and (authors[i] or "").strip():
            item["author"] = (authors[i] or "").strip()
        items.append(normalize_task_item(item))
    return items


def _cookie_header_from_file(cookie_path: str, domain_suffix: str = "binance.com") -> str:
    """Netscape cookies.txt → Cookie 请求头；若已是单行 Cookie 则原样返回。"""
    try:
        text = Path(cookie_path).read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        return ""
    if not text:
        return ""
    if not text.lstrip().startswith("#"):
        return text
    pairs: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        domain, _flag, _path, _secure, _exp, name, value = parts[:7]
        if domain_suffix in domain.lstrip("."):
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _binance_square_api_headers() -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": "https://www.binance.com/",
        "clienttype": "web",
    }
    lang = os.environ.get("BINANCE_SQUARE_LANG", "zh-CN").strip() or "zh-CN"
    headers["lang"] = lang
    cookie_file = os.environ.get("BINANCE_COOKIES_FILE", "").strip()
    if not cookie_file:
        for candidate in (_SCRIPT_DIR / "binance_cookies.txt", CONFIG_PATH.parent / "binance_cookies.txt"):
            if candidate.is_file():
                cookie_file = str(candidate.resolve())
                break
    if cookie_file and os.path.isfile(cookie_file):
        cookie_hdr = _cookie_header_from_file(cookie_file, "binance.com")
        if cookie_hdr:
            headers["Cookie"] = cookie_hdr
    return headers


def _binance_square_fetch_content_detail(content_id: str) -> dict:
    """调用币安广场内部接口（yt-dlp 无 Binance extractor）。"""
    api_tpl = os.environ.get(
        "BINANCE_SQUARE_DETAIL_API",
        "https://www.binance.com/bapi/composite/v3/friendly/pgc/special/content/detail/{id}",
    ).strip()
    url = api_tpl.format(id=content_id)
    resp = requests.get(url, headers=_binance_square_api_headers(), timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"币安广场内容接口 HTTP {resp.status_code}: {resp.text[:300]}")
    payload = resp.json()
    if payload.get("code") != "000000":
        raise RuntimeError(
            f"币安广场内容接口返回异常 code={payload.get('code')!r}: {payload.get('message') or payload}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"币安广场内容接口无 data 字段: {payload}")
    return data


def _binance_square_is_audiospace_content(data: dict, link: str = "") -> bool:
    """语音空间 / Audio Space 帖子（/square/audio），完整录音在 spaceLiveReplayLink，不是 livePullUrls。"""
    if "/square/audio" in link.lower():
        return True
    if data.get("extraFeature") == "SPACE_LIVE":
        return True
    if data.get("liveType") == 5:
        return True
    return False


def _binance_square_parse_duration(data: dict) -> float | None:
    vo = data.get("videoVO") if isinstance(data.get("videoVO"), dict) else {}
    for src in (vo, data):
        for key in ("spaceLiveReplayDuration", "videoTimeSeconds", "liveDurationTime"):
            raw = src.get(key)
            if raw is None:
                continue
            try:
                sec = float(raw)
            except (TypeError, ValueError):
                continue
            if sec > 0:
                return sec
    return None


def _binance_square_vod_stream_candidates(data: dict) -> list[str]:
    """点播/回放 URL（完整录音），不含 bblivestream 实时流。"""
    vo = data.get("videoVO") if isinstance(data.get("videoVO"), dict) else {}
    candidates: list[str] = []
    for src in (data, vo):
        for key in (
            "spaceLiveReplayLink",
            "videoLink1080p",
            "videoLink720p",
            "videoLink480p",
            "videoLink",
        ):
            u = src.get(key)
            if isinstance(u, str) and u.strip().startswith(("http://", "https://")):
                candidates.append(u.strip())
    seen: set[str] = set()
    out: list[str] = []
    for u in candidates:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _is_binance_live_pull_url(url: str) -> bool:
    """bblivestream 的 /live/ 地址为实时窗口流，FFmpeg 会一直等待导致卡住。"""
    low = url.lower()
    return "bblivestream.com" in low and "/live/" in low


def _binance_square_pick_vod_stream(data: dict) -> tuple[str, float | None] | None:
    duration = _binance_square_parse_duration(data)
    for u in _binance_square_vod_stream_candidates(data):
        return (u, duration)
    return None


def _binance_square_pick_stream(data: dict, *, allow_live_pull: bool = True) -> tuple[str, float | None]:
    """从内容详情里挑选 FFmpeg 可拉的音/视频 URL 与时长（秒）。"""
    picked = _binance_square_pick_vod_stream(data)
    if picked is not None:
        return picked

    if not allow_live_pull:
        raise RuntimeError(
            "币安广场语音空间尚无完整回放地址（spaceLiveReplayLink 为空），"
            f" contentId={data.get('id')!r}。"
        )

    duration = _binance_square_parse_duration(data)
    live = data.get("livePullUrls") if isinstance(data.get("livePullUrls"), dict) else {}
    for key in ("flvPlayUrl", "hlsPlayUrl"):
        u = live.get(key)
        if isinstance(u, str) and u.strip().startswith(("http://", "https://")):
            return (u.strip(), duration)

    raise RuntimeError(
        "币安广场内容未找到可播放的音视频地址。"
        f" contentId={data.get('id')!r}, liveStatus={data.get('liveStatus')!r}, "
        f"videoProcessStatus={data.get('videoProcessStatus')!r}。"
        " 常见原因：回放转码未完成（spaceLiveReplayLink 为空），或需配置 BINANCE_COOKIES_FILE。"
    )


def _binance_square_fetch_detail_with_replay(link: str, content_id: str) -> dict:
    """
    语音空间完整录音在 spaceLiveReplayLink（VOD m3u8），生成前 API 只有 livePullUrls，
    后者会让 FFmpeg 无限等待。对 Audio Space 轮询直到回放地址就绪。
    """
    wait_sec = int(os.environ.get("BINANCE_SQUARE_REPLAY_WAIT_SEC", "300"))
    poll_sec = max(5, int(os.environ.get("BINANCE_SQUARE_REPLAY_POLL_SEC", "15")))
    audiospace = False
    deadline = time.time() + max(0, wait_sec)
    attempt = 0
    last_detail: dict | None = None

    while True:
        attempt += 1
        detail = _binance_square_fetch_content_detail(content_id)
        last_detail = detail
        if not audiospace:
            audiospace = _binance_square_is_audiospace_content(detail, link)

        picked = _binance_square_pick_vod_stream(detail)
        if picked is not None:
            if attempt > 1:
                url, dur = picked
                print(
                    f"    币安广场回放地址已就绪（第 {attempt} 次查询，时长约 {dur:.0f} 秒）"
                    if dur
                    else f"    币安广场回放地址已就绪（第 {attempt} 次查询）",
                    flush=True,
                )
            return detail

        if audiospace:
            if time.time() >= deadline:
                break
            print(
                "    等待币安广场完整回放生成（spaceLiveReplayLink）…"
                f" 第 {attempt} 次，尚未就绪，{poll_sec}s 后重试",
                flush=True,
            )
            time.sleep(poll_sec)
            continue

        # 非语音空间：允许回退到 livePullUrls
        _binance_square_pick_stream(detail, allow_live_pull=True)
        return detail

    assert last_detail is not None
    raise RuntimeError(
        f"币安广场语音空间回放尚未生成（contentId={content_id}）。"
        f" 已等待 {wait_sec} 秒，spaceLiveReplayLink 仍为空。"
        " 这是已结束的 Audio Space 录音，平台需先转码；请稍后重试，"
        "或增大 BINANCE_SQUARE_REPLAY_WAIT_SEC。"
        " 切勿使用 livePullUrls 实时流转写，会导致 FFmpeg 卡住且内容不完整。"
    )


def _get_binance_square_stream_url(link: str) -> tuple[str, float | None]:
    content_id = _parse_binance_square_content_id(link)
    if not content_id:
        raise RuntimeError(
            f"无法从币安广场链接解析内容 id（需 square/audio?id=… 或 square/post/{{id}} 等形式）: {link}"
        )
    detail = _binance_square_fetch_detail_with_replay(link, content_id)
    audiospace = _binance_square_is_audiospace_content(detail, link)
    picked = _binance_square_pick_vod_stream(detail)
    if picked is None:
        stream_url, duration = _binance_square_pick_stream(detail, allow_live_pull=not audiospace)
    else:
        stream_url, duration = picked
    title = (detail.get("title") or "").strip()
    if title:
        print(f"    币安广场: {title[:80]}{'…' if len(title) > 80 else ''}", flush=True)
    if duration and duration > 0:
        print(f"    音频时长约 {duration:.0f} 秒（来自回放/点播地址）", flush=True)
    elif _is_binance_live_pull_url(stream_url):
        print(
            "    警告: 当前仅有 bblivestream 实时流地址，转写可能不完整；"
            "建议等待 spaceLiveReplayLink 生成后重试。",
            flush=True,
        )
    return (stream_url, duration)


def _youtube_cookie_hint() -> str:
    return (
        "YouTube 机器人验证仍失败时，请逐项排查：\n"
        "  · 另一台 Mac 正常、这台不行：多半是出口 IP/网络环境不同（公司网、VPN、机房）导致风控；或本机 yt-dlp 版本较旧。两台都执行 pip install -U yt-dlp 后再比。\n"
        "  · 仅 Cookie 文件失败时：在本机 Chrome 已登录 YouTube 的前提下，完全退出 Chrome 后执行：\n"
        "      export YOUTUBE_ON_BOT_TRY_BROWSER=chrome\n"
        "    脚本会在文件 Cookie 仍报 bot 时改从浏览器读 Cookie（与另一台「浏览器里能用」的现象一致）。\n"
        "  · 也可全程用浏览器：export YOUTUBE_COOKIES_FROM_BROWSER=chrome（不要用同时存在的旧 cookies 文件覆盖）。\n"
        "  · 扩展导出的文件易过期；Arc/Brave 请用 brave 或 chromium，勿写 chrome。\n"
        "详见：https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-cookies-to-yt-dlp\n"
        "导出说明：https://github.com/yt-dlp/yt-dlp/wiki/Extractors#exporting-youtube-cookies\n"
    )


def _youtube_auth_label(opts: dict) -> str:
    """便于排查的 Cookie 来源描述（不打印 Cookie 内容）。"""
    if opts.get("cookiefile"):
        return f"文件 {opts['cookiefile']}"
    if opts.get("cookiesfrombrowser"):
        cfb = opts["cookiesfrombrowser"]
        if isinstance(cfb, (list, tuple)):
            return "浏览器 " + ":".join(str(x) for x in cfb if x is not None)
        return f"浏览器 {cfb!r}"
    return "未配置（YouTube 多半会报 Sign in / bot）"


def _is_youtube_bot_or_auth_error(err: BaseException) -> bool:
    s = str(err).lower()
    return (
        "sign in" in s
        or "not a bot" in s
        or ("bot" in s and "youtube" in s)
        or "cookies" in s
        or "login required" in s
    )


def _is_youtube_networkish_error(err: BaseException) -> bool:
    """连接/超时/SSL 等，主 Cookie 失败时可换用备用 Cookie 再试。"""
    s = str(err).lower()
    return any(
        x in s
        for x in (
            "timed out",
            "timeout",
            "connection refused",
            "connection reset",
            "network is unreachable",
            "no route to host",
            "temporary failure",
            "name or service not known",
            "ssl",
            "eof occurred",
            "unable to download webpage",
            "errno",
            "10054",
            "10060",
        )
    )


def _youtube_should_try_macstudio_fallback(err: BaseException) -> bool:
    return _is_youtube_bot_or_auth_error(err) or _is_youtube_networkish_error(err)


def _youtube_already_uses_cookie_path(opts: dict, path: Path) -> bool:
    cf = opts.get("cookiefile")
    if not cf or not path.is_file():
        return False
    try:
        return Path(cf).resolve() == path.resolve()
    except OSError:
        return os.path.abspath(str(cf)) == os.path.abspath(str(path))


def _youtube_try_extraction_with_clients(
    link: str, ydl_opts: dict
) -> tuple[tuple[str, float | None] | None, BaseException | None]:
    """依次尝试各 player_client；成功返回 (结果, None)，失败返回 (None, last_error)。"""
    last_err: BaseException | None = None
    for clients in _youtube_player_client_variants(ydl_opts):
        opts_try = _youtube_opts_with_player_client(ydl_opts, clients)
        try:
            return (_extract_stream_url_with_ydl(link, opts_try), None)
        except Exception as e:
            last_err = e
            if _is_youtube_bot_or_auth_error(e):
                continue
            if _is_youtube_networkish_error(e):
                continue
            if _is_retryable_format_error(e):
                continue
            return (None, e)
    return (None, last_err)


def _youtube_opts_with_macstudio_cookie(base_plain: dict, mac_path: Path) -> dict:
    """忽略浏览器 Cookie，强制使用 macstudio 导出文件。"""
    opts = _merge_youtube_ydl_opts({**base_plain})
    opts["cookiefile"] = str(mac_path.resolve())
    opts.pop("cookiesfrombrowser", None)
    return opts


def _youtube_opts_browser_only(base_plain: dict, browser_spec: str) -> dict:
    """不使用 cookie 文件，仅从本机浏览器读 Cookie（与 yt-dlp --cookies-from-browser 一致）。"""
    opts = {**base_plain}
    opts.pop("cookiefile", None)
    spec = browser_spec.strip()
    parts = spec.split(":", 1)
    name = parts[0].strip()
    if len(parts) > 1 and parts[1].strip():
        opts["cookiesfrombrowser"] = (name, parts[1].strip())
    else:
        opts["cookiesfrombrowser"] = (name,)
    pc_env = os.environ.get("YOUTUBE_PLAYER_CLIENT", "").strip()
    yt: dict = {}
    if pc_env:
        yt["player_client"] = [p.strip() for p in pc_env.split(",") if p.strip()]
    else:
        yt["player_client"] = ["android", "web", "ios"]
    opts["extractor_args"] = {"youtube": yt}
    return opts


def _warn_if_youtube_cookiefile_thin(cookie_path: str) -> None:
    """
    yt-dlp 自己导出的 cookies 往往不含 LOGIN_INFO 等字段，YouTube 仍会报 Sign in / bot。
    只提示一次，避免刷屏。
    """
    global _youtube_cookie_thin_warned
    if _youtube_cookie_thin_warned or not cookie_path or not os.path.isfile(cookie_path):
        return
    try:
        text = Path(cookie_path).read_text(encoding="utf-8", errors="ignore")[:65536]
    except OSError:
        return
    if "LOGIN_INFO" in text:
        return
    _youtube_cookie_thin_warned = True
    print(
        ">>> 警告: 当前 Cookie 文件里未见 LOGIN_INFO（常见于仅用 yt-dlp 导出的精简 cookies），"
        "YouTube 仍可能要求登录验证。\n"
        "    请在已登录 YouTube 的浏览器里用扩展导出完整 Netscape cookies 覆盖该文件，"
        "或改用: export YOUTUBE_COOKIES_FROM_BROWSER=chrome（并完全退出 Chrome 后运行）。\n"
        f"    文件: {cookie_path}",
        flush=True,
    )


def _merge_youtube_ydl_opts(base: dict) -> dict:
    """为 YouTube 合并 cookiefile、cookiesfrombrowser，并设置 player_client 以拿到更多格式。"""
    opts = {**base}
    cookie_file = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if not cookie_file:
        for candidate in (_SCRIPT_DIR / "youtube_cookies.txt", CONFIG_PATH.parent / "youtube_cookies.txt"):
            if candidate.is_file():
                cookie_file = str(candidate.resolve())
                break
    if not cookie_file and YOUTUBE_COOKIES_FILE_DEFAULT.is_file():
        cookie_file = str(YOUTUBE_COOKIES_FILE_DEFAULT)
    if cookie_file and os.path.isfile(cookie_file):
        opts["cookiefile"] = cookie_file
    else:
        browser = os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "").strip()
        if browser:
            parts = browser.split(":", 1)
            name = parts[0].strip()
            if len(parts) > 1 and parts[1].strip():
                opts["cookiesfrombrowser"] = (name, parts[1].strip())
            else:
                opts["cookiesfrombrowser"] = (name,)

    ex = dict(opts.get("extractor_args") or {})
    yt = dict(ex.get("youtube") or {})
    # 允许用环境变量覆盖，例如：YOUTUBE_PLAYER_CLIENT=web,android,ios
    pc_env = os.environ.get("YOUTUBE_PLAYER_CLIENT", "").strip()
    if pc_env:
        yt["player_client"] = [p.strip() for p in pc_env.split(",") if p.strip()]
    elif not yt.get("player_client"):
        # 使用 cookie 文件时，上游更倾向 tv / web_safari / web 顺序；纯无 cookie 仍用 android 先试
        if opts.get("cookiefile"):
            yt["player_client"] = [
                "tv",
                "tv_embedded",
                "web_safari",
                "web",
                "mweb",
                "android",
                "ios",
            ]
        else:
            yt["player_client"] = ["android", "web", "ios"]
    ex["youtube"] = yt
    opts["extractor_args"] = ex
    return opts


def _youtube_opts_with_player_client(base: dict, clients: list[str]) -> dict:
    o = {**base}
    ex = dict(o.get("extractor_args") or {})
    yt = dict(ex.get("youtube") or {})
    yt["player_client"] = clients
    ex["youtube"] = yt
    o["extractor_args"] = ex
    return o


def _youtube_player_client_variants(base_opts: dict) -> list[list[str]]:
    """在 bot 类错误时依次尝试的 player_client 组合（去重）。"""
    ex = base_opts.get("extractor_args") or {}
    yt = ex.get("youtube") or {}
    first = yt.get("player_client")
    if isinstance(first, str):
        current: list[str] = [first]
    elif isinstance(first, (list, tuple)):
        current = [str(x) for x in first]
    else:
        current = ["android", "web", "ios"]

    using_cookiefile = bool(base_opts.get("cookiefile"))
    # 有 cookie 文件时多试几组 TV/Web 组合（与无 cookie 时的顺序不同）
    tv_first: list[list[str]] = [
        ["tv", "web_safari", "web", "android"],
        ["tv", "tv_embedded", "web"],
        ["web_safari", "web", "mweb"],
        ["tv_embedded", "web"],
        ["android", "web", "ios"],
    ]
    android_first: list[list[str]] = [
        ["web", "android", "ios"],
        ["android", "ios", "web"],
        ["android"],
        ["web"],
        ["ios", "web", "android"],
        ["mweb", "web", "android"],
    ]

    fallbacks: list[list[str]] = [current] + (tv_first if using_cookiefile else android_first)
    seen: set[tuple[str, ...]] = set()
    out: list[list[str]] = []
    for chain in fallbacks:
        key = tuple(chain)
        if key in seen:
            continue
        seen.add(key)
        out.append(chain)
    return out


def _is_storyboard_or_nonmedia_url(f: dict, url: str) -> bool:
    """
    YouTube 等会把 storyboard（预览图条）放进 formats，带 url 但无音视频流。
    误选会导致 FFmpeg 拉 i.ytimg.com/sb/...jpg 等。
    """
    if not url:
        return True
    low = url.lower()
    if "i.ytimg.com/sb/" in low or "/storyboard" in low:
        return True
    if "ytimg.com" in low and "/sb/" in low:
        return True
    fid = str(f.get("format_id") or "")
    if re.match(r"^sb\d*$", fid, re.I):
        return True
    fn = (f.get("format_note") or "") + " " + (f.get("resolution") or "")
    if "storyboard" in fn.lower():
        return True
    ac = f.get("acodec")
    vc = f.get("vcodec")
    if ac in (None, "none") and vc in (None, "none"):
        if low.endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
            return True
        if "ytimg.com" in low:
            return True
    return False


def _url_looks_like_http_media_stream(url: str) -> bool:
    """无 acodec 的条目仅当 URL 明显是 CDN 媒体流时才可作兜底。"""
    low = url.lower()
    if "i.ytimg.com/sb/" in low or "/storyboard" in low:
        return False
    if "googlevideo.com" in low:
        return True
    if ".m3u8" in low or "/manifest/" in low:
        return True
    if "videoplayback" in low and ("googlevideo" in low or "googleusercontent" in low):
        return True
    if re.search(r"\.(mp4|webm|m4a|mp3|ts|mkv|mov)(\?|$|#)", low):
        return True
    return False


def _pick_stream_url_from_formats_dict(info: dict) -> tuple[str, float | None] | None:
    """从 extract_info(..., process=False) 的 info['formats'] 里挑一条可直接给 FFmpeg 的 URL。"""
    fmts = info.get("formats")
    if not fmts:
        return None
    try:
        rows = list(fmts)
    except Exception:
        return None

    dur = info.get("duration")
    if dur is not None:
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = None

    audio_only: list[tuple[float, str]] = []
    muxed: list[tuple[float, str]] = []
    fallback_urls: list[str] = []

    for f in rows:
        u = f.get("url")
        if not u:
            continue
        if _is_storyboard_or_nonmedia_url(f, u):
            continue
        ac = f.get("acodec")
        vc = f.get("vcodec")
        if ac in (None, "none"):
            if _url_looks_like_http_media_stream(u):
                fallback_urls.append(u)
            continue
        if vc in (None, "none"):
            abr = f.get("abr") or 0
            try:
                abr = float(abr)
            except (TypeError, ValueError):
                abr = 0.0
            audio_only.append((abr, u))
        else:
            tbr = f.get("tbr") or f.get("abr") or 0
            try:
                tbr = float(tbr)
            except (TypeError, ValueError):
                tbr = 0.0
            muxed.append((tbr, u))

    if audio_only:
        audio_only.sort(key=lambda x: x[0], reverse=True)
        return (audio_only[0][1], dur)
    if muxed:
        muxed.sort(key=lambda x: x[0], reverse=True)
        return (muxed[0][1], dur)
    if fallback_urls:
        return (fallback_urls[0], dur)
    return None


def _is_retryable_format_error(e: BaseException) -> bool:
    err_low = str(e).lower()
    if "requested format is not available" in err_low:
        return True
    if "format is not available" in err_low:
        return True
    if "only images are available" in err_low:
        return True
    if "no video formats" in err_low or "no audio formats" in err_low:
        return True
    if "unable to download" in err_low and "format" in err_low:
        return True
    return False


def _extract_url_duration_from_merged_info(info: dict) -> tuple[str | None, float | None]:
    """format 选择器跑完后，从 info.url 或 requested_formats 取可给 FFmpeg 的 URL。"""
    if not info:
        return (None, None)
    dur = info.get("duration")
    if dur is not None:
        try:
            dur = float(dur)
        except (TypeError, ValueError):
            dur = None
    url = info.get("url")
    if url and not _is_storyboard_or_nonmedia_url({}, url):
        return (url, dur)
    rf = info.get("requested_formats")
    if isinstance(rf, list):
        for f in rf:
            u = f.get("url")
            if not u or _is_storyboard_or_nonmedia_url(f, u):
                continue
            if f.get("acodec") not in (None, "none"):
                return (u, dur)
        for f in rf:
            u = f.get("url")
            if u and not _is_storyboard_or_nonmedia_url(f, u):
                return (u, dur)
    picked = _pick_stream_url_from_formats_dict(info)
    if picked:
        return (picked[0], picked[1])
    return (None, dur)


def _ydl_extract_stream_url_resilient(link: str, ydl_opts: dict) -> tuple[str, float | None]:
    """
    先 process=False 且不带 format，从 formats 里手选 URL，避免 bestaudio/best 与当前客户端返回的格式表不匹配。
    失败再按多组 format 字符串回退。
    """
    opts_no_fmt = {k: v for k, v in ydl_opts.items() if k != "format"}
    last_err: BaseException | None = None

    try:
        with yt_dlp.YoutubeDL(opts_no_fmt) as ydl:
            info = ydl.extract_info(link, download=False, process=False)
        if info:
            picked = _pick_stream_url_from_formats_dict(info)
            if picked:
                return picked
    except Exception as e:
        last_err = e
        err_low = str(e).lower()
        if _is_youtube_link(link) and (
            "sign in" in err_low
            or "not a bot" in err_low
            or ("bot" in err_low and "youtube" in err_low)
            or "login required" in err_low
            or ("cookies" in err_low and "youtube" in err_low)
        ):
            raise

    format_chain = (
        ydl_opts.get("format") or "bestaudio/bestaudio*/best/b/worst",
        "ba/b",
        "bestvideo+bestaudio/best/ba/b/worst",
        "bv*+ba/b",
        "best/worst",
        "worst",
    )
    seen: set[str] = set()
    for fmt in format_chain:
        if not fmt or fmt in seen:
            continue
        seen.add(fmt)
        opts = {**ydl_opts, "format": fmt}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(link, download=False)
            if info is None:
                continue
            url, dur = _extract_url_duration_from_merged_info(info)
            if url:
                return (url, dur)
        except Exception as e:
            last_err = e
            err_low = str(e).lower()
            if _is_youtube_link(link) and (
                "sign in" in err_low
                or "not a bot" in err_low
                or ("bot" in err_low and "youtube" in err_low)
            ):
                raise
            continue

    if last_err:
        if _is_youtube_link(link):
            el = str(last_err).lower()
            if "requested format is not available" in el or "only images are available" in el:
                raise RuntimeError(
                    "YouTube 当前没有可用的音视频格式（只有预览图/storyboard 时也会报此错）。\n"
                    "常见原因：已使用 Cookie 时 yt-dlp 会跳过 android/ios 客户端，主要依赖 web/tv 等接口；"
                    "若本机未配置 JS 运行环境，「n challenge」解失败会导致拿不到真实音画轨。\n"
                    "处理建议：按 https://github.com/yt-dlp/yt-dlp/wiki/EJS 安装并配置 Node（或文档中的其它运行时）；"
                    "执行 uv pip install -U yt-dlp 升级到最新；若出现 mweb 403 相关提示可参考 PO Token 文档。\n\n"
                    f"原始错误: {last_err}"
                ) from last_err
        raise last_err
    raise RuntimeError(f"无法获取流地址: {link}")


def _extract_stream_url_with_ydl(link: str, ydl_opts: dict) -> tuple[str, float | None]:
    return _ydl_extract_stream_url_resilient(link, ydl_opts)


def get_stream_url(link: str) -> tuple[str, float | None]:
    """使用 yt-dlp 获取音视频流的真实 URL 与时长（秒），不下载。返回 (url, duration_sec)，duration 可能为 None。"""
    ydl_opts = {
        "format": "bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    douyin_cookie_hint = (
        "抖音仅支持 Cookie 文件。请用 Chrome 扩展「Get cookies.txt LOCALLY」或「cookies.txt」"
        "在打开该抖音链接后导出，保存为项目目录下的 batch_deal_dy_cookie.txt（或设置 DOUYIN_COOKIES_FILE）。"
        "若仍报 Fresh cookies，请：1) 在 Chrome 打开该链接并播放/刷新；2) 不关页面，立即用扩展导出；3) 覆盖 batch_deal_dy_cookie.txt 后重试。"
        "也可尝试升级 yt-dlp：uv pip install -U yt-dlp"
    )
    if "douyin" in link.lower():
        cookie_file = os.environ.get("DOUYIN_COOKIES_FILE", "").strip()
        if not cookie_file:
            default_cookie = CONFIG_PATH.parent / "batch_deal_dy_cookie.txt"
            if default_cookie.is_file():
                cookie_file = str(default_cookie)
        if not cookie_file or not os.path.isfile(cookie_file):
            raise RuntimeError(
                f"未找到抖音 Cookie 文件。请将 cookies.txt 保存为 batch_deal_dy_cookie.txt 放到项目目录，或设置 DOUYIN_COOKIES_FILE。\n{douyin_cookie_hint}"
            )
        # 设备模拟 + Cookie 文件，提高抖音解析成功率
        opts = {
            **ydl_opts,
            "cookiefile": cookie_file,
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "extractor_args": {"douyin": ["device_id=73000000000", "iid=1234567890"]},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(link, download=False)
                if info is None:
                    raise RuntimeError("无法获取视频信息")
                url = info.get("url")
                if not url:
                    formats = info.get("formats") or []
                    for f in formats:
                        u = f.get("url")
                        if u and (f.get("vcodec") == "none" or f.get("acodec") != "none"):
                            url = u
                            break
                    if not url and formats:
                        url = next((f.get("url") for f in formats if f.get("url")), None)
                if url:
                    duration = info.get("duration")
                    return (url, float(duration) if duration is not None else None)
        except Exception as e:
            raise RuntimeError(f"{douyin_cookie_hint}\n原始错误: {e}") from e

    if _is_binance_square_link(link):
        return _get_binance_square_stream_url(link)

    if _is_youtube_link(link):
        yt_base = {**ydl_opts}
        ydl_opts = _merge_youtube_ydl_opts(ydl_opts)
        # 未配置 Cookie 时，直接使用脚本目录下的 macstudio 导出文件（避免 cwd 不对找不到文件）
        if (
            not ydl_opts.get("cookiefile")
            and not ydl_opts.get("cookiesfrombrowser")
            and YOUTUBE_MACSTUDIO_COOKIES_FILE.is_file()
        ):
            ydl_opts = _youtube_opts_with_macstudio_cookie(yt_base, YOUTUBE_MACSTUDIO_COOKIES_FILE)
        cf = ydl_opts.get("cookiefile")
        if cf:
            _warn_if_youtube_cookiefile_thin(str(cf))
        if os.environ.get("YOUTUBE_DEBUG", "").strip().lower() in ("1", "true", "yes"):
            print(f">>> YouTube Cookie 来源: {_youtube_auth_label(ydl_opts)}", flush=True)

        ok, last_err = _youtube_try_extraction_with_clients(link, ydl_opts)
        if ok is not None:
            return ok

        fb = YOUTUBE_MACSTUDIO_COOKIES_FILE
        if (
            last_err is not None
            and fb.is_file()
            and _youtube_should_try_macstudio_fallback(last_err)
            and not _youtube_already_uses_cookie_path(ydl_opts, fb)
        ):
            if os.environ.get("YOUTUBE_DEBUG", "").strip().lower() in ("1", "true", "yes"):
                print(f">>> YouTube 回退尝试 Cookie: {fb}", flush=True)
            ydl_fb = _youtube_opts_with_macstudio_cookie(yt_base, fb)
            ok2, last_err2 = _youtube_try_extraction_with_clients(link, ydl_fb)
            if ok2 is not None:
                return ok2
            if last_err2 is not None:
                last_err = last_err2
            ydl_opts = ydl_fb

        on_bot_browser = os.environ.get("YOUTUBE_ON_BOT_TRY_BROWSER", "").strip()
        if (
            last_err is not None
            and _is_youtube_bot_or_auth_error(last_err)
            and on_bot_browser
            and not ydl_opts.get("cookiesfrombrowser")
        ):
            if os.environ.get("YOUTUBE_DEBUG", "").strip().lower() in ("1", "true", "yes"):
                print(
                    f">>> YouTube 仍报 bot，按 YOUTUBE_ON_BOT_TRY_BROWSER 从浏览器重试: {on_bot_browser}",
                    flush=True,
                )
            ydl_br = _youtube_opts_browser_only(yt_base, on_bot_browser)
            ok3, last_err3 = _youtube_try_extraction_with_clients(link, ydl_br)
            if ok3 is not None:
                return ok3
            if last_err3 is not None:
                last_err = last_err3
            ydl_opts = ydl_br

        if last_err is not None:
            if _is_youtube_bot_or_auth_error(last_err):
                extra = ""
                ms_path = YOUTUBE_MACSTUDIO_COOKIES_FILE
                if ms_path.is_file():
                    resolved = ms_path.resolve()
                    if _youtube_already_uses_cookie_path(ydl_opts, ms_path):
                        extra = (
                            f"\n说明: 已使用备用 Cookie 文件仍失败，多为 Cookie 过期或 IP/账号被风控；"
                            f"请重新导出并覆盖，或升级 yt-dlp、换网络。\n    {resolved}\n"
                        )
                    else:
                        extra = f"\n说明: 备用 Cookie 文件路径（请核对是否在磁盘上）: {resolved}\n"
                raise RuntimeError(
                    f"{_youtube_cookie_hint()}{extra}"
                    f"当前 Cookie 配置: {_youtube_auth_label(ydl_opts)}\n原始错误: {last_err}"
                ) from last_err
            raise last_err
        raise RuntimeError("yt-dlp YouTube 解析失败且无错误信息")

    return _extract_stream_url_with_ydl(link, ydl_opts)


def stream_to_audio_array(stream_url: str, duration_sec: float | None = None) -> np.ndarray:
    """
    使用 FFmpeg 将流转为 16kHz 单声道 float32 数组（Whisper 所需格式）。
    若提供 duration_sec，会按读取字节数估算并打印转码进度。
    """
    global _ffmpeg_proxy_logged
    _warn_if_bnbstatic_needs_proxy(stream_url)
    cmd = [
        get_ffmpeg_path(),
        "-hide_banner", "-loglevel", "error",
    ]
    proxy_cli = _ffmpeg_proxy_cli_args()
    if proxy_cli:
        cmd.extend(proxy_cli)
        if not _ffmpeg_proxy_logged:
            _ffmpeg_proxy_logged = True
            print(
                ">>> FFmpeg 已附加代理（-http_proxy/-socks_proxy）；"
                "FFmpeg 默认不读 HTTPS_PROXY，与 curl 不同，已由脚本同步环境变量。"
            )
    if "bilibili" in stream_url or "bilivideo" in stream_url:
        cmd.extend([
            "-headers",
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\nReferer: https://www.bilibili.com/\r\n",
        ])
    elif any(x in stream_url for x in ("bblivestream.com", "binance.com", "bnbstatic.com")):
        cmd.extend([
            "-headers",
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36\r\nReferer: https://www.binance.com/\r\n",
        ])
        if _is_binance_live_pull_url(stream_url):
            idle_sec = max(5, int(os.environ.get("BINANCE_LIVE_PULL_IDLE_TIMEOUT_SEC", "20")))
            cmd.extend(["-rw_timeout", str(idle_sec * 1_000_000)])
        elif ".m3u8" in stream_url.lower():
            cmd.extend(["-reconnect", "1", "-reconnect_streamed", "1", "-reconnect_delay_max", "5"])
    cmd.extend([
        "-i", stream_url,
        "-f", "s16le",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-",
    ])
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # 已知时长时按字节估算进度：16kHz * 2 字节 = 32000 字节/秒
    chunk_size = 256 * 1024
    expected_bytes = int(duration_sec * 32000) if duration_sec and duration_sec > 0 else None
    raw_chunks = []
    bytes_read = 0
    last_pct = -1

    if process.stdout:
        while True:
            chunk = process.stdout.read(chunk_size)
            if not chunk:
                break
            raw_chunks.append(chunk)
            bytes_read += len(chunk)
            if expected_bytes and expected_bytes > 0:
                pct = min(100, int(bytes_read / expected_bytes * 100))
                if pct >= last_pct + 5 or pct == 100:
                    print(f"\r    FFmpeg 转码: {pct}%", end="", flush=True)
                    last_pct = pct
    raw_bytes = b"".join(raw_chunks)
    stderr = process.stderr.read() if process.stderr else b""
    process.wait()
    if last_pct >= 0:
        print()
    if process.returncode != 0:
        err = stderr.decode("utf-8", errors="replace") if stderr else ""
        raise RuntimeError(f"FFmpeg 转码失败 (code={process.returncode}): {err}")

    if len(raw_bytes) == 0:
        raise RuntimeError("FFmpeg 未输出任何数据，可能流地址无效或视频无音轨")

    # int16 -> float32, 范围 [-1, 1]
    audio = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    return audio


def transcribe_audio_array(
    audio: np.ndarray,
    progress_callback=None,
) -> list[tuple[float, float, str]]:
    """使用 faster-whisper 转写，返回 [(start, end, text), ...]。可选 progress_callback(end_sec, total_sec, n_segments) 用于进度。"""
    model = get_whisper_model()
    total_sec = len(audio) / 16000.0
    segments_gen, _ = model.transcribe(
        audio,
        language=WHISPER_LANGUAGE,
        beam_size=1,
        vad_filter=True,
    )
    result = []
    last_pct = -1
    t0 = time.perf_counter()
    for seg in segments_gen:
        result.append((seg.start, seg.end, (seg.text or "").strip()))
        if progress_callback:
            progress_callback(seg.end, total_sec, len(result))
        elif total_sec > 0:
            pct = min(100, int(seg.end / total_sec * 100))
            if pct >= last_pct + 5 or pct == 100:
                print(f"\r    转写进度: {pct}% ({len(result)} 段)", end="", flush=True)
                last_pct = pct
    elapsed = time.perf_counter() - t0
    n_chars = sum(len(t) for _, _, t in result)
    tail = f" | 转写总时间 {elapsed:.1f} 秒 | 约 {n_chars} 字"
    if progress_callback:
        if result:
            print(f"    转写完成: {len(result)} 段{tail}", flush=True)
    else:
        if not result:
            return result
        if total_sec > 0:
            pct_final = min(100, int(result[-1][1] / total_sec * 100))
        else:
            pct_final = 100
        print(f"\r    转写进度: {pct_final}% ({len(result)} 段){tail}    ", flush=True)
        print()
    return result


def stream_transcribe(name: str, link: str) -> Path:
    """
    不下载，直接流转写：获取流 URL → FFmpeg 转 PCM → faster-whisper 转写
    输出到 subtitles/name.txt 和 logs/name.txt
    """
    ensure_dirs()
    transcript_path = TRANSCRIPT_DIR / f"{name}.txt"
    log_path = LOG_DIR / f"{name}.txt"

    print(f"\n>>> 获取流地址: {link}")
    stream_url, duration_sec = get_stream_url(link)
    if duration_sec is not None:
        print(f"    视频时长约 {duration_sec:.0f} 秒")

    print(f">>> FFmpeg 转码中（16k 单声道）...")
    audio = stream_to_audio_array(stream_url, duration_sec)
    duration_sec = len(audio) / 16000
    print(f"    音频时长约 {duration_sec:.1f} 秒")

    print(f">>> 转写中 -> {transcript_path}")
    segments = transcribe_audio_array(audio)

    # 生成与 WhisperX 类似的输出格式，便于后续 Qwen 处理
    lines = []
    plain_parts = []
    for start, end, text in segments:
        if not text:
            continue
        line = f"[{start:.2f}s -> {end:.2f}s] {text}"
        lines.append(line)
        plain_parts.append(text)

    raw_output = "\n".join(lines)
    transcript_path.write_text(raw_output, encoding="utf-8")
    log_path.write_text(raw_output, encoding="utf-8")

    print(f"✅ 转写完成: {transcript_path}")
    return transcript_path


def extract_plain_text_from_transcript(raw_text: str) -> str:
    """
    从转写输出提取纯文本。
    支持两种格式：
    1) [start -> end] text
    2) Transcript: [time] text (WhisperX 格式，兼容)
    """
    lines = raw_text.splitlines()
    texts = []
    # [0.00s -> 2.50s] 中文内容
    pattern1 = re.compile(r"^\[\d+(?:\.\d+)?s\s*->\s*\d+(?:\.\d+)?s\]\s*(.*)$")
    # Transcript: [time] 中文内容
    pattern2 = re.compile(r"^Transcript:\s*\[[^\]]+\]\s*(.*)$")

    for line in lines:
        line = line.strip()
        if not line:
            continue
        m = pattern1.match(line) or pattern2.match(line)
        if m:
            content = m.group(1).strip()
            if content:
                texts.append(content)
        elif not line.startswith(("UserWarning", "INFO", "WARNING", "Downloading")):
            texts.append(line)

    return " ".join(texts)


def _split_plain_text_into_refine_chunks(text: str, max_chars: int) -> list[str]:
    """
    将识别稿切成多段供 Qwen 逐段整理，避免单次生成长度被 max_tokens 截断。
    优先在换行、句号等处断开。
    """
    text = text.strip()
    if not text:
        return []
    max_chars = max(800, max_chars)
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        ideal_end = min(start + max_chars, n)
        if ideal_end >= n:
            tail = text[start:n].strip()
            if tail:
                chunks.append(tail)
            break
        search_from = start + max(1, max_chars // 4)
        break_at = ideal_end
        segment = text[start:ideal_end]
        for sep in ("\n\n", "\n", "。", "；", "，"):
            idx = segment.rfind(sep)
            if idx == -1:
                continue
            abs_end = start + idx + len(sep)
            if abs_end > search_from:
                break_at = abs_end
                break
        piece = text[start:break_at].strip()
        if not piece:
            break_at = ideal_end
            piece = text[start:break_at].strip()
        if not piece:
            start = ideal_end
            continue
        chunks.append(piece)
        start = break_at
    return [c for c in chunks if c]


def call_qwen(prompt: str, *, max_tokens: int = 8192, timeout: int = 120) -> str:
    """调用通义千问 API。max_tokens 为模型单次生成上限，长稿须用大值否则会截断。"""
    if not QWEN_API_KEY:
        raise RuntimeError("QWEN_API_KEY 未配置")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {QWEN_API_KEY}",
    }
    payload = {
        "model": QWEN_MODEL,
        "input": {"messages": [{"role": "user", "content": prompt}]},
        "parameters": {"temperature": 0.7, "max_tokens": max_tokens},
    }
    resp = requests.post(QWEN_ENDPOINT, headers=headers, json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"Qwen API 调用失败 ({resp.status_code}): {resp.text}")

    data = resp.json()
    if "output" in data and "choices" in data["output"]:
        if data["output"]["choices"]:
            return data["output"]["choices"][0]["message"]["content"]
    if "output" in data and "text" in data["output"]:
        return data["output"]["text"]
    raise RuntimeError(f"Qwen 返回格式异常: {data}")


def refine_transcript_with_qwen(name: str, transcript_path: Path) -> Path:
    """AI 断句整理 + 摘要，保存到 output/name.txt"""
    raw = transcript_path.read_text(encoding="utf-8")
    plain_text = extract_plain_text_from_transcript(raw)
    if not plain_text.strip():
        raise RuntimeError("未提取到有效文本")

    system_prompt = (
        "你是一个中文文字编辑助手。"
        "现在给你一段由语音识别得到的中文文本，内容已经基本正确，但存在："
        "1）断句混乱；2）简繁体混用；3）口语化、重复、无意义语气词。\n\n"
        "请你：\n"
        "- 合并所有片段，按语义正确断句成自然的中文段落；\n"
        "- 统一为简体中文；\n"
        "- 保留原视频的含义，不要自行编造新内容；\n"
        "- 删除明显重复的句子和无意义的口头语；\n"
        "- 输出纯文本，不要加标题、前言或总结。\n\n"
        "下面是待整理的原始转写文本：\n"
    )
    chunks = _split_plain_text_into_refine_chunks(plain_text, QWEN_REFINE_CHUNK_CHARS)
    refined_parts: list[str] = []
    n_chunk = len(chunks)
    for idx, ch in enumerate(chunks):
        if n_chunk > 1:
            print(
                f">>> Qwen 整理全文第 {idx + 1}/{n_chunk} 段（每段约 {QWEN_REFINE_CHUNK_CHARS} 字内）…",
                flush=True,
            )
            prefix = (
                f"【说明】这是整期口播转写稿的第 {idx + 1}/{n_chunk} 段，请只整理本段文字，"
                "不要写摘要、不要臆测其他段内容。\n\n"
            )
        else:
            prefix = ""
        part = call_qwen(
            system_prompt + prefix + ch,
            max_tokens=QWEN_REFINE_MAX_TOKENS,
            timeout=QWEN_REFINE_TIMEOUT_SEC,
        ).strip()
        refined_parts.append(part)
    refined_text = "\n\n".join(refined_parts)

    summary_source = refined_text[: max(0, QWEN_SUMMARY_SOURCE_CHARS)]
    summary_prompt = (
        "你是一个内容摘要助手。"
        "请为以下文本生成一个简洁准确的摘要，控制在100-200字以内。"
        "摘要应该概括文本的核心内容和主要观点。\n\n"
        "待摘要的文本（可能仅为全文前部节选，请据此概括主旨即可）：\n"
    )
    summary = call_qwen(
        summary_prompt + summary_source,
        max_tokens=QWEN_SUMMARY_MAX_TOKENS,
        timeout=60,
    ).strip()

    final_output = f"摘要：{summary}\n\n全文：{refined_text}"
    ensure_dirs()
    refined_path = OUTPUT_DIR / f"{name}.txt"
    refined_path.write_text(final_output, encoding="utf-8")
    return refined_path


def process_item_once(item: dict) -> dict:
    """处理单个任务（一次尝试），返回包含文字稿的结果。"""
    item = normalize_task_item(item)
    name = item.get("name")
    link = item.get("link")
    if not name or not link:
        raise ValueError(f"任务缺少 name/link 字段: {item}")

    transcript_path = stream_transcribe(name, link)
    raw_text = transcript_path.read_text(encoding="utf-8")
    plain_text = extract_plain_text_from_transcript(raw_text)

    refined_text = None
    refined_path = None
    try:
        refined_path_obj = refine_transcript_with_qwen(name, transcript_path)
        refined_path = str(refined_path_obj)
        refined_text = refined_path_obj.read_text(encoding="utf-8")
    except Exception as e:
        # AI 精排失败不影响主流程
        print(f"⚠ AI 处理失败（跳过）：{e}")

    result = {
        **item,
        "status": "success",
        "transcript": plain_text,
        "raw_transcript": raw_text,
        "refined_text": refined_text,
        "transcript_path": str(transcript_path),
        "refined_path": refined_path,
    }
    return result


def process_item_with_retry(item: dict, retries: int = 3) -> dict:
    """处理单个任务，失败最多重试 retries 次（总次数=1+retries）。"""
    last_error = None
    for attempt in range(retries + 1):
        try:
            print(f"\n>>> 处理任务 {item.get('name')}，第 {attempt + 1}/{retries + 1} 次")
            return {
                **process_item_once(item),
                "attempt": attempt + 1,
                "max_attempts": retries + 1,
            }
        except Exception as e:
            last_error = e
            print(f"[ERROR] 任务失败，第 {attempt + 1}/{retries + 1} 次: {e}")
            traceback.print_exc()
            if _is_cuda_runtime_missing_error(e):
                print("[ERROR] 检测到 CUDA 运行库缺失，属于环境问题，不再重复重试当前任务。")
                break
    return {
        **item,
        "status": "error",
        "error": str(last_error) if last_error else "unknown error",
        "attempt": retries + 1,
        "max_attempts": retries + 1,
    }


def _normalize_ws_payload(payload) -> list[dict]:
    """
    支持以下输入：
    1) {"name": "...", "link": "..."}
    2) {"content_id": "4396…", "author": "颜驰Bit"}  → 自动拼 replay URL，输出名=作者_时间戳
    3) [{"name": "...", "link": "..."}, ...]
    4) {"videos":[...]} 或 {"data": {.../[]}}
    """
    return _normalize_task_payload(payload)


def run_file_mode(
    cli_urls: list[str] | None = None,
    cli_names: list[str] | None = None,
    cli_titles: list[str] | None = None,
    cli_shottitles: list[str] | None = None,
    cli_json_items: list[str] | None = None,
    cli_content_ids: list[str] | None = None,
    cli_authors: list[str] | None = None,
):
    ensure_dirs()
    urls = [u for u in (cli_urls or []) if (u or "").strip()]
    names = [n for n in (cli_names or []) if (n or "").strip()]
    json_raw = [x for x in (cli_json_items or []) if (x or "").strip()]
    content_ids = [c for c in (cli_content_ids or []) if (c or "").strip()]
    authors = list(cli_authors or [])
    if content_ids:
        if urls or names or cli_titles or cli_shottitles or json_raw:
            raise ValueError(
                "--content-id 与 --item/--json/--url/--link/--name/--title/--shottitle 不能同时使用"
            )
        config = build_items_from_content_ids(content_ids, authors)
        print(f">>> contentId 模式：共 {len(config)} 条 → audio/replay?id=…")
    elif json_raw:
        if urls or names or cli_titles or cli_shottitles:
            raise ValueError(
                "--item/--json 与 --url/--link/--name/--title/--shottitle 不能同时使用"
            )
        config = parse_cli_json_items(json_raw)
        config = [normalize_task_item(x) for x in config]
        print(f">>> JSON 模式：使用命令行 JSON 对象，共 {len(config)} 条，不读取 videos.json")
    elif urls:
        config = build_items_from_cli_urls(urls, names, cli_titles, cli_shottitles)
        config = [normalize_task_item(x) for x in config]
        print(">>> URL 模式：使用命令行中的链接，不读取 videos.json")
    else:
        config = load_config()
        if not isinstance(config, list):
            raise ValueError("videos.json 顶层应为对象数组 [{name, link}, ...]")
        if names:
            config = filter_config_by_names(config, names)
            print(f">>> 筛选模式：仅处理 videos.json 中的 name={names}")
        config = [normalize_task_item(x) for x in config]

    for item in config:
        name = item.get("name")
        link = item.get("link")
        if not name or not link:
            print(f"跳过无效配置: {item}")
            continue

        print(f"\n{'='*40}")
        print(f"处理视频：{name}")
        print(f"链接：{link}")
        print(f"{'='*40}")

        # 若 output 中已存在该名称的成品稿，则跳过
        output_file = OUTPUT_DIR / f"{name}.txt"
        if output_file.exists():
            print(f"✅ 已存在，跳过：{output_file}")
            continue

        try:
            result = process_item_with_retry(item, retries=3)
            if result.get("status") == "success":
                print(f"✅ 处理完成：{name} → {OUTPUT_DIR / f'{name}.txt'}")
            else:
                print(f"[ERROR] 处理 {name} 失败：{result.get('error')}")
        except Exception as e:
            print(f"[ERROR] 处理 {name} 失败：{e}")


async def run_realtime_mode(host: str, port: int):
    """
    实时模式：
    - 启动 WebSocket 服务
    - 接收类似 videos.json 结构的消息
    - 入队串行处理（默认不并发）
    - 处理完成后回传：原结构 + 文字稿/状态
    """
    ensure_dirs()
    task_queue: asyncio.Queue[tuple[object, dict]] = asyncio.Queue()

    async def worker():
        while True:
            websocket, item = await task_queue.get()
            try:
                result = await asyncio.to_thread(process_item_with_retry, item, 3)
                await websocket.send(json.dumps(result, ensure_ascii=False))
            except Exception as e:
                err = {
                    **item,
                    "status": "error",
                    "error": str(e),
                }
                try:
                    await websocket.send(json.dumps(err, ensure_ascii=False))
                except Exception:
                    pass
            finally:
                task_queue.task_done()

    async def ws_handler(websocket):
        async for message in websocket:
            try:
                payload = json.loads(message)
            except Exception:
                await websocket.send(
                    json.dumps({"status": "error", "error": "消息不是合法 JSON"}, ensure_ascii=False)
                )
                continue

            items = _normalize_ws_payload(payload)
            if not items:
                await websocket.send(
                    json.dumps(
                        {
                            "status": "error",
                            "error": "消息结构不符合要求，需包含 name/link，或 content_id(+可选 author)，或 videos/data 列表",
                        },
                        ensure_ascii=False,
                    )
                )
                continue

            for item in items:
                await task_queue.put((websocket, item))
            await websocket.send(
                json.dumps(
                    {
                        "status": "queued",
                        "queued_count": len(items),
                        "queue_size": task_queue.qsize(),
                    },
                    ensure_ascii=False,
                )
            )

    worker_task = asyncio.create_task(worker())
    print(f"🚀 WebSocket 实时服务已启动：ws://{host}:{port}")
    print("   收到消息后将按队列串行处理，完成后回传结果。")
    try:
        async with websockets.serve(ws_handler, host, port, max_size=8 * 1024 * 1024):
            await asyncio.Future()
    finally:
        worker_task.cancel()


def refresh_youtube_cookies_cli(browser_spec: str) -> int:
    """
    调用 yt-dlp：从本机浏览器读取 Cookie 并写入 Netscape 文件（与 --cookies 行为一致）。
    无法弹出 YouTube 页面；请先在浏览器里登录 youtube.com（含人机验证），再退出浏览器后执行。
    """
    global _youtube_cookie_thin_warned
    browser_spec = (browser_spec or "chrome").strip()
    out_path = YOUTUBE_MACSTUDIO_COOKIES_FILE.resolve()
    test_url = os.environ.get(
        "YOUTUBE_COOKIE_TEST_URL",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    ).strip()
    print(
        "\n>>> 刷新 YouTube Cookie 到文件（一次性，之后批处理可读该文件）\n"
        "    YouTube 不会在命令行里弹窗；请按顺序：\n"
        "    1) 打开 Chrome（或你指定的浏览器）访问 https://www.youtube.com 并登录（若出现验证请做完）\n"
        "    2) 完全退出该浏览器（macOS：菜单 → 退出 Chrome，不要只关窗口）\n"
        "    3) 再执行下面这条命令（已包含你当前参数）\n\n"
        f"    写入路径: {out_path}\n"
        f"    浏览器参数: {browser_spec}\n"
        f"    测试 URL（可用环境变量 YOUTUBE_COOKIE_TEST_URL 改成你的视频）\n",
        flush=True,
    )
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--cookies-from-browser",
        browser_spec,
        "--cookies",
        str(out_path),
        "--simulate",
        test_url,
    ]
    print("执行:", " ".join(cmd), "\n", flush=True)
    p = subprocess.run(cmd)
    if p.returncode != 0:
        print(
            f"\n>>> yt-dlp 退出码 {p.returncode}。"
            "若提示无法读 Cookie 数据库，请确认浏览器已完全退出；Brave/Arc 请把 --browser 设为 brave。",
            flush=True,
        )
        return p.returncode
    _youtube_cookie_thin_warned = False
    try:
        text = out_path.read_text(encoding="utf-8", errors="ignore")[:65536]
    except OSError as e:
        print(f"\n>>> 无法读取输出文件: {e}", flush=True)
        return 1
    if "LOGIN_INFO" in text:
        print(
            f"\n>>> 成功：文件里已有 LOGIN_INFO，接下来直接跑批处理即可（无需再登录）。\n    {out_path}\n",
            flush=True,
        )
    else:
        print(
            "\n>>> 文件已生成，但未检测到 LOGIN_INFO。"
            "若批处理仍报 bot，请用 Chrome 扩展「Get cookies.txt LOCALLY」在 youtube.com 页导出并覆盖：\n"
            f"    {out_path}\n",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Whisper 无下载批量/实时转写")
    parser.add_argument(
        "--refresh-youtube-cookies",
        action="store_true",
        help="从本机浏览器导出 Cookie 到 macstudioyoutube.com_cookies.txt（覆盖）后退出；"
        "请先在该浏览器登录 youtube.com 并完全退出浏览器再执行",
    )
    parser.add_argument(
        "--browser",
        default=None,
        metavar="SPEC",
        help="与 --refresh-youtube-cookies 搭配，传给 yt-dlp 的 --cookies-from-browser（如 chrome、chrome:Default、brave）",
    )
    parser.add_argument("--mode", choices=["file", "realtime"], default="file", help="运行模式")
    parser.add_argument(
        "--url",
        "--link",
        action="append",
        default=None,
        dest="url",
        metavar="URL",
        help="视频链接（可多次；--link 为同义，对应 videos.json 的 link）；"
        "一旦提供则不读取 videos.json，仅处理这些 URL",
    )
    parser.add_argument(
        "--name",
        action="append",
        default=None,
        metavar="NAME",
        help="输出文件名 / videos.json 的 name（可多次）。"
        "与 --url/--link 联用时按顺序对齐；仅传 --name 时从 videos.json 按 name 筛选",
    )
    parser.add_argument(
        "--title",
        action="append",
        default=None,
        metavar="TITLE",
        help="可选，对应 videos.json 的 title；与 --url/--link 按下标对齐",
    )
    parser.add_argument(
        "--shottitle",
        action="append",
        default=None,
        metavar="SHOTTITLE",
        help="可选，对应 videos.json 的 shottitle；与 --url/--link 按下标对齐",
    )
    parser.add_argument(
        "--item",
        "--json",
        action="append",
        default=None,
        dest="item",
        metavar="JSON",
        help='直接传入与 videos.json 条目相同的 JSON 对象（可多次），例如 '
        '\'{"name":"yanchi20260713","link":"https://...","title":"...","shottitle":"..."}\'；'
        "也支持 JSON 数组或 .json 文件路径；与 --url/--name 等互斥",
    )
    parser.add_argument(
        "--content-id",
        action="append",
        default=None,
        dest="content_id",
        metavar="ID",
        help="币安广场 contentId（可多次）；自动拼成 "
        "https://www.binance.com/zh-CN/square/audio/replay?id=ID ；"
        "输出到 output/作者_年月日时分秒.txt",
    )
    parser.add_argument(
        "--author",
        action="append",
        default=None,
        metavar="AUTHOR",
        help="与 --content-id 对齐的作者名（可多次）；缺省则尝试从币安详情接口读取昵称",
    )
    parser.add_argument("--host", default=REALTIME_HOST, help="realtime 模式监听地址")
    parser.add_argument("--port", type=int, default=REALTIME_PORT, help="realtime 模式监听端口")
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="强制使用 CPU 转写（默认尽量使用 GPU/CUDA；无可用 GPU 时仍为 CPU）",
    )
    args = parser.parse_args()

    configure_whisper_device(force_cpu=args.cpu)

    if args.refresh_youtube_cookies:
        spec = (args.browser or os.environ.get("YOUTUBE_COOKIES_FROM_BROWSER", "chrome")).strip()
        raise SystemExit(refresh_youtube_cookies_cli(spec))

    if args.mode == "file":
        try:
            run_file_mode(
                cli_urls=args.url or [],
                cli_names=args.name or [],
                cli_titles=args.title or [],
                cli_shottitles=args.shottitle or [],
                cli_json_items=args.item or [],
                cli_content_ids=args.content_id or [],
                cli_authors=args.author or [],
            )
        except ValueError as e:
            parser.error(str(e))
    else:
        if args.url or args.name or args.title or args.shottitle or args.item or args.content_id:
            parser.error(
                "realtime 模式不支持 --item/--json/--url/--link/--name/--title/--shottitle/--content-id，"
                "请使用 file 模式或 WebSocket 下发任务"
            )
        asyncio.run(run_realtime_mode(args.host, args.port))
