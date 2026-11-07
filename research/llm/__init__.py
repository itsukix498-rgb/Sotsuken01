"""LLMの呼び出しを切り替えるための部品。

使えるLLM
    gemini … Gemini API（無料枠あり。APIキーは .env の GEMINI_API_KEY）
    ollama … Ollama（自分のPCで動くLLM。外部には何も送らない）

新しいLLM（Claude、GPTなど）を追加するときは、base.LLMProvider を受け継いだクラスを
このフォルダに作り、下の PROVIDERS に名前を足す。
"""

from __future__ import annotations

from .base import DailyLimitReached, LLMError, LLMProvider, LLMResponse


def get_provider(name: str, model: str, **kwargs) -> LLMProvider:
    """名前とモデル名から、LLMを呼び出す部品を作る。"""
    if name == "gemini":
        from .gemini import GeminiProvider
        return GeminiProvider(model, **kwargs)
    if name == "ollama":
        from .ollama import OllamaProvider
        return OllamaProvider(model, **kwargs)
    raise ValueError(f"使えないLLMの名前です: {name}（使えるのは {PROVIDERS}）")


PROVIDERS = ("gemini", "ollama")

__all__ = ["DailyLimitReached", "LLMError", "LLMProvider", "LLMResponse", "PROVIDERS", "get_provider"]
