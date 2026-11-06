"""保存した論文の本文とハイパーリンクから、URLを抽出する（段階2）。

アプリの「URLを抽出」と同じ仕組み（extract_urls.py）を使う。
  ・本文から：改行で切れたURLの結合、末尾の記号の除去、スキームなしURL、日本語の文中のURL
  ・ハイパーリンク（リンク注釈）から：PDFの中のクリックできるリンク
  ・両方を統合し、同じURLは1件にまとめて、最初に出てきたページ番号を記録する
LLMは使わない（無料）。
"""

from __future__ import annotations

from extract_urls import UrlRecord, extract_urls_from_text, merge_url_records


def extract_from_pages(page_texts: list[str], page_links: list[list[str]]) -> list[UrlRecord]:
    """ページごとの本文とリンクからURLを抽出する（ページ番号は1始まり）。"""
    page_results = []
    for i, text in enumerate(page_texts):
        links = page_links[i] if i < len(page_links) else []
        page_results.append((i + 1, extract_urls_from_text(text), list(links)))
    return merge_url_records(page_results)
