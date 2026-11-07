"""Ollama（自分のPCで動くLLM）で判定する。外部には何も送らない。

    ・Ollama をインストールし、使うモデルをダウンロードしておく（例: ollama pull <モデル名>）
    ・temperature は 0、答えは JSON の形で返すよう指定する
    ・入力が長いので、読み込める文字数（num_ctx）を大きめにする（小さいと入力の後半が切り捨てられる）
"""

from __future__ import annotations

import os
import time

import requests

from .base import LLMError, LLMProvider, LLMResponse


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, model: str, base_url: str | None = None, num_ctx: int = 16384,
                 session: requests.Session | None = None):
        super().__init__(model)
        self.base_url = (base_url or os.environ.get("OLLAMA_URL") or "http://localhost:11434").rstrip("/")
        self.num_ctx = num_ctx
        self.session = session or requests.Session()

    def settings(self) -> dict:
        return {**super().settings(), "num_ctx": self.num_ctx}

    def generate(self, system: str, user: str) -> LLMResponse:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature, "num_ctx": self.num_ctx},
        }
        start = time.monotonic()
        try:
            # PCで動かすと1本に数分かかることがあるので、待ち時間は長めにする
            r = self.session.post(f"{self.base_url}/api/chat", json=body, timeout=(10, 1800))
        except requests.RequestException as e:
            raise LLMError(f"Ollama に接続できません（Ollama が起動しているか確認してください）: {e}") from e
        if r.status_code != 200:
            raise LLMError(f"Ollama の呼び出しに失敗しました（HTTP {r.status_code}: {r.text[:200]}）")
        data = r.json()
        return LLMResponse(
            text=(data.get("message") or {}).get("content", ""),
            input_tokens=int(data.get("prompt_eval_count", 0)),
            output_tokens=int(data.get("eval_count", 0)),
            seconds=time.monotonic() - start,
            model=data.get("model", self.model),
        )
