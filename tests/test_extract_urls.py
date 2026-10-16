"""extract_urls.py の URL抽出まわりのテスト。"""

import sys
from pathlib import Path

import pymupdf as fitz
import pytest

# リポジトリ直下の extract_urls.py を読み込めるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract_urls import (  # noqa: E402
    PdfOpenError,
    clean_url,
    extract_urls_from_pdf,
    extract_urls_from_text,
    merge_url_records,
    open_pdf,
    open_pdf_bytes,
)


# --- 基本 -------------------------------------------------------------------

def test_http_and_https():
    text = "See http://example.com/a and https://example.org/b for details"
    assert extract_urls_from_text(text) == ["http://example.com/a", "https://example.org/b"]


def test_duplicates_in_text_are_removed():
    text = "https://osf.io/abcde https://osf.io/abcde"
    assert extract_urls_from_text(text) == ["https://osf.io/abcde"]


def test_fragment_without_domain_is_dropped():
    # 空白で分断されたURLの断片「https://github」は出力しない
    assert extract_urls_from_text("see https:// and https://github. com/a/b") == []


def test_no_url():
    assert extract_urls_from_text("No links here, e.g. Fig. 1 and Table 2.") == []


# --- スキームなしURL ----------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        ("code is at github.com/lak-lab/dropout-model.", ["github.com/lak-lab/dropout-model"]),
        ("doi.org/10.1145/3576050.3576100", ["doi.org/10.1145/3576050.3576100"]),
        ("visit www.kaggle.com/datasets/foo", ["www.kaggle.com/datasets/foo"]),
        ("data: zenodo.org/records/1234567, osf.io/x7y8z", ["zenodo.org/records/1234567", "osf.io/x7y8z"]),
    ],
)
def test_schemeless_urls(text, expected):
    assert extract_urls_from_text(text) == expected


def test_schemeless_excludes_email_and_files():
    # メールアドレスのドメインや「train.csv/test.csv」はURLとみなさない
    text = "Contact taro@univ.edu or see train.csv/test.csv splits."
    assert extract_urls_from_text(text) == []


# --- 末尾の句読点・括弧 --------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [
        ("https://github.com/a/b.", "https://github.com/a/b"),
        ("https://github.com/a/b,", "https://github.com/a/b"),
        ("https://github.com/a/b;", "https://github.com/a/b"),
        ("https://github.com/a/b).", "https://github.com/a/b"),
        ("https://github.com/a/b]", "https://github.com/a/b"),
        ("https://en.wikipedia.org/wiki/Mean_(statistics)", "https://en.wikipedia.org/wiki/Mean_(statistics)"),
        ("https://en.wikipedia.org/wiki/Mean_(statistics)).", "https://en.wikipedia.org/wiki/Mean_(statistics)"),
        # LaTeXのチルダ「∼」を「~」に戻す
        ("https://www.cs.example.edu/∼yamada/", "https://www.cs.example.edu/~yamada/"),
    ],
)
def test_clean_url(raw, expected):
    assert clean_url(raw) == expected


def test_trailing_punct_in_sentence():
    text = "The dataset (https://datashop.memphis.edu/Project?id=1) is public; see also [https://pslcdatashop.web.cmu.edu]."
    assert extract_urls_from_text(text) == [
        "https://datashop.memphis.edu/Project?id=1",
        "https://pslcdatashop.web.cmu.edu",
    ]


# --- 改行で切れたURL -----------------------------------------------------------

@pytest.mark.parametrize(
    "text, expected",
    [
        # スラッシュの直後で改行
        ("available at https://github.com/\nlak-lab/dropout-model and more", ["https://github.com/lak-lab/dropout-model"]),
        # 次の行がスラッシュで始まる
        ("available at https://github.com/lak-lab\n/dropout-model and more", ["https://github.com/lak-lab/dropout-model"]),
        # ハイフンの直後で改行
        ("https://osf.io/learning-\nanalytics-data/ is used", ["https://osf.io/learning-analytics-data/"]),
        # スキームの直後で改行
        ("at https://\nzenodo.org/records/42.", ["https://zenodo.org/records/42"]),
        # 3行にまたがる
        ("https://github.com/\nlak-lab/\ndropout-model.", ["https://github.com/lak-lab/dropout-model"]),
        # 英数字の途中で切れても、次行にパスがあれば結合
        ("https://github.com/lak-lab/drop\nout-model/blob/main/data.csv here", ["https://github.com/lak-lab/dropout-model/blob/main/data.csv"]),
        # スキームなしURLの途中で改行
        ("doi.org/10.1145/\n3576050.3576100", ["doi.org/10.1145/3576050.3576100"]),
        # クエリ文字列の途中で改行
        ("https://example.org/data?id=12&\nformat=csv", ["https://example.org/data?id=12&format=csv"]),
        # 参考文献のDOIが「.」の直後で改行
        ("https://doi.org/10.1038/sdata.\n2017.171", ["https://doi.org/10.1038/sdata.2017.171"]),
    ],
)
def test_broken_urls_are_joined(text, expected):
    assert extract_urls_from_text(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        # 文末のピリオドの後の次文はつなげない
        ("Data is at https://osf.io/abcde.\nThe students were", ["https://osf.io/abcde"]),
        # URLのあとに普通の単語が続く行はつなげない
        ("Data is at https://osf.io/abcde\nwhich contains logs", ["https://osf.io/abcde"]),
        # 閉じ括弧で終わっている
        ("(https://osf.io/abcde)\nsee/also", ["https://osf.io/abcde"]),
        # 「/」で終わった行の次が大文字始まりの文
        ("page: https://www.cs.example.edu/~yamada/\nDataset on Kaggle", ["https://www.cs.example.edu/~yamada/"]),
        # 「.」の次行が節番号
        ("at https://osf.io/abcde.\n2.1 Data", ["https://osf.io/abcde"]),
    ],
)
def test_lines_not_joined_when_url_ended(text, expected):
    assert extract_urls_from_text(text) == expected


def test_dot_at_line_end_joined_only_when_next_looks_like_path():
    # 「.」で終わる行は文末と区別がつかないため、次行がパスらしい場合だけ結合する
    assert extract_urls_from_text("see https://pslcdatashop.\nweb.cmu.edu/Project?id=5") == [
        "https://pslcdatashop.web.cmu.edu/Project?id=5"
    ]


# --- 本文とリンク注釈の統合 ------------------------------------------------------

def test_merge_dedup_keeps_first_page_and_prefers_scheme():
    records = merge_url_records([
        (1, ["github.com/a/b"], []),
        (3, ["https://github.com/a/b"], ["https://github.com/a/b/"]),
    ])
    assert len(records) == 1
    assert records[0].page == 1
    assert records[0].url == "https://github.com/a/b"
    assert records[0].source == "text+annotation"


def test_merge_truncated_text_url_replaced_by_annotation():
    records = merge_url_records([(2, ["https://github.com/lak-lab/drop"], ["https://github.com/lak-lab/dropout-model"])])
    assert [(r.page, r.url, r.source) for r in records] == [
        (2, "https://github.com/lak-lab/dropout-model", "text+annotation")
    ]


def test_merge_does_not_replace_parent_path_with_child_annotation():
    # リポジトリのURLと、そのサブフォルダへのリンクは別物として残す
    records = merge_url_records([(1, ["https://github.com/a/b"], ["https://github.com/a/b/tree/main/scripts"])])
    assert [r.url for r in records] == ["https://github.com/a/b", "https://github.com/a/b/tree/main/scripts"]


# --- PDFを使った結合テスト -------------------------------------------------------

def _make_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Code: https://github.com/")
    page.insert_text((72, 86), "lak-lab/dropout-model.")
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 100, 200, 112), "uri": "https://zenodo.org/records/99"})
    page.insert_text((72, 110), "[dataset]")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Again github.com/lak-lab/dropout-model")
    doc.save(path)


def test_extract_from_pdf(tmp_path):
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    with open_pdf(pdf) as doc:
        records = extract_urls_from_pdf(doc)
    assert [(r.page, r.url, r.source) for r in records] == [
        (1, "https://github.com/lak-lab/dropout-model", "text"),
        (1, "https://zenodo.org/records/99", "annotation"),
    ]


def test_open_pdf_bytes(tmp_path):
    # Webアプリのアップロードと同じく、バイト列から開ける
    pdf = tmp_path / "paper.pdf"
    _make_pdf(pdf)
    with open_pdf_bytes(pdf.read_bytes(), "paper.pdf") as doc:
        assert len(extract_urls_from_pdf(doc)) == 2
    with pytest.raises(PdfOpenError):
        open_pdf_bytes(b"this is not a pdf", "fake.pdf")
    with pytest.raises(PdfOpenError, match="空"):
        open_pdf_bytes(b"", "empty.pdf")


def test_open_pdf_errors(tmp_path):
    with pytest.raises(PdfOpenError, match="見つかりません"):
        open_pdf(tmp_path / "missing.pdf")
    txt = tmp_path / "note.txt"
    txt.write_text("hello")
    with pytest.raises(PdfOpenError, match=".pdf ではありません"):
        open_pdf(txt)
    fake = tmp_path / "fake.pdf"
    fake.write_text("this is not a pdf")
    with pytest.raises(PdfOpenError):
        open_pdf(fake)
