#!/usr/bin/env python3
"""
gemini 模块使用示例。

运行前确保 .env 中已配置：
  GEMINI_API_KEY=你的密钥
  GEMINI_MODEL=gemini-2.5-flash（或你想用的模型）

用法：
    python gemini/demo.py                    # 文本 + 图片生成
    python gemini/demo.py --text-only        # 仅文本
    python gemini/demo.py --img-only         # 仅图片生成
    python gemini/demo.py --analyze          # 图片理解
    python gemini/demo.py -p "自定义文案"    # 自定义文案（默认文本+图片）
    python gemini/demo.py --text-only -p "解释 DeFi"
"""
import argparse
import sys
import os

# 确保项目根在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pathlib import Path
from dotenv import load_dotenv
from PIL import Image

load_dotenv(Path(__file__).parent.parent / ".env")

from gemini import get_default_client


def demo_text(client, prompt: str = None):
    """文本生成"""
    print("\n[1] 文本生成")
    if not prompt:
        prompt = "用一句话介绍以太坊"
    print(f"    prompt: {prompt!r}")
    text = client.generate_text(prompt)
    print(f"    result: {text[:200]!r}")
    return text


def demo_image(client, prompt: str = None):
    """图片生成"""
    print("\n[2] 图片生成")
    if not prompt:
        prompt = "A simple red circle on white background"
    print(f"    prompt: {prompt!r}")
    img = client.generate_image(prompt, aspect_ratio="1:1")
    out = Path(__file__).parent / "demo_output.png"
    img.convert("RGB").save(out, quality=92)
    print(f"    saved: {out}  size={img.size}")
    return img


def demo_analyze(client, prompt: str = None):
    """图片理解"""
    # 先确保有一张测试图
    demo_img_path = Path(__file__).parent / "demo_output.png"
    if not demo_img_path.exists():
        print("[!] demo_output.png 不存在，先跑 --img-only 生成一张")
        demo_image(client)

    print("\n[3] 图片理解")
    print(f"    image: {demo_img_path}")
    if not prompt:
        prompt = "用一句话描述这张图片的内容"
    result = client.analyze_image(
        str(demo_img_path),
        prompt=prompt,
    )
    print(f"    result: {result[:200]!r}")
    return result


def main():
    parser = argparse.ArgumentParser(description="gemini 模块演示")
    parser.add_argument("--text-only", action="store_true", help="仅文本生成")
    parser.add_argument("--img-only", action="store_true", help="仅图片生成")
    parser.add_argument("--analyze", action="store_true", help="仅图片理解")
    parser.add_argument("-p", "--prompt", type=str, default=None,
                        help="自定义文案（用于文本生成 / 图片描述 / 图片理解）")
    args = parser.parse_args()

    print("初始化 Gemini 客户端...")
    try:
        client = get_default_client()
    except Exception as e:
        print(f"[ERROR] 客户端初始化失败: {e}")
        sys.exit(1)

    print(f"使用模型: {client.model}")
    print(f"API Key 尾缀: ...{client.api_key[-6:]}")

    if args.img_only:
        demo_image(client, args.prompt)
    elif args.analyze:
        demo_analyze(client, args.prompt)
    elif args.text_only:
        demo_text(client, args.prompt)
    else:
        demo_text(client, args.prompt)
        try:
            demo_image(client, args.prompt)
        except Exception as e:
            print(f"[WARN] 图片生成跳过: {e}")


if __name__ == "__main__":
    main()
