"""Gemini 文生图 demo（Nano Banana / generate_content）。

用法:
  python demos/gemini_generate_img.py
  # 或
  $env:GEMINI_API_KEY="..."
  $env:GEMINI_IMAGE_MODEL="gemini-2.5-flash-image"
  python demos/gemini_generate_img.py
"""

from __future__ import annotations

import os
import sys
from io import BytesIO
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai import errors as genai_errors
from PIL import Image

# Windows 控制台避免 emoji / 中文乱码导致二次崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

api_key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
if not api_key:
    raise SystemExit("请先在 .env 或环境变量中设置 GEMINI_API_KEY")

client = genai.Client(api_key=api_key)
out_dir = Path(__file__).resolve().parent
prompt = os.environ.get(
    "GEMINI_IMAGE_PROMPT",
    "A cinematic cyberpunk street with neon signs, trading charts floating in the air, 8k resolution",
)
# 默认用稳定版；旧 preview 模型名已下线
model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image").strip()
if model in {
    "gemini-2.0-flash-preview-image-generation",
    "imagen-3.0-generate-002",
}:
    print(f"[warn] 模型 {model} 已废弃，改用 gemini-2.5-flash-image")
    model = "gemini-2.5-flash-image"
# 备注：文本模型现推荐 gemini-3.6-flash；生图需付费配额（free_tier 常为 0）

print(f"使用模型: {model}")
print(f"密钥指纹: ...{api_key[-6:]} (len={len(api_key)})")

try:
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio="16:9"),
        ),
    )
except genai_errors.ClientError as e:
    msg = str(e)
    if "leaked" in msg.lower():
        print("[FAIL] 当前 API Key 已被标记泄露，Google 拒绝使用")
        print("       -> 到 AI Studio 作废旧钥并生成新钥，更新 .env 的 GEMINI_API_KEY")
        print(f"       详情: {msg[:400]}")
        sys.exit(6)
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg or "quota" in msg.lower():
        print("[FAIL] 配额不足（free_tier limit:0 通常表示未开通付费/该模型无免费额度）")
        print("       -> 去 Google AI Studio 开通 Billing，或换一把有配额的密钥")
        print(f"       详情: {msg[:400]}")
        sys.exit(2)
    if "FAILED_PRECONDITION" in msg and "location" in msg.lower():
        print("[FAIL] 当前地区不支持该 Gemini API（User location is not supported）")
        print("       -> 需要代理/换区，或改用项目里的 browser_media_runner 网页生图")
        print(f"       详情: {msg[:400]}")
        sys.exit(3)
    if "404" in msg or "NOT_FOUND" in msg:
        print("[FAIL] 模型不存在或当前密钥无权限")
        print("       -> 试: gemini-2.5-flash-image / gemini-3.1-flash-image")
        print(f"       详情: {msg[:400]}")
        sys.exit(4)
    print(f"[FAIL] API 错误: {msg[:600]}")
    sys.exit(1)

saved = 0
parts = getattr(response, "parts", None) or []
if not parts and getattr(response, "candidates", None):
    parts = response.candidates[0].content.parts or []

for part in parts:
    if getattr(part, "text", None):
        print(f"文本: {part.text}")
    inline = getattr(part, "inline_data", None)
    if inline is not None and getattr(inline, "data", None):
        image = Image.open(BytesIO(inline.data))
        out_path = out_dir / f"gemini_output_{saved}.jpg"
        image.convert("RGB").save(out_path, format="JPEG", quality=92)
        print(f"[OK] 图片已生成并保存: {out_path}")
        saved += 1

if saved == 0:
    print("[WARN] 未返回图片，请检查模型权限/配额/地区是否支持图像生成")
    print(response)
    sys.exit(5)

print(f"完成，共 {saved} 张")
