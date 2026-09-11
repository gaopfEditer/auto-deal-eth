"""
gemini 模块：封装 google-genai 客户端，复用 .env 中的 GEMINI_API_KEY / GEMINI_MODEL。
"""
from gemini.client import GeminiClient, get_default_client

__all__ = ["GeminiClient", "get_default_client"]
