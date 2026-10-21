"""collect_papers.py のテスト（ネットワークは使わず、APIの応答をダミーにする）。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import collect_papers as cp  # noqa: E402


class FakeResponse:
    def __init__(self, data=None, status=200, content=b""):
        self._data, self.status_code, self._content = data, status, content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise cp.requests.HTTPError(f"{self.status_code}")

    def json(self):
        return self._data

    def iter_content(self, size):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeSession:
    """URLの一部に応じて決まった応答を返すダミーのセッション。"""

    def __init__(self, routes):
        self.routes, self.headers = routes, {}

    def get(self, url, params=None, timeout=None, stream=False):
        for key, resp in self.routes.items():
            if key in url:
                return resp
        raise AssertionError(f"想定外のURL: {url}")


def _crossref(items):
    return FakeResponse({"message": {"items": items}})


def test_clean_title():
    assert cp.clean_title("Learning &amp;amp; <i>Knowledge</i>\n  Tracing") == "Learning & Knowledge Tracing"


def test_lak_keeps_only_conference_papers():
    session = FakeSession({"crossref": _crossref([
        {"DOI": "10.1145/1.1", "title": ["Paper A"], "author": [{"given": "Taro", "family": "Yamada"}],
         "container-title": ["Proceedings of the 14th Learning Analytics and Knowledge Conference"]},
        {"DOI": "10.1145/1.2", "title": ["Journal paper"], "container-title": ["Journal of Learning Analytics and Knowledge"]},
        {"DOI": "10.1145/1.3", "title": ["Front matter"],
         "container-title": ["Proceedings of the 14th Learning Analytics and Knowledge Conference"]},
    ])})
    papers = cp.fetch_lak(session, 2024)
    assert [(p.title, p.doi, p.authors, p.landing_url) for p in papers] == [
        ("Paper A", "10.1145/1.1", ["Taro Yamada"], "https://doi.org/10.1145/1.1")
    ]
    assert papers[0].pdf_status == cp.PDF_MANUAL


def test_aied_excludes_same_named_textbook():
    session = FakeSession({"crossref": _crossref([
        {"DOI": "10.1007/a", "title": ["Conference paper"],
         "container-title": ["Lecture Notes in Computer Science", "Artificial Intelligence in Education"]},
        {"DOI": "10.1007/b", "title": ["Machine Learning in Education"], "container-title": ["Artificial Intelligence in Education"]},
    ])})
    assert [p.title for p in cp.fetch_aied(session, 2024)] == ["Conference paper"]


def test_edm_reads_zenodo_and_skips_proceedings_book():
    hit = lambda title, key: {  # noqa: E731
        "doi": "10.5281/zenodo.1", "metadata": {"title": title, "creators": [{"name": "Suzuki, Hanako"}]},
        "links": {"self_html": "https://zenodo.org/records/1"},
        "files": [{"key": key, "links": {"self": f"https://zenodo.org/files/{key}"}}],
    }
    session = FakeSession({"zenodo": FakeResponse({"hits": {"hits": [
        hit("Proceedings of EDM2024", "book.pdf"), hit("A Paper", "2024.EDM-long.1.pdf")]}})})
    papers = cp.fetch_edm(session, 2024)
    assert [(p.title, p.pdf_url, p.pdf_status) for p in papers] == [
        ("A Paper", "https://zenodo.org/files/2024.EDM-long.1.pdf", cp.PDF_AUTO)
    ]


def test_collect_dedup_keyword_and_out_of_range(monkeypatch):
    fake = [cp.Paper("EDM", 2024, "Dropout prediction", doi="10.1/x"),
            cp.Paper("EDM", 2024, "Dropout prediction", doi="10.1/y"),  # 同じタイトルの別バージョン
            cp.Paper("EDM", 2024, "Knowledge tracing", doi="10.1/z")]
    monkeypatch.setitem(cp._FETCHERS, "EDM", lambda s, y: list(fake))
    monkeypatch.setattr(cp, "add_open_access_pdfs", lambda s, p: None)
    papers, notes = cp.collect_papers(["EDM"], [2020, 2024], keyword="dropout")
    assert [p.doi for p in papers] == ["10.1/x"]
    assert any("2020" in n and "範囲外" in n for n in notes)


def test_download_pdf_rejects_html_and_forbidden():
    ok = FakeSession({"ok": FakeResponse(content=b"%PDF-1.7 ...")})
    assert cp.download_pdf("https://ok/a.pdf", ok).startswith(b"%PDF")
    html = FakeSession({"html": FakeResponse(content=b"<!DOCTYPE html>")})
    with pytest.raises(cp.PdfDownloadError, match="PDFではない"):
        cp.download_pdf("https://html/a.pdf", html)
    forbidden = FakeSession({"acm": FakeResponse(status=403)})
    with pytest.raises(cp.PdfDownloadError, match="拒否"):
        cp.download_pdf("https://acm/a.pdf", forbidden)
