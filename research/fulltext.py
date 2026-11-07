"""論文の本文を用意する。

取り方の順番
    a. S2ORC … 1本ずつ取るAPIがなく、一括ダウンロード（s2orc で約120GB、s2orc_v2 で約180GB）しかないため、
               今は「S2ORC に本文があるか（textAvailability）」を記録するだけにする
    b. オープンアクセスのPDF … 次の候補を順に試し、既存のPDF読み込み機能（extract_urls.py）で本文を取り出す
               Semantic Scholar の openAccessPdf → arXiv 版 → OpenAlex のPDF → 先生のシートのURL（PDFの場合）
               （ACM の dl.acm.org は自動取得が禁止されているので、問い合わせない）
    c. どちらも取れなければ「なし」とし、理由を記録する

取得した本文は data/cache/text/ に保存し、再実行のときはダウンロードしない。
（論文の本文は著作物なので、data/ に置いて GitHub には上げない）
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from collect_papers import PdfDownloadError, download_pdf, polite_sleep
from extract_urls import PdfOpenError, extract_link_annotations, extract_page_texts, open_pdf_bytes

SOURCE_S2ORC = "S2ORC"
SOURCE_PDF = "PDF"
SOURCE_NONE = "なし"

# ページの区切り（本文のテキストに入れておき、URL抽出などでページ番号を復元できるようにする）
PAGE_BREAK = "\n\f\n"


@dataclass
class FulltextResult:
    source: str  # S2ORC / PDF / なし
    text: str = ""
    reason: str = ""  # 取得できなかった理由
    pdf_url: str = ""
    pdf_from: str = ""  # PDFをどこで見つけたか（Semantic Scholar / arXiv / OpenAlex / 先生のシート）
    s2orc_available: bool = False  # Semantic Scholar が本文を持っているか（textAvailability が fulltext）
    pages: int = 0
    links: list[list[str]] = field(default_factory=list)  # ページごとのハイパーリンク（リンク注釈）のURL

    @property
    def page_texts(self) -> list[str]:
        return self.text.split(PAGE_BREAK) if self.text else []


def _cache_file(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}.txt"


def _links_file(cache_dir: Path, key: str) -> Path:
    """本文と同じ名前で、ハイパーリンクを保存するファイル（.links.json）。"""
    return _cache_file(cache_dir, key).with_suffix(".links.json")


def load_cached(pdf_url: str, cache_dir: str | Path = "data/cache/text") -> tuple[list[str], list[list[str]]] | None:
    """保存した本文とハイパーリンクを読み込む。どちらかがなければ None。

    戻り値: (ページごとの本文, ページごとのリンクのURL)
    """
    cache_dir = Path(cache_dir)
    text_file, links_file = _cache_file(cache_dir, pdf_url), _links_file(cache_dir, pdf_url)
    if not (text_file.exists() and links_file.exists()):
        return None
    return (text_file.read_text(encoding="utf-8").split(PAGE_BREAK),
            json.loads(links_file.read_text(encoding="utf-8")))


# 自動取得が禁止されているサイト。問い合わせ自体を送らない（ACM はボット対策で 403 を返す）
BLOCKED_HOSTS = ("dl.acm.org",)


def candidate_pdf_urls(paper: dict | None, extra: list[tuple[str, str]] = ()) -> list[tuple[str, str]]:
    """試すPDFのURLを、(取得元の名前, URL) の形で良さそうな順に並べる（重複は除く）。

    1. Semantic Scholar の openAccessPdf
    2. arXiv 版（Semantic Scholar が arXiv の ID を知っている場合）
    3. 呼び出し側が渡す候補（OpenAlex のPDF、先生のシートのURLがPDFの場合など）
    """
    out: list[tuple[str, str]] = []
    if paper:
        url = ((paper.get("openAccessPdf") or {}).get("url") or "").strip()
        if url:
            out.append(("Semantic Scholar", url))
        arxiv = (paper.get("externalIds") or {}).get("ArXiv")
        if arxiv:
            out.append(("arXiv", f"https://arxiv.org/pdf/{arxiv}"))
    out += [(label, url.strip()) for label, url in extra if url and url.strip()]
    seen, unique = set(), []
    for label, url in out:
        if url not in seen:
            seen.add(url)
            unique.append((label, url))
    return unique


def _blocked(url: str) -> bool:
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return any(host == b or host.endswith("." + b) for b in BLOCKED_HOSTS)


def get_fulltext(paper: dict | None, extra_urls: list[tuple[str, str]] = (),
                 cache_dir: str | Path = "data/cache/text",
                 download=download_pdf, wait=polite_sleep) -> FulltextResult:
    """論文の本文を用意する。PDFの候補を順に試し、最初に本文が取れたものを使う。

    paper: Semantic Scholar の論文情報（見つからなければ None）
    extra_urls: ほかのPDFの候補 [(取得元の名前, URL), ...]
    """
    s2orc = bool(paper) and (paper.get("textAvailability") or "") == "fulltext"
    candidates = candidate_pdf_urls(paper, extra_urls)
    if not candidates:
        reason = "Semantic Scholar で論文が見つからない" if not paper else "オープンアクセスのPDFがない"
        if s2orc:
            reason += "（S2ORCには本文あり。一括ダウンロードが必要）"
        return FulltextResult(SOURCE_NONE, reason=reason, s2orc_available=s2orc)

    cache_dir = Path(cache_dir)
    failures = []
    for label, url in candidates:
        # 本文とハイパーリンクの両方が保存済みなら、ダウンロードしない
        cached = load_cached(url, cache_dir)
        if cached:
            pages, links = cached
            return FulltextResult(SOURCE_PDF, text=PAGE_BREAK.join(pages), pdf_url=url, pdf_from=label,
                                  s2orc_available=s2orc, pages=len(pages), links=links)
        if _blocked(url):
            failures.append(f"{label}: 自動取得が禁止されているサイト（{url.split('/')[2]}）")
            continue
        try:
            data = download(url)
            with open_pdf_bytes(data, url) as doc:
                pages = extract_page_texts(doc)
                links = [extract_link_annotations(page) for page in doc]
        except (PdfDownloadError, PdfOpenError) as e:
            failures.append(f"{label}: {e}")
            continue
        finally:
            wait(1.0)  # 相手のサーバーに負担をかけないよう、PDFの取得ごとに間をあける
        text = PAGE_BREAK.join(pages)
        if len(text.strip()) < 200:
            # 画像だけのPDF（スキャン）などは文字が取れない
            failures.append(f"{label}: PDFから文字を取り出せない（画像のみの可能性）")
            continue
        text_file = _cache_file(cache_dir, url)
        text_file.parent.mkdir(parents=True, exist_ok=True)
        text_file.write_text(text, encoding="utf-8")
        _links_file(cache_dir, url).write_text(json.dumps(links, ensure_ascii=False), encoding="utf-8")
        return FulltextResult(SOURCE_PDF, text=text, pdf_url=url, pdf_from=label, s2orc_available=s2orc,
                              pages=len(pages), links=links)

    return FulltextResult(SOURCE_NONE, reason="PDFを取得できない（" + " / ".join(failures) + "）",
                          pdf_url=candidates[0][1], s2orc_available=s2orc)
