"""research/ のテスト（ネットワークを使わず、APIの応答はダミーにする）。

先生のデータセットの本物は使わない。テスト用の小さな表を一時フォルダに作って確かめる。
"""

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collect_papers import PdfDownloadError  # noqa: E402
from research import fulltext, semantic_scholar  # noqa: E402
from research.teacher_dataset import describe_file, load_column_map, load_papers, normalize_doi  # noqa: E402


# --- Semantic Scholar --------------------------------------------------------------

class FakeResponse:
    def __init__(self, status, data=None, headers=None):
        self.status_code, self._data, self.headers, self.text = status, data, headers or {}, json.dumps(data)

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls, self.headers = list(responses), [], {}

    def request(self, method, url, timeout=None, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def _client(tmp_path, responses, api_key="test-key"):
    session = FakeSession(responses)
    sleeps = []
    client = semantic_scholar.SemanticScholarClient(api_key=api_key, cache_dir=tmp_path, session=session,
                                                    sleep=sleeps.append)
    return client, session, sleeps


def test_batch_uses_key_and_caches(tmp_path):
    paper = {"paperId": "abc", "title": "A paper", "openAccessPdf": {"url": "https://x.org/a.pdf"}}
    client, session, _ = _client(tmp_path, [FakeResponse(200, [paper, None])])
    result = client.get_papers(["DOI:10.1/a", "DOI:10.1/none"])
    assert result == {"DOI:10.1/a": paper, "DOI:10.1/none": None}
    assert session.headers["x-api-key"] == "test-key"
    method, url, kwargs = session.calls[0]
    assert (method, url.endswith("/paper/batch")) == ("POST", True)
    assert kwargs["json"] == {"ids": ["DOI:10.1/a", "DOI:10.1/none"]}
    # 2回目はキャッシュから返し、APIには送らない
    assert client.get_papers(["DOI:10.1/a", "DOI:10.1/none"]) == result
    assert len(session.calls) == 1


def test_batch_splits_into_500(tmp_path):
    ids = [f"DOI:10.1/{i}" for i in range(501)]
    client, session, _ = _client(tmp_path, [FakeResponse(200, [None] * 500), FakeResponse(200, [None])])
    client.get_papers(ids)
    assert [len(c[2]["json"]["ids"]) for c in session.calls] == [500, 1]


def test_retries_after_429(tmp_path):
    client, session, sleeps = _client(tmp_path, [FakeResponse(429), FakeResponse(429, headers={"Retry-After": "3"}),
                                                 FakeResponse(200, [{"paperId": "x"}])])
    assert client.get_papers(["DOI:10.1/x"])["DOI:10.1/x"] == {"paperId": "x"}
    assert len(session.calls) == 3
    assert 3 in sleeps  # Retry-After に従って待った


def test_gives_up_after_retries(tmp_path):
    client, _, _ = _client(tmp_path, [FakeResponse(429)] * 3)
    client.max_retries = 2
    with pytest.raises(semantic_scholar.SemanticScholarError):
        client.get_papers(["DOI:10.1/x"])


def test_waits_between_requests(tmp_path):
    client, _, sleeps = _client(tmp_path, [FakeResponse(200, [None]), FakeResponse(200, [None])])
    client.get_papers(["DOI:10.1/a"])
    client.get_papers(["DOI:10.1/b"])
    assert any(s > 1.0 for s in sleeps)  # 2回目の前に1秒以上待った


def test_match_title_found_and_not_found(tmp_path):
    hit = {"paperId": "p1", "title": "Title", "matchScore": 0.97}
    client, session, _ = _client(tmp_path, [FakeResponse(200, {"data": [hit]}), FakeResponse(404, {"error": "x"})])
    assert client.match_title("Title") == hit
    assert client.match_title("Nonsense title") is None
    assert client.match_title("  title ") == hit  # 空白・大文字小文字の違いはキャッシュで同じとみなす
    assert len(session.calls) == 2


# --- 先生のデータセットの読み込み ----------------------------------------------------

def _make_sheet(tmp_path) -> Path:
    # 実際のシートのように、1行目にグループ名、2行目に列名、3行目に説明、4行目からデータ
    rows = [
        ["Basic information", "", "", "", ""],
        ["Venue name", "Year", "Paper title", "Paper URL (or DOI link if it exists)", "Data set name(s)"],
        ["[category]", "[int]", "[string]", "[hyperlink]", "[string]"],
        ["LAK", "2020", "A  sample paper", "https://dl.acm.org/doi/10.1145/0000000.0000001", "ExampleSet"],
        ["EDM", "2021", "Second paper", "", "X"],
        ["", "", "", "", ""],
    ]
    path = tmp_path / "teacher.xlsx"
    pd.DataFrame(rows).to_excel(path, sheet_name="Selected papers", header=False, index=False)
    return path


def _make_map(tmp_path) -> Path:
    path = tmp_path / "map.json"
    path.write_text(json.dumps({"sheets": [{
        "sheet": "Selected papers", "role": "selected", "header_row": 2, "data_start_row": 4,
        "columns": {"venue": "Venue name", "year": "Year", "title": "Paper title",
                    "paper_url": "Paper URL (or DOI link if it exists)", "dataset_name": "Data set name(s)"}}]}),
        encoding="utf-8")
    return path


def test_load_papers_with_column_map(tmp_path):
    papers = load_papers(_make_sheet(tmp_path), load_column_map(_make_map(tmp_path)))
    assert len(papers) == 2  # 空行は飛ばす
    p = papers[0]
    assert (p.row_id, p.role, p.venue, p.year, p.title) == ("Selected papers:4", "selected", "LAK", 2020, "A sample paper")
    assert p.doi == "10.1145/0000000.0000001"
    assert p.s2_id == "DOI:10.1145/0000000.0000001"
    assert p.extra == {"dataset_name": "ExampleSet"}
    assert papers[1].s2_id == ""  # DOIがなければタイトルで探す


def test_column_map_rejects_unknown_items(tmp_path):
    path = tmp_path / "map.json"
    path.write_text(json.dumps({"sheets": [{"sheet": "S", "header_row": 1, "data_start_row": 2,
                                            "columns": {"titel": "Paper title"}}]}), encoding="utf-8")
    with pytest.raises(ValueError, match="項目名"):
        load_column_map(path)


def test_describe_file_shows_first_rows(tmp_path):
    text = describe_file(_make_sheet(tmp_path), rows=3)
    assert "シート「Selected papers」" in text and "Paper title" in text


@pytest.mark.parametrize("value, expected", [
    ("https://doi.org/10.1145/0000000.0000001", "10.1145/0000000.0000001"),
    ("https://dl.acm.org/doi/abs/10.1145/0000000.0000001.", "10.1145/0000000.0000001"),
    ("10.5281/ZENODO.123", "10.5281/zenodo.123"),
    ("https://example.org/paper", ""),
])
def test_normalize_doi(value, expected):
    assert normalize_doi(value) == expected


# --- 本文の取得 -------------------------------------------------------------------

def _pdf_bytes() -> bytes:
    import pymupdf
    doc = pymupdf.open()
    for i in range(2):
        doc.new_page().insert_text((72, 72), f"Page {i + 1}. " + "Learning analytics data is available. " * 5)
    return doc.tobytes()


def test_fulltext_from_open_access_pdf_and_cache(tmp_path):
    calls = []

    def download(url):
        calls.append(url)
        return _pdf_bytes()

    paper = {"paperId": "p", "openAccessPdf": {"url": "https://x.org/a.pdf"}, "textAvailability": "fulltext"}
    r = fulltext.get_fulltext(paper, cache_dir=tmp_path, download=download, wait=lambda s: None)
    assert (r.source, r.pages, r.s2orc_available) == ("PDF", 2, True)
    assert "Page 2" in r.page_texts[1]
    # 2回目はキャッシュから読み、ダウンロードしない
    r2 = fulltext.get_fulltext(paper, cache_dir=tmp_path, download=download, wait=lambda s: None)
    assert r2.text == r.text and len(calls) == 1


@pytest.mark.parametrize("paper, reason", [
    (None, "見つからない"),
    ({"paperId": "p", "openAccessPdf": None}, "オープンアクセスのPDFがない"),
    ({"paperId": "p", "openAccessPdf": {"url": ""}, "textAvailability": "fulltext"}, "S2ORCには本文あり"),
])
def test_fulltext_none_reasons(tmp_path, paper, reason):
    r = fulltext.get_fulltext(paper, cache_dir=tmp_path, download=lambda u: b"", wait=lambda s: None)
    assert r.source == "なし" and reason in r.reason


def test_fulltext_download_error(tmp_path):
    def download(url):
        raise PdfDownloadError("サイトにアクセスを拒否されました")

    paper = {"paperId": "p", "openAccessPdf": {"url": "https://publisher.example/pdf/10.1/x"}}
    r = fulltext.get_fulltext(paper, cache_dir=tmp_path, download=download, wait=lambda s: None)
    assert r.source == "なし" and "拒否" in r.reason


def test_fulltext_skips_blocked_site_and_falls_back(tmp_path):
    calls = []

    def download(url):
        calls.append(url)
        if "landing" in url:
            raise PdfDownloadError("PDFではないページが返されました")
        return _pdf_bytes()

    paper = {"paperId": "p", "openAccessPdf": {"url": "https://dl.acm.org/doi/pdf/10.1/x"}}
    extra = [("OpenAlex", "https://repo.example/landing/1"), ("先生のシート", "https://educationaldatamining.org/p.pdf")]
    r = fulltext.get_fulltext(paper, extra, cache_dir=tmp_path, download=download, wait=lambda s: None)
    assert (r.source, r.pdf_from) == ("PDF", "先生のシート")
    # ACM には問い合わせず、OpenAlex（失敗）→ 先生のシートの順に試した
    assert calls == ["https://repo.example/landing/1", "https://educationaldatamining.org/p.pdf"]


def test_fulltext_tries_extra_urls_even_if_s2_missing(tmp_path):
    r = fulltext.get_fulltext(None, [("先生のシート", "https://educationaldatamining.org/p.pdf")],
                              cache_dir=tmp_path, download=lambda u: _pdf_bytes(), wait=lambda s: None)
    assert (r.source, r.pdf_from) == ("PDF", "先生のシート")


def test_candidate_order_and_arxiv():
    paper = {"openAccessPdf": {"url": "https://a.org/1.pdf"}, "externalIds": {"ArXiv": "2206.08288"}}
    cands = fulltext.candidate_pdf_urls(paper, [("OpenAlex", "https://a.org/1.pdf"), ("OpenAlex", "https://b.org/2.pdf")])
    assert cands == [("Semantic Scholar", "https://a.org/1.pdf"), ("arXiv", "https://arxiv.org/pdf/2206.08288"),
                     ("OpenAlex", "https://b.org/2.pdf")]  # 同じURLは1回だけ


@pytest.mark.parametrize("url, expected", [
    ("https://educationaldatamining.org/files/conferences/EDM2099/papers/paper_1.pdf", True),
    ("https://educationaldatamining.org/EDM2099/proceedings/sample-paper/", True),
    ("https://link.springer.com/chapter/10.1007/000-0-000-00000-0_1", False),
    ("https://dl.acm.org/doi/10.1145/0000000.0000002", False),
])
def test_teacher_pdf_url(url, expected):
    from scripts.build_papers_status import teacher_pdf_url
    assert bool(teacher_pdf_url(url)) is expected
