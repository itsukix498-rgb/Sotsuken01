"""論文PDFから本文中のURLとリンク注釈のURLを抽出するスクリプト。

使い方:
    python extract_urls.py paper.pdf

処理の流れ:
    1. PDF読み込み      open_pdf()
    2. テキスト抽出      extract_page_texts()
    3. URL抽出          extract_urls_from_text() / extract_link_annotations() / merge_url_records()
    4. 出力             print_records() / save_csv()
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf as fitz  # PyMuPDF（旧モジュール名 fitz）

# 取得元を表すラベル
SOURCE_TEXT = "text"
SOURCE_ANNOTATION = "annotation"


@dataclass
class UrlRecord:
    """抽出した1件のURL。page は最初に出現したページ番号（1始まり）。"""

    page: int
    url: str
    sources: list[str] = field(default_factory=list)

    @property
    def source(self) -> str:
        # 本文とリンク注釈の両方から見つかった場合は "text+annotation" になる
        return "+".join(self.sources)


class PdfOpenError(Exception):
    """PDFを開けなかったときの例外（メッセージはそのまま利用者に表示する）。"""


# ---------------------------------------------------------------------------
# 1. PDF読み込み
# ---------------------------------------------------------------------------

def open_pdf(path: str | Path) -> fitz.Document:
    """PDFファイルを開く。問題があればわかりやすいメッセージ付きで PdfOpenError を送出する。"""
    path = Path(path)
    if not path.exists():
        raise PdfOpenError(f"ファイルが見つかりません: {path}")
    if not path.is_file():
        raise PdfOpenError(f"ファイルではありません（フォルダなど）: {path}")
    if path.suffix.lower() != ".pdf":
        raise PdfOpenError(f"拡張子が .pdf ではありません: {path}")

    try:
        doc = fitz.open(path)
    except Exception as e:  # PyMuPDF は壊れたファイルで様々な例外を出すためまとめて扱う
        raise PdfOpenError(f"PDFとして開けませんでした（ファイルが壊れている可能性があります）: {path}\n  詳細: {e}") from e
    return _check_document(doc, path)


def open_pdf_bytes(data: bytes, name: str = "uploaded.pdf") -> fitz.Document:
    """メモリ上のPDF（Webアプリでアップロードされたファイルなど）を開く。"""
    if not data:
        raise PdfOpenError(f"ファイルが空です: {name}")
    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception as e:
        raise PdfOpenError(f"PDFとして開けませんでした（ファイルが壊れている可能性があります）: {name}\n  詳細: {e}") from e
    return _check_document(doc, name)


def _check_document(doc: fitz.Document, name: str | Path) -> fitz.Document:
    """開いたPDFが処理できる状態か確認する（できなければ閉じて PdfOpenError）。"""
    if not doc.is_pdf:
        doc.close()
        raise PdfOpenError(f"PDF形式のファイルではありません: {name}")
    if doc.needs_pass:
        doc.close()
        raise PdfOpenError(f"パスワードで保護されたPDFは読み込めません: {name}")
    if doc.page_count == 0:
        doc.close()
        raise PdfOpenError(f"ページが1枚もないPDFです: {name}")
    return doc


# ---------------------------------------------------------------------------
# 2. テキスト抽出
# ---------------------------------------------------------------------------

# PDF由来の不可視文字（ソフトハイフン・ゼロ幅スペースなど）。URLの途中に入ると抽出が切れるため除去する
_INVISIBLE_CHARS = dict.fromkeys(map(ord, "­​‌‍﻿"), None)


def extract_page_texts(doc: fitz.Document) -> list[str]:
    """ページごとのテキストをリストで返す（インデックス0が1ページ目）。"""
    texts = []
    for page in doc:
        text = page.get_text("text")
        texts.append(text.translate(_INVISIBLE_CHARS))
    # 拡張予定: ここで参考文献セクションを除外する処理を挟む
    return texts


# ---------------------------------------------------------------------------
# 3. URL抽出
# ---------------------------------------------------------------------------

# URLに使える文字（空白・引用符・山括弧などは含めない）
_URL_CHARS = r"[^\s<>\"'{}|\\^`“”‘’]"

# スキームなしURLとして認めるトップレベルドメイン。
# 「train.csv/test.csv」のような誤検出を避けるため、汎用的な [a-z]+ ではなく列挙する
_TLDS = (
    "com|org|net|io|edu|gov|info|ai|co|me|app|dev|ly|"
    "uk|de|jp|cn|fr|nl|au|ca|eu|ch|se|no|fi|dk|es|it|kr|tw|br|in|nz|be|at|pl|ru"
)

URL_PATTERN = re.compile(
    rf"""
    (?:https?|ftp)://{_URL_CHARS}+                       # スキームあり
    |
    (?<![@\w.\-/])www\.{_URL_CHARS}+                    # www. で始まるもの
    |
    (?<![@\w.\-/])                                      # メールアドレスや既存URLの一部は除外
    (?:[a-z0-9](?:[a-z0-9\-]*[a-z0-9])?\.)+(?:{_TLDS})  # ドメイン名（github.com, doi.org など）
    /{_URL_CHARS}*                                      # スキームなしはパスがあるものに限定
    """,
    re.IGNORECASE | re.VERBOSE,
)

# 行末に来たときに「URLがまだ続いている」とみなす文字
_CONTINUE_CHARS = "/-_=?&#~%:+"
# 末尾から取り除く句読点・記号
_TRAILING_PUNCT = ".,;:!?'\"’”"
_BRACKET_PAIRS = {")": "(", "]": "[", "}": "{", ">": "<"}
# 次行の先頭トークンがURLの続きらしいか（拡張子で終わる・スラッシュを含むなど）
_FILE_EXT = re.compile(r"^[\w\-]+\.(?:csv|tsv|zip|gz|tar|json|jsonl|xml|html?|php|pdf|txt|md|xlsx?|py|ipynb|rdata|rds|sav|parquet)\b", re.IGNORECASE)
_URL_TOKEN = re.compile(rf"^{_URL_CHARS}+")


def clean_url(url: str) -> str:
    """URL末尾の句読点や対応の取れていない閉じ括弧を取り除く。"""
    # LaTeXで「~」が「∼」(U+223C) や「˜」(U+02DC) として出力されることがあるので戻す
    url = url.replace("∼", "~").replace("˜", "~")
    while url:
        last = url[-1]
        if last in _TRAILING_PUNCT:
            url = url[:-1]
        elif last in _BRACKET_PAIRS:
            # Wikipediaの「..._(statistics)」のように対応する開き括弧がURL内にあれば残す
            if url.count(_BRACKET_PAIRS[last]) >= url.count(last):
                break
            url = url[:-1]
        else:
            break
    return url


def _url_at_line_end(line: str) -> str | None:
    """行末で終わっているURLがあれば返す（なければ None）。"""
    stripped = line.rstrip()
    for m in URL_PATTERN.finditer(stripped):
        if m.end() == len(stripped):
            return m.group()
    # 「https://」だけが行末に残っているケース（スキームの直後で改行）
    m = re.search(r"(?:https?|ftp)://$", stripped, re.IGNORECASE)
    return m.group() if m else None


def _should_join(line: str, next_line: str) -> bool:
    """line の末尾のURLが next_line に続いていると判断できれば True。"""
    url = _url_at_line_end(line)
    if url is None:
        return False
    next_stripped = next_line.lstrip()
    token_match = _URL_TOKEN.match(next_stripped)
    if not token_match:
        return False
    token = token_match.group()

    # 次行が「/」で始まる → パスの続き
    if token.startswith("/"):
        return True
    # 行末が区切り文字 → 続きがあるのはほぼ確実（LaTeXの \url はここで改行することが多い）
    if url[-1] in _CONTINUE_CHARS:
        # ただし「…/」の次行が「Dataset」のような大文字始まりの英単語なら、新しい文の始まりとみなす
        if url[-1] == "/" and re.fullmatch(r"[A-Z][a-z]+", token):
            return False
        return True
    # 行末が「.」→ 文末のピリオドの可能性もあるので、次行がURLの続きらしい場合だけ結合
    if url[-1] == ".":
        return (
            "/" in token
            or bool(re.fullmatch(r"\d[\w.\-/()]{3,}", token))  # DOIの「…/sdata.」+「2017.171」のような分割
            or bool(_FILE_EXT.match(token))
            or bool(re.match(r"^(?:com|org|net|io|edu)\b", token))
        )
    # 行末が閉じ括弧やカンマなど → URLはそこで終わっているとみなす
    if not url[-1].isalnum():
        return False
    # 行末が英数字（単語の途中で切れた可能性）→ 次行トークンにパスや拡張子があるときだけ結合
    return "/" in token.rstrip("/.,;)") or bool(_FILE_EXT.match(token))


def join_broken_lines(text: str) -> str:
    """改行で途中が切れたURLを、可能な範囲で1行につなげる。"""
    lines = text.splitlines()
    result: list[str] = []
    i = 0
    while i < len(lines):
        current = lines[i]
        # 3行以上にまたがるURLもあるので繰り返し結合する
        while i + 1 < len(lines) and _should_join(current, lines[i + 1]):
            current = current.rstrip() + lines[i + 1].lstrip()
            i += 1
        result.append(current)
        i += 1
    return "\n".join(result)


def extract_urls_from_text(text: str) -> list[str]:
    """テキストからURLを抽出して出現順に返す（このリスト内では重複を除く）。"""
    joined = join_broken_lines(text)
    urls: list[str] = []
    for m in URL_PATTERN.finditer(joined):
        url = clean_url(m.group())
        # 「https://」だけのものや、ホスト名に「.」がない断片（「https://github. com」→「https://github」）は捨てる
        host = re.sub(r"^(?:https?|ftp)://", "", url, flags=re.IGNORECASE).split("/")[0]
        if "." not in host:
            continue
        if url not in urls:
            urls.append(url)
    return urls


def extract_link_annotations(page: fitz.Page) -> list[str]:
    """ページ内のハイパーリンク（リンク注釈）から外部URLを取り出す。"""
    urls = []
    for link in page.get_links():
        uri = link.get("uri")
        if link.get("kind") != fitz.LINK_URI or not uri:
            continue
        uri = clean_url(uri.strip())
        # mailto: などWeb以外のリンクは対象外
        if not re.match(r"(?:https?|ftp)://|www\.", uri, re.IGNORECASE):
            continue
        if uri not in urls:
            urls.append(uri)
    return urls


def normalize_url(url: str) -> str:
    """重複判定用のキー。スキーム・www・末尾スラッシュの違いを無視し、ホスト名は小文字にする。"""
    key = re.sub(r"^(?:https?|ftp)://", "", url, flags=re.IGNORECASE)
    key = re.sub(r"^www\.", "", key, flags=re.IGNORECASE)
    host, sep, rest = key.partition("/")
    return (host.lower() + sep + rest).rstrip("/")


def merge_url_records(page_results: list[tuple[int, list[str], list[str]]]) -> list[UrlRecord]:
    """ページごとの (ページ番号, 本文URL, 注釈URL) を統合し、重複を除いた一覧にする。

    - 同じURLは1件にまとめ、最初に出現したページ番号を残す
    - 本文ではスキームなし、注釈ではスキームあり、のような表記揺れは同一とみなし、
      スキーム付きの表記を優先して表示する
    - 本文で途中までしか取れなかったURLが同じページの注釈URLの前半と一致する場合は、
      改行で切れたものとみなして注釈側に統合する
    """
    records: dict[str, UrlRecord] = {}

    def add(page: int, url: str, source: str) -> None:
        key = normalize_url(url)
        rec = records.get(key)
        if rec is None:
            records[key] = UrlRecord(page=page, url=url, sources=[source])
            return
        if source not in rec.sources:
            rec.sources.append(source)
        if "://" not in rec.url and "://" in url:
            rec.url = url

    for page, text_urls, annot_urls in page_results:
        annot_keys = [normalize_url(u) for u in annot_urls]
        for url in text_urls:
            key = normalize_url(url)
            # 本文側が注釈URLの途中で切れている場合は注釈URLに置き換える
            # （「…/dropout-prediction」と「…/dropout-prediction/tree/main」のように
            #   区切り文字の位置で一致するだけの別URLは置き換えない）
            longer = [
                a for a, k in zip(annot_urls, annot_keys)
                if "/" in key and k != key and k.startswith(key) and k[len(key)] not in "/?#&."
            ]
            if len(longer) == 1:
                url = longer[0]
            add(page, url, SOURCE_TEXT)
        for url in annot_urls:
            add(page, url, SOURCE_ANNOTATION)

    # 拡張予定: ここでURLの種類分け（GitHub/Zenodo/OSF/Kaggle など）を付与する
    return sorted(records.values(), key=lambda r: r.page)  # 安定ソートなのでページ内の出現順は保たれる


def extract_urls_from_pdf(doc: fitz.Document) -> list[UrlRecord]:
    """PDF全体からURL一覧を作る（テキスト抽出 → URL抽出 → 統合）。"""
    page_texts = extract_page_texts(doc)
    page_results = []
    for index, (page, text) in enumerate(zip(doc, page_texts)):
        page_results.append((index + 1, extract_urls_from_text(text), extract_link_annotations(page)))
    return merge_url_records(page_results)


# ---------------------------------------------------------------------------
# 4. 出力
# ---------------------------------------------------------------------------

def print_records(records: list[UrlRecord]) -> None:
    """URL一覧を画面に表示する。"""
    if not records:
        print("URLは見つかりませんでした。")
        return
    print(f"{'page':>4}  {'source':<15}  url")
    print("-" * 80)
    for r in records:
        print(f"{r.page:>4}  {r.source:<15}  {r.url}")
    print("-" * 80)
    print(f"合計 {len(records)} 件")


def default_csv_path(pdf_path: str | Path) -> Path:
    """入力PDFと同じ場所に「<PDF名>_urls.csv」を作る。"""
    pdf_path = Path(pdf_path)
    return pdf_path.with_name(f"{pdf_path.stem}_urls.csv")


def records_to_csv(records: list[UrlRecord]) -> str:
    """URL一覧をCSV形式の文字列にする（列: page, url, source）。"""
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(["page", "url", "source"])
    for r in records:
        writer.writerow([r.page, r.url, r.source])
    return buf.getvalue()


def save_csv(records: list[UrlRecord], csv_path: str | Path) -> None:
    """URL一覧をCSVに保存する（Excelで文字化けしないよう BOM 付き UTF-8）。"""
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        f.write(records_to_csv(records))


# ---------------------------------------------------------------------------
# コマンドライン
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="論文PDFから本文中のURLを一覧にします。")
    parser.add_argument("pdf", help="入力PDFファイルのパス")
    parser.add_argument("-o", "--output", help="CSVの保存先（省略時は <PDF名>_urls.csv）")
    args = parser.parse_args(argv)

    try:
        doc = open_pdf(args.pdf)
    except PdfOpenError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    with doc:
        records = extract_urls_from_pdf(doc)

    print_records(records)
    csv_path = Path(args.output) if args.output else default_csv_path(args.pdf)
    save_csv(records, csv_path)
    print(f"CSVを保存しました: {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
