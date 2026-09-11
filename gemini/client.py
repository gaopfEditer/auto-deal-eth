"""
Gemini 客户端封装。

环境变量（来自 .env）：
  GEMINI_API_KEY   - API 密钥
  GEMINI_MODEL     - 默认模型，默认 gemini-2.5-flash
  GEMINI_REQUEST_TIMEOUT - 请求超时（秒），默认 45

用法示例：
  from gemini import get_default_client
  client = get_default_client()
  resp = client.generate_text("Hello")
  resp = client.generate_image("A red circle")
"""
import os
import sys
from pathlib import Path
from typing import Literal, Optional
from functools import lru_cache

# ---------------------------------------------------------------------------
# 基础客户端
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    封装 google.genai.Client，提供文本生成和图片生成接口。

    Args:
        api_key:  API 密钥；None 则从 .env 读取 GEMINI_API_KEY。
        model:    默认模型名；None 则读取 GEMINI_MODEL（默认 gemini-2.5-flash）。
        timeout:  请求超时秒数；None 则读取 GEMINI_REQUEST_TIMEOUT（默认 45）。
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout: Optional[int] = None,
    ):
        # 延迟 import，避免全局导入失败
        from google import genai

        if api_key is None:
            api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY 未设置，请先在 .env 中配置，或传入 api_key 参数。"
            )

        self.api_key = api_key
        self.model = (model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")).strip()
        self.timeout = int(
            timeout
            if timeout is not None
            else os.getenv("GEMINI_REQUEST_TIMEOUT", "45")
        )
        self._client = genai.Client(api_key=self.api_key)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _resolve_model(self, model: Optional[str]) -> str:
        return (model or self.model).strip()

    # ------------------------------------------------------------------
    # 文本生成
    # ------------------------------------------------------------------

    def generate_text(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        纯文本生成。

        Args:
            prompt: 输入提示词。
            model:  覆盖默认模型。
            **kwargs: 透传给 models.generate_content.config。

        Returns:
            模型返回的文本字符串。
        """
        resolved = self._resolve_model(model)
        try:
            r = self._client.models.generate_content(
                model=resolved,
                contents=prompt,
            )
            return getattr(r, "text", None) or ""
        except Exception as e:
            print(f"[GeminiClient] generate_text failed: {e}", file=sys.stderr)
            raise

    def generate_text_stream(
        self,
        prompt: str,
        model: Optional[str] = None,
        **kwargs,
    ):
        """
        流式文本生成（yield 每段 text）。

        Args:
            prompt: 输入提示词。
            model:  覆盖默认模型。
            **kwargs: 透传。

        Yields:
            每段 text 内容。
        """
        resolved = self._resolve_model(model)
        try:
            for chunk in self._client.models.generate_content_stream(
                model=resolved,
                contents=prompt,
            ):
                t = getattr(chunk, "text", None)
                if t:
                    yield t
        except Exception as e:
            print(f"[GeminiClient] generate_text_stream failed: {e}", file=sys.stderr)
            raise

    # ------------------------------------------------------------------
    # 图片生成（文本指令 -> 图片）
    # ------------------------------------------------------------------

    def generate_image(
        self,
        prompt: str,
        model: Literal[
            "gemini-2.5-flash-image",
            "gemini-3.1-flash-image",
        ] = "gemini-2.5-flash-image",
        aspect_ratio: str = "1:1",
        **kwargs,
    ):
        """
        根据文本指令生成图片。

        Args:
            prompt:         图片描述文本。
            model:          生图模型，默认 gemini-2.5-flash-image。
            aspect_ratio:   比例，默认 1:1；还支持 16:9 / 9:16 / 4:3 / 3:4。
            person_generation: 是否允许出现人物，默认禁止。

        Returns:
            PIL.Image.Image 对象。
        """
        from io import BytesIO
        from PIL import Image
        from google.genai import types

        cfg = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
            ),
        )

        try:
            r = self._client.models.generate_content(
                model=model,
                contents=prompt,
                config=cfg,
            )
            # 取第一个图片 parts
            parts = getattr(r, "parts", None) or []
            if not parts and r.candidates:
                parts = r.candidates[0].content.parts or []

            for p in parts:
                inline = getattr(p, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    return Image.open(BytesIO(inline.data))

            raise RuntimeError(
                f"generate_image 返回中没有图片 parts。"
                f" 可能的免费配额不足（free_tier limit=0），"
                f" 请在 Google AI Studio 开通 Billing。"
            )
        except Exception as e:
            print(f"[GeminiClient] generate_image failed: {e}", file=sys.stderr)
            raise

    # ------------------------------------------------------------------
    # 多模态（图片理解）
    # ------------------------------------------------------------------

    def analyze_image(
        self,
        image_path: str,
        prompt: str = "描述这张图片",
        model: Optional[str] = None,
    ) -> str:
        """
        分析一张本地图片（多模态理解）。

        Args:
            image_path: 本地图片路径。
            prompt:     分析指令。
            model:      覆盖默认模型（建议用支持多模态的模型）。

        Returns:
            模型返回的文本描述。
        """
        from google.genai.types import Blob, Part
        from PIL import Image

        resolved = self._resolve_model(model)
        img = Image.open(image_path)
        img_bytes = BytesIO()
        img.save(img_bytes, format=kwargs.pop("img_format", "PNG"))
        img_bytes = img_bytes.getvalue()

        blob = Blob(data=img_bytes, mime_type="image/png")
        part = Part(inline_data=blob)

        try:
            r = self._client.models.generate_content(
                model=resolved,
                contents=[part, prompt],
            )
            return getattr(r, "text", None) or ""
        except Exception as e:
            print(f"[GeminiClient] analyze_image failed: {e}", file=sys.stderr)
            raise


# ---------------------------------------------------------------------------
# 快捷全局单例
# ---------------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_default_client() -> GeminiClient:
    """
    返回全局默认实例（单例，按 API_KEY 缓存）。
    首次调用时从 .env 读取密钥初始化。
    """
    # 加载 .env（优先项目根目录，其次 cwd）
    from dotenv import load_dotenv
    from pathlib import Path
    _repo_root = Path(__file__).resolve().parent.parent
    load_dotenv(_repo_root / ".env")
    load_dotenv()  # fallback 到 cwd
    return GeminiClient()
