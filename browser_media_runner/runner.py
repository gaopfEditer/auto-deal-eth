"""
资源列表 + 提示词输入 -> 直接上传到 Gemini 网页版分析。

注意：
- 不做浏览器截图
- 不做下载直链图片
- 不走 Gemini REST
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from gemini_web_automation import analyze_resources_with_gemini_web

PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_PROMPTS_DIR = PACKAGE_DIR / "prompts"
DEFAULT_HISTORY_DIR = PACKAGE_DIR / "history"

def default_prompts_dir() -> Path:
    return DEFAULT_PROMPTS_DIR


def default_history_dir() -> Path:
    return DEFAULT_HISTORY_DIR


def _is_http(s: str) -> bool:
    t = (s or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def _sanitize_resource(raw: str) -> str:
    """
    清洗命令行/复制粘贴带入的异常前缀与不可见字符。
    典型问题：'?D:\\a.png'、含 LRM/RLM 等方向控制字符。
    """
    s = str(raw or "").strip().strip("\"'").strip()
    # 删除常见不可见控制字符（如 U+202A/U+200E 等）
    s = "".join(ch for ch in s if ch.isprintable() and not ch.isspace())
    # 某些终端会把本地路径前缀带上 '?'
    if s.startswith("?") and len(s) >= 3 and s[2:3] in (":", "\\"):
        s = s[1:]
    return s


def _is_http(s: str) -> bool:
    t = (s or "").strip().lower()
    return t.startswith("http://") or t.startswith("https://")


def load_prompt(prompt_name: str, prompts_dir: Optional[Path] = None) -> str:
    """prompt_name 为文件名（可含子路径如 domain/foo.txt，需真实存在）。"""
    base = Path(prompts_dir or DEFAULT_PROMPTS_DIR).resolve()
    # 禁止跳出 prompts 根目录
    candidate = (base / prompt_name).resolve()
    if not str(candidate).startswith(str(base)):
        raise ValueError(f"非法提示词路径: {prompt_name}")
    if not candidate.is_file():
        raise FileNotFoundError(f"提示词文件不存在: {candidate}")
    return candidate.read_text(encoding="utf-8").strip()


def analyze_resources(
    resources: Sequence[str],
    prompt_input: str,
    *,
    prompts_dir: Optional[Union[str, Path]] = None,
    history_dir: Optional[Union[str, Path]] = None,
    use_remote_debugging: Optional[bool] = None,  # 兼容保留，当前不在 runner 内使用
    domain_tag: str = "",
    save_history: bool = True,
    prompt_is_text: bool = False,
) -> Dict[str, Any]:
    """
    主入口：资源列表与提示词均作为输入，直接交给 Gemini 网页版上传分析。
    - 不做截图、不做下载、不走 REST。
    - resources 支持本地文件路径与 URL（URL 会在 gemini_web_automation 中先截图后上传）。
    """
    hroot = Path(history_dir or DEFAULT_HISTORY_DIR).resolve()
    pdir = Path(prompts_dir or DEFAULT_PROMPTS_DIR).resolve()
    if prompt_is_text:
        prompt_text = (prompt_input or "").strip()
        prompt_name = "<inline>"
    else:
        prompt_name = prompt_input
        prompt_text = load_prompt(prompt_name, pdir)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    if save_history:
        work = hroot / run_id
        work.mkdir(parents=True, exist_ok=True)
    else:
        work = Path(tempfile.mkdtemp(prefix=f"bmr_{run_id}_"))

    files: List[str] = []
    skipped: List[Dict[str, Any]] = []
    for x in resources:
        s = _sanitize_resource(str(x))
        if not s:
            continue
        if _is_http(s):
            files.append(s)
        elif os.path.isfile(s):
            files.append(os.path.abspath(s))
        else:
            skipped.append({"kind": "skip", "source": s, "detail": "非本地文件路径"})

    if not files:
        out = {
            "ok": False,
            "error": "没有可上传的本地文件资源",
            "domain_tag": domain_tag,
            "prompt_name": prompt_name,
            "run_id": run_id,
            "history_dir": str(work) if save_history else str(work),
            "resources": [],
            "resource_meta": skipped,
        }
        if save_history:
            (work / "result.json").write_text(
                json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        return out

    web_result = analyze_resources_with_gemini_web(
        files, prompt_text, symbol=domain_tag or "resource_batch", keep_browser_open=False
    )
    out: Dict[str, Any] = {
        "ok": bool(web_result.get("ok")),
        "domain_tag": domain_tag,
        "prompt_name": prompt_name,
        "run_id": run_id,
        "history_dir": str(work) if save_history else str(work),
        "resources": files,
        "resource_meta": skipped,
        "web_result": web_result,
    }

    if save_history:
        (work / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        (work / "resources.json").write_text(
            json.dumps(list(resources), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (work / "resource_meta.json").write_text(
            json.dumps(skipped, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (work / "web_result.json").write_text(
            json.dumps(web_result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (work / "result.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return out


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(
        description="browser_media_runner：资源列表 + 提示词输入 -> Gemini 网页端上传分析"
    )
    ap.add_argument(
        "resources",
        nargs="+",
        help="本地图片路径或 http(s) 链接，可多枚",
    )
    ap.add_argument(
        "-p",
        "--prompt",
        required=True,
        help="提示词输入；默认按 prompts 目录中的文件名解析",
    )
    ap.add_argument(
        "--prompt-text",
        action="store_true",
        help="将 --prompt 视为提示词正文，而非文件名",
    )
    ap.add_argument(
        "--prompts-dir",
        default="",
        help="提示词根目录，默认包内 prompts/",
    )
    ap.add_argument(
        "--history-dir",
        default="",
        help="history 根目录，默认包内 history/",
    )
    ap.add_argument(
        "--tag",
        default="",
        help="业务域标签，写入结果 JSON",
    )
    ap.add_argument("--no-history", action="store_true", help="不写 history 子目录")
    args = ap.parse_args()

    result = analyze_resources(
        args.resources,
        args.prompt,
        prompt_is_text=args.prompt_text,
        prompts_dir=args.prompts_dir or None,
        history_dir=args.history_dir or None,
        domain_tag=args.tag,
        save_history=not args.no_history,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
