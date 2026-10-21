"""Webアプリの画面テスト（Streamlit の AppTest でブラウザなしに動かす）。

ネットワークを使う「論文を検索」は、collect_papers をダミーに差し替えて確認する。
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parent.parent
TIMEOUT = 60


def _app() -> AppTest:
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=TIMEOUT)


def _page(name: str) -> AppTest:
    return AppTest.from_file(str(ROOT / "views" / name), default_timeout=TIMEOUT)


def _paper(i: int, conference: str = "EDM", pdf: bool = True) -> dict:
    import collect_papers

    return collect_papers.Paper(conference, 2024, f"Paper {i}", ["A. Author"], f"10.1/{i}",
                                f"https://example.org/{i}", f"https://example.org/{i}.pdf" if pdf else "").to_row()


def test_password_gate():
    at = _app()
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
    assert any("論文を検索" in t.value for t in at.title)


def test_no_legacy_pages_folder():
    # pages/ フォルダがあると Streamlit が各ページを自動で登録し、/extract などのURLを直接開くと
    # app.py（合言葉の確認）を通らずにページが動いてしまう。ページは views/ に置くこと
    assert not (ROOT / "pages").exists()


def test_no_password_when_not_configured():
    at = _app().run()
    assert not at.exception
    assert any("論文を検索" in t.value for t in at.title)


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


def test_step1_search_moves_to_step2(fake_search):
    at = _app().run()
    assert not at.exception
    # 国際会議・国内の両方とも、同じボタン形式（pills）で選ぶ
    assert len(at.button_group) == 2
    next(b for b in at.button if "検索して次へ" in b.label).click().run()
    assert not at.exception
    assert any("論文を選ぶ" in t.value for t in at.title)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["見つかった論文"] == "2"
    assert metrics["PDFを自動取得できる"] == "1"
    # PDFを自動取得できる論文には、最初からチェックが入っている
    assert at.session_state["selected"] == {0}


def test_step2_without_search_shows_guide():
    at = _page("step2_select.py").run()
    assert not at.exception
    assert any("まだ論文を検索していません" in i.value for i in at.info)


def test_step2_keeps_selection():
    at = _page("step2_select.py")
    at.session_state["papers"] = [_paper(0), _paper(1), _paper(2, pdf=False)]
    at.session_state["selected"] = {1}
    at.run()
    assert not at.exception
    assert any("1 本を選択中" in c.value for c in at.caption)


def test_step3_limits_jstage_batch():
    at = _page("step3_extract.py")
    at.session_state["papers"] = [_paper(i, conference="JSET論文誌") for i in range(12)]
    at.session_state["selected"] = set(range(12))
    at.run()
    assert not at.exception
    assert any("10 本のPDFを取得します" in s.value for s in at.subheader)
    assert any("1回 10 本まで" in w.value for w in at.warning)


def test_step3_shows_results():
    at = _page("step3_extract.py")
    at.session_state["papers"] = [_paper(0)]
    at.session_state["selected"] = {0}
    at.session_state["batch"] = {
        "results": [{"conference": "EDM", "year": 2024, "title": "Paper 0", "status": "✅ 成功", "urls": 1,
                     "error": "", "landing_url": "https://example.org/0"}],
        "urls": [{"conference": "EDM", "year": 2024, "title": "Paper 0", "doi": "10.1/0", "page": 1,
                  "url": "https://github.com/a/b", "source": "text", "link": "https://github.com/a/b"}],
    }
    at.run()
    assert not at.exception
    assert any("URLを 1 件" in s.value for s in at.success)


def test_extract_page_with_sample():
    at = _page("extract.py").run()
    assert not at.exception
    next(b for b in at.button if "サンプル" in b.label).click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["URL件数"] == "11"
