"""Gemini API（Google）で判定する。

    ・APIキーは .env の GEMINI_API_KEY から読み、ヘッダー x-goog-api-key に付ける（URLには入れない）
    ・temperature は 0、答えは JSON の形で返すよう指定する
    ・回数の上限（429 / RESOURCE_EXHAUSTED）に達したら、指定された時間だけ待って再試行する
    ・1日の上限に達したら DailyLimitReached を出して止める（続きはキャッシュから再開できる）

無料枠では、送った内容がGoogleのサービス改善に使われる場合がある。
送るのは公開されている論文の一部とURLだけで、先生のデータセットの内容は送らない。
"""

from __future__ import annotations

import os
import re
import time

import requests

from .base import DailyLimitReached, LLMError, LLMProvider, LLMResponse

API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, model: str, api_key: str | None = None, session: requests.Session | None = None,
                 sleep=time.sleep, max_retries: int = 5, min_interval: float = 5.0):
        super().__init__(model)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY が設定されていません（.env に書いてください）")
        self.session = session or requests.Session()
        self._sleep = sleep
        self.max_retries = max_retries
        # 無料枠は1分あたりの回数が少ないので、呼び出しの間をあける
        # （初期値5秒＝1分12回まで。gemini-3.5-flash-lite の無料枠は1分15回なので、余裕を持たせている）
        self.min_interval = min_interval
        self._last = 0.0

    def _headers(self) -> dict:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    def list_models(self) -> list[str]:
        """このキーで使えるモデル名の一覧（generateContent に対応するもの）。"""
        r = self.session.get(f"{API_BASE}/models", headers=self._headers(), params={"pageSize": 200}, timeout=30)
        if r.status_code != 200:
            raise LLMError(f"モデル一覧を取得できません（HTTP {r.status_code}: {r.text[:200]}）")
        return sorted(m["name"].removeprefix("models/") for m in r.json().get("models", [])
                      if "generateContent" in m.get("supportedGenerationMethods", []))

    @staticmethod
    def _retry_seconds(error: dict) -> float:
        """エラーの詳細から、待つべき秒数を読む（なければ60秒）。"""
        for d in error.get("details", []):
            delay = d.get("retryDelay")
            if delay:
                m = re.match(r"([\d.]+)s", delay)
                if m:
                    return float(m.group(1)) + 1
        return 60.0

    @staticmethod
    def _is_daily_limit(error: dict) -> bool:
        """1日あたりの上限に達したかどうか（エラーの詳細に PerDay の上限名が入る）。"""
        for d in error.get("details", []):
            for v in d.get("violations", []):
                if "perday" in str(v.get("quotaId", "")).lower():
                    return True
        return False

    def generate(self, system: str, user: str) -> LLMResponse:
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": self.temperature, "responseMimeType": "application/json"},
        }
        for attempt in range(self.max_retries + 1):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = time.monotonic()
            start = time.monotonic()
            try:
                r = self.session.post(f"{API_BASE}/models/{self.model}:generateContent", headers=self._headers(),
                                      json=body, timeout=(10, 150))  # 混雑時に長く待ち続けないよう150秒で区切る
            except requests.RequestException as e:
                if attempt < self.max_retries:
                    self._sleep(min(2 ** attempt * 5, 120))
                    continue
                raise LLMError(f"Gemini への接続に失敗しました: {e}") from e
            seconds = time.monotonic() - start

            if r.status_code == 200:
                data = r.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    reason = (data.get("promptFeedback") or {}).get("blockReason", "不明")
                    raise LLMError(f"Gemini が答えを返しませんでした（理由: {reason}）")
                parts = (candidates[0].get("content") or {}).get("parts") or []
                text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                usage = data.get("usageMetadata") or {}
                return LLMResponse(
                    text=text,
                    input_tokens=int(usage.get("promptTokenCount", 0)),
                    # 考える過程（思考）のトークンも料金・上限に数えられるので、出力に含めて記録する
                    output_tokens=int(usage.get("candidatesTokenCount", 0)) + int(usage.get("thoughtsTokenCount", 0)),
                    seconds=seconds,
                    model=data.get("modelVersion", self.model),
                )

            try:
                error = r.json().get("error", {})
            except ValueError:
                error = {}
            if r.status_code == 429:
                if self._is_daily_limit(error):
                    raise DailyLimitReached("Gemini の1日の上限に達しました。明日、同じコマンドで続きから再開できます。")
                if attempt < self.max_retries:
                    self._sleep(self._retry_seconds(error))
                    continue
            elif r.status_code >= 500 and attempt < self.max_retries:
                self._sleep(min(2 ** attempt * 5, 120))
                continue
            raise LLMError(f"Gemini の呼び出しに失敗しました（HTTP {r.status_code}: {error.get('message', r.text[:200])}）")
        raise LLMError("Gemini の呼び出しに失敗しました（再試行の回数を超えました）")
