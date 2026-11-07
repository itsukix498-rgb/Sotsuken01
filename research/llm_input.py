"""LLMに渡す文章を作る（段階3）。

論文の全文は渡さず、判断に必要な部分だけを渡す。
  ・各URLの前後の文章（前後300文字）
  ・データについて書かれた文（dataset、data are available、upon request などを含む文）
  ・参考文献の章にあるURLは【参考文献】の印を付け、前後の文章は省いてURLだけを渡す（文字数の節約）
  ・データと明らかに関係ないURL（文献管理ソフトや研究者IDのリンク）はルールで除外し、LLMには渡さない

ここで使うのは論文の本文とURLだけ。先生のデータセットの内容（答え）は使わない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from extract_urls import UrlRecord, normalize_url

CONTEXT_CHARS = 300  # URLの前後に付ける文字数
MAX_DATA_SENTENCES = 25  # データについて書かれた文の上限
MAX_SENTENCE_CHARS = 400  # 1文の長さの上限（長すぎる文は切る）

# データと明らかに関係ないURL（LLMには渡さず「公開先ではない」とする）
NON_DATA_HOSTS = ("paperpile.com", "orcid.org")

# 参考文献の章の見出し（行の中にこれだけが書かれている場合）
REFERENCES_HEADING = re.compile(r"^\s*(?:\d+\.?\s*)?(references|bibliography|reference list|参考文献|引用文献)\s*$",
                                re.IGNORECASE | re.MULTILINE)

# データについて書かれた文を見つけるための言い回し
DATA_PATTERNS = [
    r"\bdata ?sets?\b", r"\bdata (?:are|is|were|was|will be) (?:publicly |freely |openly )?(?:available|shared|accessible)",
    r"\bavailable (?:up)?on (?:reasonable )?request\b", r"\bupon request\b", r"\bon request\b",
    r"\bpublicly available\b", r"\bopenly available\b", r"\bfreely available\b", r"\bopen data\b",
    r"\bdata availability\b", r"\bavailability of data\b", r"\brepository\b",
    r"\bgithub\b", r"\bzenodo\b", r"\bosf\b", r"\bkaggle\b", r"\bfigshare\b", r"\bdataverse\b", r"\bdatashop\b",
    r"\bhugging ?face\b", r"\bprivacy\b", r"\bIRB\b", r"\bethic(?:s|al)\b", r"\bconfidential",
    r"\bcannot be (?:shared|made available|released)\b", r"\bnot (?:be )?(?:publicly )?(?:shared|available|released)\b",
    r"\bcontact the (?:corresponding )?authors?\b",
]
DATA_REGEX = re.compile("|".join(DATA_PATTERNS), re.IGNORECASE)


@dataclass
class UrlItem:
    id: str  # LLMに見せるID（U1, U2, ...）
    url: str
    page: int
    source: str  # text / annotation / text+annotation
    in_references: bool = False
    context: str = ""  # URLの前後の文章（参考文献の章のURLでは空）


@dataclass
class LlmInput:
    title: str
    urls: list[UrlItem] = field(default_factory=list)
    data_sentences: list[str] = field(default_factory=list)
    excluded_urls: list[str] = field(default_factory=list)  # ルールで除外したURL

    def render_urls(self) -> str:
        if not self.urls:
            return "(no URLs found)"
        lines = []
        for u in self.urls:
            mark = " [REFERENCE LIST]" if u.in_references else ""
            lines.append(f"{u.id}: {u.url} (page {u.page}){mark}")
            if u.context:
                lines.append(f'    context: "...{u.context}..."')
        return "\n".join(lines)

    def render_data_sentences(self) -> str:
        if not self.data_sentences:
            return "(no sentences about data found)"
        return "\n".join(f"- {s}" for s in self.data_sentences)


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def find_references_start(full_text: str) -> int:
    """参考文献の章が始まる位置（文字の位置）。見つからなければ本文の長さ（＝参考文献なし）。

    見出しが複数ある場合（目次など）は、本文の後半にある最後の見出しを使う。
    """
    starts = [m.start() for m in REFERENCES_HEADING.finditer(full_text)]
    starts = [s for s in starts if s > len(full_text) * 0.3]
    return starts[-1] if starts else len(full_text)


def _find_url_position(full_text: str, url: str) -> int:
    """本文の中でURLが出てくる位置。改行で切れている場合に備えて、前半だけでも探す。見つからなければ -1。"""
    candidates = [url, url.split("://", 1)[-1]]
    candidates.append(candidates[-1][:30])
    flat = full_text.replace("\n", "")
    for c in candidates:
        if len(c) < 8:
            continue
        pos = full_text.find(c)
        if pos >= 0:
            return pos
        pos = flat.find(c)
        if pos >= 0:
            # 改行を除いた位置を、元の文章の位置にだいたい戻す
            return min(pos + full_text[:pos].count("\n"), len(full_text) - 1)
    return -1


def extract_data_sentences(text: str, limit: int = MAX_DATA_SENTENCES) -> list[str]:
    """データについて書かれた文を、出てきた順に取り出す（重複は除く）。"""
    flat = _squash(text)
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\[])", flat)
    found, seen = [], set()
    for s in sentences:
        if not DATA_REGEX.search(s):
            continue
        s = s[:MAX_SENTENCE_CHARS]
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(s)
        if len(found) >= limit:
            break
    return found


def build_llm_input(title: str, page_texts: list[str], records: list[UrlRecord]) -> LlmInput:
    """論文1本分の、LLMに渡す材料を作る。"""
    # ページの位置を覚えておくため、ページを改行2つでつないで1つの文章にする
    full_text = "\n\n".join(page_texts)
    ref_start = find_references_start(full_text)
    result = LlmInput(title=title)

    n = 0
    for r in records:
        host = r.url.split("//", 1)[-1].split("/", 1)[0].lower().removeprefix("www.")
        if any(host == h or host.endswith("." + h) for h in NON_DATA_HOSTS):
            result.excluded_urls.append(r.url)
            continue
        n += 1
        pos = _find_url_position(full_text, r.url)
        in_refs = pos >= ref_start if pos >= 0 else False
        context = ""
        if pos >= 0 and not in_refs:
            context = _squash(full_text[max(0, pos - CONTEXT_CHARS): pos + len(r.url) + CONTEXT_CHARS])
        result.urls.append(UrlItem(id=f"U{n}", url=r.url, page=r.page, source=r.source,
                                   in_references=in_refs, context=context))

    # データについて書かれた文は、参考文献の章より前の本文から探す
    result.data_sentences = extract_data_sentences(full_text[:ref_start])
    return result


def same_url(a: str, b: str) -> bool:
    """表記の違い（https:// の有無、末尾の / など）を無視して同じURLか。"""
    return normalize_url(a) == normalize_url(b)
