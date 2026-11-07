"""LLMを呼び出す部品の共通の形。

どのLLMも「指示文（system）と問題文（user）を渡すと、文字の答え・トークン数・時間が返る」形にそろえる。
これにより、判定の処理（research/judge.py）はLLMの種類を気にせずに済む。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str  # LLMの答え（JSONの文字列のはず）
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    model: str = ""  # 実際に答えたモデル名（サービス側で自動で切り替わることがあるため記録する）


class LLMError(Exception):
    """LLMの呼び出しに失敗したとき（再試行しても回復しなかった場合）。"""


class DailyLimitReached(LLMError):
    """無料枠の1日の上限に達したとき。ここで止めて、次の日にキャッシュから続きを再開する。"""


class LLMProvider:
    """LLMを呼び出す部品の親クラス。"""

    name = "base"
    temperature = 0.0  # 同じ入力から同じ答えが出やすいよう、ばらつきを0にする（再現性のため）

    def __init__(self, model: str):
        self.model = model

    def settings(self) -> dict:
        """記録に残す設定（キャッシュの鍵にも使う）。"""
        return {"provider": self.name, "model": self.model, "temperature": self.temperature}

    def generate(self, system: str, user: str) -> LLMResponse:
        raise NotImplementedError
