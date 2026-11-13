"""AIが示した「根拠の文」が、論文の本文に本当にあるかを確かめる。

プロンプトでは「根拠の文は、渡した抜粋からそのまま写す」と指示しているが、AIが文を言い換えたり、
本文にない文を作ったりしても、答えの形の確認（research/judge.py）では見つけられない。
そこで、根拠の文を論文の本文から探し、次の3つに分ける。あわせて、見つかったページも返す。

    一致      … 本文に同じ文がある（空白・改行・引用符・行末のハイフンなどの違いは無視する）
    ほぼ一致  … 同じ文はないが、よく似た文がある（AIが少し言い換えた、など）
    見つからない … 本文に同じ文も似た文もない（AIが作った文の可能性がある）

AIへの入力は変えないので、すでに判定した結果（保存した答え）にも、あとから使える。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

MATCH = "一致"
NEAR = "ほぼ一致"
NOT_FOUND = "見つからない"
EMPTY = "なし"

NEAR_RATIO = 0.85  # これ以上似ていれば「ほぼ一致」
MIN_CHARS = 12  # これより短い根拠（単語だけなど）は、どこにでも見つかってしまうので確かめない

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-", "­": "", " ": " "})
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}


def normalize(text: str) -> str:
    """比べるために文を整える（小文字、引用符・ダッシュをそろえる、行末のハイフンでの改行をつなぐ、空白をまとめる）。"""
    for a, b in _LIGATURES.items():
        text = text.replace(a, b)
    text = text.translate(_QUOTES)
    # 行末のハイフンで切れた単語をつなぐ。AIに渡した抜粋では改行が空白になっている（"avail- able"）ので、空白の場合もつなぐ
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    # 単語の中のハイフンも消す（"open-source" が改行で "open-\nsource" になっていても、同じ文とみなすため）
    text = re.sub(r"(\w)-(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    # AIが抜粋の印（"...前後の文章..."）や引用符ごと写したときのために、前後の記号を取る
    return text.strip(" .…\"'")


def _sentences(page: str) -> list[str]:
    flat = re.sub(r"\s+", " ", page)
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", flat) if len(s) >= MIN_CHARS]


@dataclass
class EvidenceCheck:
    status: str  # 一致 / ほぼ一致 / 見つからない / なし
    page: int | None = None  # 見つかったページ（1始まり）

    @property
    def label(self) -> str:
        """画面に出す短い表示。"""
        if self.status == MATCH:
            return f"本文の {self.page} ページにあり"
        if self.status == NEAR:
            return f"似た文が {self.page} ページにあり"
        if self.status == NOT_FOUND:
            return "本文に見つからない"
        return "—"


def check_evidence(evidence: str | None, pages: list[str]) -> EvidenceCheck:
    """根拠の文を、論文のページごとの本文から探す。"""
    if not evidence or len(evidence.strip()) < MIN_CHARS:
        return EvidenceCheck(EMPTY)
    target = normalize(evidence)

    # 1. 同じ文があるか（ページごとに探す）
    normalized_pages = [normalize(p) for p in pages]
    for i, page in enumerate(normalized_pages, start=1):
        if target in page:
            return EvidenceCheck(MATCH, i)
    # ページの境目をまたぐ場合もあるので、全体をつないでも探す
    joined = ""
    starts = []
    for page in normalized_pages:
        starts.append(len(joined))
        joined += page + " "
    pos = joined.find(target)
    if pos >= 0:
        page_no = max(i for i, s in enumerate(starts, start=1) if s <= pos)
        return EvidenceCheck(MATCH, page_no)

    # 2. よく似た文があるか（文ごとに似ている度合いを比べ、一番似ているものを使う）
    best_ratio, best_page = 0.0, None
    for i, page in enumerate(pages, start=1):
        for sentence in _sentences(page):
            s = normalize(sentence)
            # 長さが大きく違う文は比べない（速くするため）
            if not (0.5 * len(target) <= len(s) <= 2.0 * len(target)):
                continue
            ratio = SequenceMatcher(None, target, s).ratio()
            if ratio > best_ratio:
                best_ratio, best_page = ratio, i
    if best_ratio >= NEAR_RATIO:
        return EvidenceCheck(NEAR, best_page)

    # 3. 文が途中で分かれていないか（ページの境目や脚注をまたいだ文を、AIがつないで写した場合）
    page_no = _found_in_pieces(target, joined, starts)
    if page_no:
        return EvidenceCheck(NEAR, page_no)
    return EvidenceCheck(NOT_FOUND)


PIECE_CHARS = 25  # 分かれた文を探すときの、1つの断片の長さ
PIECE_RATIO = 0.8  # 断片のうち、これ以上の割合が順番どおりに見つかれば「似た文あり」とする


def _found_in_pieces(target: str, joined: str, starts: list[int]) -> int | None:
    """根拠の文を短い断片に分け、ほとんどの断片が本文に順番どおり、近い範囲で見つかるかを調べる。

    例：文の前半が2ページ目の最後、後半が3ページ目の最初にあり、間に脚注が挟まっている場合。
    見つかれば、最初の断片があったページを返す。
    """
    pieces = [target[i:i + PIECE_CHARS] for i in range(0, len(target), PIECE_CHARS)]
    pieces = [p for p in pieces if len(p) >= 10]
    if len(pieces) < 2:
        return None
    window = 3 * len(target) + 300  # 間に挟まる脚注などの長さを見込む
    pos = joined.find(pieces[0])
    while pos >= 0:
        found, cursor = 1, pos + len(pieces[0])
        for piece in pieces[1:]:
            nxt = joined.find(piece, cursor, pos + window)
            if nxt >= 0:
                found, cursor = found + 1, nxt + len(piece)
        if found / len(pieces) >= PIECE_RATIO:
            return max(i for i, s in enumerate(starts, start=1) if s <= pos)
        pos = joined.find(pieces[0], pos + 1)
    return None
