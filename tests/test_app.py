"""Webアプリの画面テスト（Streamlit の AppTest でブラウザなしに動かす）。

ネットワークを使う「論文を検索」は collect_papers を、AIの判定は Gemini をダミーに差し替えて確認する。
"""

import json
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


def _texts(at: AppTest) -> str:
    """画面に出ている文章（見出し・本文・HTML）をまとめて返す。"""
    parts = [m.value for m in at.markdown] + [t.value for t in at.title] + [s.value for s in at.subheader]
    parts += [str(getattr(h, "proto", "")) for h in at.get("html")]
    return "\n".join(parts)


# --- 合言葉・ホーム ----------------------------------------------------------------

def test_password_gate():
    at = _app()
    at.secrets["APP_PASSWORD"] = "secret"
    at.run()
    assert not at.exception
    # 何のアプリか・合言葉が必要なことが、はっきり書かれている
    assert "Paper Data Finder" in _texts(at)
    assert "合言葉を入力してください" in _texts(at)
    assert any("合言葉" in t.label for t in at.text_input)

    at.text_input[0].input("wrong")
    at.button[0].click().run()
    assert any("違います" in e.value for e in at.error)

    at.text_input[0].input("secret")
    at.button[0].click().run()
    assert not at.exception
    # 入るとホームが開く
    assert "論文を検索して調べる" in _texts(at)


def test_no_legacy_pages_folder():
    # pages/ フォルダがあると Streamlit が各ページを自動で登録し、/extract などのURLを直接開くと
    # app.py（合言葉の確認）を通らずにページが動いてしまう。ページは views/ に置くこと
    assert not (ROOT / "pages").exists()


def test_no_password_when_not_configured():
    at = _app().run()
    assert not at.exception
    # ホームに3つの入口がある
    labels = [b.label for b in at.button]
    assert {"論文を検索する", "PDFをアップロードする", "使い方を見る"} <= set(labels)


def test_guide_page():
    at = _app().run()
    at.button(key="home_guide").click().run()
    assert not at.exception
    assert any("使い方" in t.value for t in at.title)


# --- STEP 1〜3 ----------------------------------------------------------------------

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
    at.button(key="home_search").click().run()
    assert not at.exception
    # 国際会議・国内の両方とも、同じボタン形式（pills）で選ぶ
    assert len(at.button_group) == 2
    next(b for b in at.button if b.label == "検索して次へ").click().run()
    assert not at.exception
    assert any("論文を選ぶ" in t.value for t in at.title)
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["見つかった論文"] == "2"
    assert metrics["PDFを自動取得できる"] == "1"
    # 最初はどの論文も選ばれていない（PDFを取得する論文は自分で選ぶ）
    assert at.session_state["selected"] == set()
    assert next(b for b in at.button if b.label.startswith("次へ")).disabled

    # STEP 1 に戻ると、検索の履歴から前の結果を開き直せる
    at.switch_page("views/step1_search.py").run()
    assert not at.exception
    assert any("検索の履歴" in s.value for s in at.subheader)
    at.button(key="history_0").click().run()
    assert any("論文を選ぶ" in t.value for t in at.title)


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


def test_step2_select_all_and_none():
    at = _page("step2_select.py")
    at.session_state["papers"] = [_paper(0), _paper(1), _paper(2, pdf=False)]
    at.session_state["selected"] = set()
    at.run()
    assert not at.exception
    # 「すべて選ぶ」は、PDFを自動取得できる論文だけを選ぶ
    next(b for b in at.button if b.label == "すべて選ぶ").click().run()
    assert at.session_state["selected"] == {0, 1}
    assert not next(b for b in at.button if b.label.startswith("次へ")).disabled
    next(b for b in at.button if b.label == "すべて外す").click().run()
    assert at.session_state["selected"] == set()


def test_limited_selection():
    from ui_common import MAX_BATCH, limited_selection

    rows = [_paper(i) for i in range(35)]
    assert limited_selection(rows, range(35)) == set(range(MAX_BATCH))
    rows = [_paper(i, conference="JSET論文誌") for i in range(12)] + [_paper(12, pdf=False)]
    # J-STAGE は1回10本まで。PDFを自動取得できない論文は選ばない
    assert limited_selection(rows, range(13)) == set(range(10))


def test_step3_limits_jstage_batch():
    at = _page("step3_extract.py")
    at.session_state["papers"] = [_paper(i, conference="JSET論文誌") for i in range(12)]
    at.session_state["selected"] = set(range(12))
    at.run()
    assert not at.exception
    assert any("10 本のPDFを取得します" in s.value for s in at.subheader)
    assert any("1回 10 本まで" in w.value for w in at.warning)


# --- AIで判定（ダミーのAIを使う） ------------------------------------------------------

ENGLISH_TEXT = ("We release the data collected in this study. "
                "The data are openly available at https://osf.io/abcde for other researchers. ") * 4
JAPANESE_TEXT = "本研究では，大学の授業で収集した学習ログを分析した。データは公開していない。" * 10


class _FakeProvider:
    """Gemini の代わりに、決まった答えを返す（ネットワークを使わない）。"""

    name, model, temperature = "fake", "fake-model", 0.0

    def __init__(self):
        self.calls = 0

    def settings(self):
        return {"provider": self.name, "model": self.model, "temperature": self.temperature}

    def generate(self, system, user):
        from research.llm import LLMResponse

        self.calls += 1
        answer = {"paper": {"shares_dataset": "yes", "evidence": "The data are openly available."},
                  "datasets": [{"name": "Fake logs", "url": "https://osf.io/abcde", "availability": "P",
                                "evidence": "The data are openly available."}],
                  "urls": [{"id": "U1", "is_data_location": True, "reason": "OSF data page."}]}
        return LLMResponse(text=json.dumps(answer), input_tokens=10, output_tokens=5, seconds=0.0, model=self.model)


def _doc(title: str = "Paper 0", text: str = ENGLISH_TEXT) -> dict:
    from extract_urls import UrlRecord

    return {"conference": "EDM", "year": 2024, "title": title, "doi": "10.1/0", "pages": [text],
            "records": [UrlRecord(page=1, url="https://osf.io/abcde", sources=["text"])]}


def _batch_with_docs(docs=None):
    return {
        "results": [{"conference": "EDM", "year": 2024, "title": "Paper 0", "status": "成功", "urls": 1,
                     "error": "", "landing_url": "https://example.org/0"}],
        "urls": [{"conference": "EDM", "year": 2024, "title": "Paper 0", "doi": "10.1/0", "page": 1,
                  "url": "https://osf.io/abcde", "source": "text", "link": "https://osf.io/abcde"}],
        "docs": docs if docs is not None else [_doc()],
    }


@pytest.fixture
def fake_ai(monkeypatch, tmp_path):
    """APIキーがある状態にし、Gemini をダミーに差し替える。"""
    import ui_ai

    fake = _FakeProvider()
    monkeypatch.setattr(ui_ai, "gemini_api_key", lambda: "dummy")
    monkeypatch.setattr(ui_ai, "make_provider", lambda key: fake)
    monkeypatch.setattr(ui_ai, "CACHE_DIR", tmp_path)
    return fake


def _step(name: str, batch: dict) -> AppTest:
    at = _page(name)
    at.session_state["papers"] = [_paper(0)]
    at.session_state["selected"] = {0}
    at.session_state["batch"] = batch
    return at


def test_step3_shows_results_and_link_to_step4(fake_ai):
    at = _step("step3_extract.py", _batch_with_docs()).run()
    assert not at.exception
    assert any("URLを 1 件" in s.value for s in at.success)
    # STEP 4（AIで判定）へは、大きなボタンを押したときだけ移動する
    assert at.button(key="to_step4").label == "AIでデータセットを判定する →"
    assert "STEP 4" in _texts(at)


def test_step3_without_key_has_no_ai_button(monkeypatch):
    import ui_ai

    monkeypatch.setattr(ui_ai, "gemini_api_key", lambda: "")
    at = _step("step3_extract.py", _batch_with_docs()).run()
    assert not at.exception
    assert not any(b.label.startswith("AIで") for b in at.button)


def test_step4_without_key(monkeypatch):
    import ui_ai

    monkeypatch.setattr(ui_ai, "gemini_api_key", lambda: "")
    at = _step("step4_judge.py", _batch_with_docs()).run()
    assert not at.exception
    assert any("APIキーが設定されていません" in i.value for i in at.info)


def test_step4_without_docs():
    at = _page("step4_judge.py").run()
    assert not at.exception
    assert any("まだ論文の本文を取得していません" in i.value for i in at.info)


def test_step4_ai_judge(fake_ai):
    at = _step("step4_judge.py", _batch_with_docs()).run()
    assert not at.exception
    next(b for b in at.button if b.label == "選んだ 1 本をAIで判定する").click().run()
    assert not at.exception
    assert fake_ai.calls == 1
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["公開"] == "1"
    # 判定の後も、今日あと何本判定できるかを表示する
    assert "今日あと" in _texts(at)
    assert at.session_state["ai"]["datasets"][0]["name"] == "Fake logs"
    # 根拠の文が本文にあるかを確かめ、ページと一緒に表示する
    assert at.session_state["ai"]["papers"][0]["evidence_check"] == "本文の 1 ページにあり"
    assert at.session_state["ai"]["datasets"][0]["evidence_check"] == "本文の 1 ページにあり"
    assert at.session_state["ai"]["urls"][0]["url"] == "https://osf.io/abcde"

    # 結果を消して選び直すと、同じ論文は保存した答えを使い、AIを呼ばない
    next(b for b in at.button if b.label == "別の論文を選んで判定する").click().run()
    assert not at.exception
    next(b for b in at.button if b.label.startswith("選んだ")).click().run()
    assert fake_ai.calls == 1


def test_step4_resumes_pending(fake_ai):
    # 判定の途中で実行が打ち切られても、次の実行で「判定する論文」の続きから判定する
    import ui_ai

    batch = _batch_with_docs()
    at = _step("step4_judge.py", batch)
    at.session_state["ai_pending"] = {"sig": ui_ai.selection_key(batch["docs"], "ai"), "indices": [0]}
    at.run()
    assert not at.exception
    assert fake_ai.calls == 1
    assert at.session_state["ai"]["papers"][0]["kind"] == "公開"
    assert "ai_pending" not in at.session_state


def test_step4_selection_limit(fake_ai):
    import ui_ai

    docs = [_doc(title=f"Paper {i}") for i in range(12)]
    at = _step("step4_judge.py", _batch_with_docs(docs)).run()
    assert not at.exception
    # 最初は先頭の10本にチェックが入っている
    assert any(b.label == "選んだ 10 本をAIで判定する" for b in at.button)

    # 上限を超えて選ぶと、注意が出てボタンが押せなくなる
    at.session_state[ui_ai.selection_key(docs, "ai")] = set(range(11))
    at.run()
    assert any("10 本まで" in w.value for w in at.warning)
    assert next(b for b in at.button if b.label.startswith("選んだ")).disabled


def test_step4_excludes_japanese_papers(fake_ai):
    docs = [_doc(title="英語の論文"), _doc(title="日本語の論文", text=JAPANESE_TEXT)]
    at = _step("step4_judge.py", _batch_with_docs(docs)).run()
    assert not at.exception
    # 日本語の論文は対象外と知らせ、選べるのは英語の論文だけ
    assert any("1 本は、AIの判定の対象外" in i.value for i in at.info)
    assert any(b.label == "選んだ 1 本をAIで判定する" for b in at.button)


def test_ai_daily_limit(monkeypatch, tmp_path):
    import ui_ai

    monkeypatch.setattr(ui_ai, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(ui_ai, "DAILY_LIMIT", 0)
    ui_ai._daily_counter.clear()
    fake = _FakeProvider()
    result = ui_ai.judge_papers([_doc()], fake)
    ui_ai._daily_counter.clear()
    assert fake.calls == 0
    assert "1日の上限" in result["stopped"]


def test_remaining_html():
    import ui_ai

    assert "<b>12</b>" in ui_ai.remaining_html(12)
    # 上限に達したら、いつ戻るかを知らせる
    assert "17時" in ui_ai.remaining_html(0)


def test_paper_language():
    import ui_ai

    assert ui_ai.paper_language([ENGLISH_TEXT]) == ui_ai.LANG_EN
    assert ui_ai.paper_language([JAPANESE_TEXT]) == ui_ai.LANG_OTHER
    assert ui_ai.paper_language(["", "  "]) == ui_ai.LANG_NO_TEXT
    # 英語の論文に日本語の要旨が少しあっても英語とみなす
    assert ui_ai.paper_language([ENGLISH_TEXT * 5, "日本語の要旨。" * 5]) == ui_ai.LANG_EN


# --- 手元の論文 ------------------------------------------------------------------------

def test_extract_page_with_sample():
    at = _page("extract.py").run()
    assert not at.exception
    next(b for b in at.button if "サンプル" in b.label).click().run()
    assert not at.exception
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["URL件数"] == "11"


def test_extract_page_ai_needs_consent(fake_ai):
    at = _page("extract.py").run()
    next(b for b in at.button if "サンプル" in b.label).click().run()
    assert not at.exception
    run = next(b for b in at.button if b.label.startswith("選んだ"))
    # 「公開済みの論文です」にチェックするまで、判定のボタンは押せない
    assert run.disabled
    at.checkbox(key="ai_upload_consent").check().run()
    run = next(b for b in at.button if b.label.startswith("選んだ"))
    assert not run.disabled
    run.click().run()
    assert not at.exception
    assert fake_ai.calls >= 1
    assert "ai_upload" in at.session_state
