"""Webアプリの画面テスト（Streamlit の AppTest でブラウザなしに動かす）。

ネットワークを使う「論文を検索」は、collect_papers をダミーに差し替えて確認する。
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent


def test_password_gate():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
    at.secrets["APP_PASSWORD"] = "secret"
    at.run()
    assert not at.exception
    assert any("合言葉" in t.label for t in at.text_input)

    at.text_input[0].input("wrong")
    at.button[0].click().run()
    assert any("違います" in e.value for e in at.error)

    at.text_input[0].input("secret")
    at.button[0].click().run()
    assert not at.exception
    assert any("論文を集める" in t.value for t in at.title)


def test_no_password_when_not_configured():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert any("論文を集める" in t.value for t in at.title)


@pytest.fixture
def fake_search(monkeypatch):
    """APIを呼ばずに、決まった論文一覧を返すようにする。"""
    import collect_papers

    def fake(conferences, years, keyword="", progress=None):
        return [
            collect_papers.Paper("EDM", 2024, "Paper with PDF", ["A. Author"], "10.5281/zenodo.1",
                                 "https://zenodo.org/records/1", "https://example.org/a.pdf"),
            collect_papers.Paper("EDM", 2024, "Paper without PDF", ["B. Author"], "10.5281/zenodo.2",
                                 "https://zenodo.org/records/2", ""),
        ], []

    monkeypatch.setattr(collect_papers, "collect_papers", fake)


def test_extract_page_with_sample():
    at = AppTest.from_file(str(ROOT / "pages" / "extract.py"), default_timeout=60).run()
    assert not at.exception
    next(b for b in at.button if "サンプル" in b.label).click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["URL件数"] == "11"


def test_collect_page_limits_jstage_batch(monkeypatch):
    import collect_papers

    def fake(conferences, years, keyword="", progress=None):
        return [collect_papers.Paper("教育工学会論文誌", 2024, f"論文{i}", ["著者"], f"10.1/{i}",
                                     f"https://www.jstage.jst.go.jp/article/x/{i}/_article/-char/ja/",
                                     f"https://www.jstage.jst.go.jp/article/x/{i}/_pdf/-char/ja") for i in range(12)], []

    monkeypatch.setattr(collect_papers, "collect_papers", fake)
    at = AppTest.from_file(str(ROOT / "pages" / "collect.py"), default_timeout=60).run()
    at.multiselect[0].set_value(["教育工学会論文誌"]).run()
    next(b for b in at.button if "論文を検索" in b.label).click().run()
    assert not at.exception
    assert any("1回 10 本まで" in w.value for w in at.warning)
    assert any("10 本のPDFを取得します" in c.value for c in at.caption)
    assert any("Powered by J-STAGE" in c.value for c in at.caption)


def test_collect_page_search(fake_search):
    at = AppTest.from_file(str(ROOT / "pages" / "collect.py"), default_timeout=60).run()
    assert not at.exception
    search_button = next(b for b in at.button if "論文を検索" in b.label)
    search_button.click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["見つかった論文"] == "2"
    assert metrics["PDFを自動取得できる"] == "1"
