"""「AIで判定する（試験版）」の部品（STEP 4 のページと、手元の論文のページで使う）。

取得した論文の本文から、判断に必要な部分（URLの前後の文と、データについて書かれた文）だけを
Gemini API に送り、次の2段で判定させる（研究用のスクリプトと同じプロンプト・同じ仕組みを使う）。
  1段目：読者が手に入れられる教育データセットがあるか（あり／なし／不明）
  2段目：あれば、データセットごとの名前・URL・入手方法（公開／要ログイン／要申請）

  ・APIキーは Streamlit の Secrets（公開アプリ）か .env（手元のPC）の GEMINI_API_KEY から読む。キーがなければボタンを出さない
  ・送るのは公開されている論文の一部とURLだけ。先生のデータセットはアプリでは一切使わない
  ・無料枠の上限を守るため、1回に判定する本数と、アプリ全体で1日に判定する本数に上限を設ける
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

from research.judge import STATUS_OK, Judge, load_prompt
from research.llm import LLMError
from research.llm.base import DailyLimitReached
from research.llm_input import build_llm_input

PROMPT_VERSION = "judge_v3"  # 調整用の論文で一番成績がよかった版
MODEL = "gemini-3.5-flash-lite"  # 無料枠で1日500回まで使えるモデル
MAX_AI_PAPERS = 10  # 1回に判定する本数の上限
DAILY_LIMIT = 200  # アプリ全体（全員の合計）で1日に判定する本数の上限（無料枠の1日500回より少なくしておく）
# 判定の結果を一時的に保存する場所（同じ論文をもう一度判定するときはAIを呼ばない）
CACHE_DIR = Path(tempfile.gettempdir()) / "paper_data_finder_llm"

SHARES_LABELS = {"yes": "あり", "no": "なし", "unknown": "不明"}
AVAILABILITY_LABELS = {"P": "公開", "L": "要ログイン", "O": "要申請"}


def gemini_api_key() -> str:
    """Secrets → 環境変数（.env）の順に GEMINI_API_KEY を探す。なければ空文字。"""
    try:
        key = st.secrets.get("GEMINI_API_KEY", "")
    except Exception:  # secrets.toml がない（手元で動かすとき）
        key = ""
    if not key:
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(__file__).resolve().parent / ".env")
        except ImportError:
            pass
        key = os.environ.get("GEMINI_API_KEY", "")
    return key


# --- 1日の上限（アプリ全体で共有する数） ----------------------------------------------

def _today() -> str:
    # Gemini の1日の上限は米国太平洋時間の0時（日本時間の17時ごろ）に戻るので、それに合わせて数える
    return datetime.now(timezone(timedelta(hours=-8))).strftime("%Y-%m-%d")


@st.cache_resource
def _daily_counter() -> dict:
    """アプリを使う全員で共有するカウンター（サーバーが再起動すると0に戻る）。"""
    return {"date": _today(), "count": 0, "lock": threading.Lock()}


def remaining_today() -> int:
    c = _daily_counter()
    with c["lock"]:
        if c["date"] != _today():
            c["date"], c["count"] = _today(), 0
        return max(0, DAILY_LIMIT - c["count"])


def remaining_html(left: int) -> str:
    """「今日あと〇本」の表示（HTML）。"""
    css = "pdf-remaining pdf-empty" if left == 0 else "pdf-remaining"
    note = "今日の上限に達しました。日本時間17時ごろに戻ります" if left == 0 else "アプリを使う全員の合計"
    return f'<div class="{css}">AIの判定：今日あと <b>{left}</b> 本<small>（{note}）</small></div>'


@st.fragment(run_every=10)
def remaining_badge() -> None:
    """今日あと何本判定できるかを表示する。この部分だけ10秒ごとに数え直すので、ほかの人が使った分も反映される。"""
    st.html(remaining_html(remaining_today()))


def _use_one() -> bool:
    """1本分を数える。上限に達していれば False。"""
    c = _daily_counter()
    with c["lock"]:
        if c["date"] != _today():
            c["date"], c["count"] = _today(), 0
        if c["count"] >= DAILY_LIMIT:
            return False
        c["count"] += 1
        return True


# --- 判定 ---------------------------------------------------------------------------

def make_provider(api_key: str):
    from research.llm.gemini import GeminiProvider

    # アプリでは長く待たせないよう、再試行は少なめにする
    return GeminiProvider(MODEL, api_key=api_key, max_retries=2)


def judge_papers(docs: list[dict], provider, progress=None) -> dict:
    """論文を順に判定し、画面に出す表（論文ごと・データセットごと・URLごと）を返す。

    docs: [{"conference", "year", "title", "doi", "pages": [ページの文章], "records": [UrlRecord]}]
    """
    judge = Judge(provider, load_prompt(PROMPT_VERSION), cache_dir=CACHE_DIR)
    papers, datasets, urls = [], [], []
    stopped = ""
    for i, doc in enumerate(docs, start=1):
        if progress:
            progress(i - 1, len(docs), doc["title"])
        item = build_llm_input(doc["title"], doc["pages"], doc["records"])
        cached = judge._cache_path(judge.prompt.render_user(item)).exists()
        if not cached and not _use_one():
            stopped = f"アプリ全体の1日の上限（{DAILY_LIMIT}本）に達したため、残りは判定していません。明日また試してください。"
            break
        try:
            j = judge.judge(item)
        except DailyLimitReached:
            stopped = "Gemini の無料枠の1日の上限に達したため、残りは判定していません。明日また試してください。"
            break
        except LLMError as e:
            stopped = f"AIの呼び出しに失敗したため、残りは判定していません（{e}）"
            break

        base = {"conference": doc["conference"], "year": doc["year"], "title": doc["title"]}
        if j.status != STATUS_OK:
            papers.append({**base, "shares": "判定不能", "kind": "不明", "n_datasets": 0, "evidence": ""})
            continue
        answer = j.answer
        found = answer.get("datasets") or []
        papers.append({**base, "shares": SHARES_LABELS.get(answer["paper"]["shares_dataset"], "不明"),
                       "kind": four_class(answer["paper"]["shares_dataset"], [d["availability"] for d in found]),
                       "n_datasets": len(found), "evidence": answer["paper"].get("evidence", "")})
        for d in found:
            datasets.append({**base, "name": d["name"], "url": d.get("url") or "",
                             "availability": AVAILABILITY_LABELS.get(d["availability"], d["availability"]),
                             "evidence": d.get("evidence", "")})
        flags = {u["id"]: u for u in answer.get("urls", [])}
        for u in item.urls:
            f = flags.get(u.id, {})
            if f.get("is_data_location"):
                urls.append({**base, "url": u.url, "page": u.page, "reason": f.get("reason", "")})
    if progress:
        progress(len(docs), len(docs), "")
    return {"papers": papers, "datasets": datasets, "urls": urls, "stopped": stopped}


def four_class(shares: str, availabilities: list[str]) -> str:
    """2段の答えを、公開／要申請／非公開／不明 の4つに分ける（研究の評価と同じ分け方）。"""
    if shares == "yes":
        if any(a in ("P", "L") for a in availabilities):
            return "公開"
        return "要申請" if availabilities else "不明"
    if shares == "no":
        return "非公開"
    return "不明"


# --- 論文の言語 ------------------------------------------------------------------------
# AIに渡す材料（データについて書かれた文）は英語の言い回しでしか探せず、正しく判定できることを
# 確かめたのも英語の論文（LAK・EDM・AIED）だけなので、AIの判定は英語の論文に限る。
# 日本語の論文は、データについての文が1つも取り出せず、ほとんど材料なしで判定することになる。

MIN_LETTERS = 200  # 文字がこれより少ないPDF（画像だけのPDFなど）は、本文を読めないとみなす
ENGLISH_RATIO = 0.8  # 文字のうち英字（a〜z）が占める割合がこれ以上なら英語の論文とみなす
LANG_EN, LANG_OTHER, LANG_NO_TEXT = "英語", "英語以外", "本文なし"
EXCLUDED_REASONS = {
    LANG_OTHER: "日本語など英語以外の論文（AIの判定が未対応）",
    LANG_NO_TEXT: "本文の文字を読み取れない（画像だけのPDFなど）",
}


def paper_language(pages: list[str]) -> str:
    """論文の言語をおおまかに判定する（英語／英語以外／本文なし）。"""
    letters = [c for page in pages for c in page if c.isalpha()]
    if len(letters) < MIN_LETTERS:
        return LANG_NO_TEXT
    ascii_letters = sum(c.isascii() for c in letters)
    return LANG_EN if ascii_letters / len(letters) >= ENGLISH_RATIO else LANG_OTHER


def split_by_language(docs: list[dict]) -> tuple[list[dict], list[dict]]:
    """AIで判定できる論文（英語）と、対象外の論文に分ける。判定した言語は doc["language"] に覚えておく。"""
    eligible, excluded = [], []
    for d in docs:
        if "language" not in d:
            d["language"] = paper_language(d["pages"])
        (eligible if d["language"] == LANG_EN else excluded).append(d)
    return eligible, excluded


# --- 画面 ---------------------------------------------------------------------------

def render_ai_section(docs: list[dict], state_key: str = "ai", require_consent: bool = False) -> None:
    """AIで判定する欄（STEP 4 と、手元の論文のページで使う）。

    state_key      : 判定の結果などを覚える名前（ページごとに分け、混ざらないようにする）
    require_consent: True なら「公開済みの論文です」の確認にチェックしてから判定できる（手元の論文用）
    """
    api_key = gemini_api_key()
    if not api_key:
        st.info("この環境では AI の判定を使えません（Gemini のAPIキーが設定されていません）。")
        return

    eligible, excluded = split_by_language(docs)
    sig = selection_key(eligible, state_key)
    pending_key, runs_key = state_key + "_pending", state_key + "_pending_runs"
    # 別の論文（前の検索やアップロード）の結果・途中の判定は使わない
    for key in (state_key, pending_key):
        if (st.session_state.get(key) or {}).get("sig", sig) != sig:
            st.session_state.pop(key, None)
    result = st.session_state.get(state_key)
    pending = st.session_state.get(pending_key)

    if result is None and pending is not None:
        # 判定の途中。ボタンを押した回の実行だけで判定すると、途中で画面の更新（表の操作など）が届いたときに
        # 実行が打ち切られて、選ぶ画面に戻ってしまう。そこで「判定する論文」を覚えておき、打ち切られても
        # 次の実行で続きから判定する（判定済みの論文は保存した答えを使うので、回数は増えない）
        runs = st.session_state[runs_key] = st.session_state.get(runs_key, 0) + 1
        if runs > 5:  # 何度も打ち切られる（想定外の問題がある）ときは、あきらめて選ぶ画面に戻す
            st.session_state.pop(pending_key, None)
            st.session_state.pop(runs_key, None)
            st.error("判定を最後まで終えられませんでした。もう一度試してください。")
        else:
            counter = st.empty()
            bar = st.progress(0.0, text="準備中…")

            def progress(done, total, title):
                # 1本判定するごとに、残りの本数を数え直して表示する
                counter.html(remaining_html(remaining_today()))
                bar.progress(done / total if total else 1.0,
                             text=f"（{done + 1}/{total}）{title[:60]}" if done < total else "完了しました")

            target = [eligible[i] for i in pending["indices"] if i < len(eligible)]
            st.session_state[state_key] = {**judge_papers(target, make_provider(api_key), progress), "sig": sig}
            st.session_state.pop(pending_key, None)
            st.session_state.pop(runs_key, None)
            st.rerun()

    if result is None:
        left = remaining_today()
        remaining_badge()
        st.caption(
            f"- 1回に判定するのは {MAX_AI_PAPERS} 本までです。1本あたり10秒ほどかかります。\n"
            "- Gemini には論文の本文の一部（URLの前後の文と、データについて書かれた文）とURLだけを送ります。"
            "無料枠のため、送った内容が Google のサービス改善に使われることがあります。\n"
            "- AIの判断は間違えることがあります。必ず根拠の文とリンク先を確かめてください。")
        if excluded:
            show_excluded(excluded)
        if not eligible:
            st.info("AIで判定できる英語の論文がありません。")
            return
        target = choose_papers(eligible, sig)
        too_many = len(target) > MAX_AI_PAPERS
        if too_many:
            st.warning(f"選べるのは {MAX_AI_PAPERS} 本までです（今 {len(target)} 本を選択中）。チェックを減らしてください。")
        agreed = True
        if require_consent:
            agreed = st.checkbox("判定する論文は、すでに公開されている論文です（投稿前の原稿や研究室内の資料ではありません）",
                                 key=state_key + "_consent")
        if st.button(f"選んだ {len(target)} 本をAIで判定する", type="primary", key=state_key + "_run",
                     disabled=left == 0 or too_many or not target or not agreed):
            st.session_state[pending_key] = {"sig": sig, "indices": target}
            st.rerun()
        return

    remaining_badge()
    show_ai_result(result)
    # 結果を消して、選ぶ画面に戻る（一度判定した論文は保存した答えを使うので、回数は減らない）
    if st.button("別の論文を選んで判定する", key=state_key + "_again"):
        st.session_state.pop(state_key, None)
        st.rerun()


def show_excluded(excluded: list[dict]) -> None:
    """AIの判定の対象外にした論文を知らせる。"""
    st.info(f"次の {len(excluded)} 本は、AIの判定の対象外です（URLの抽出結果はそのまま使えます）。"
            "AIで判定できるのは、正しく判定できることを確かめた英語の論文だけです。")
    with st.expander(f"対象外の論文（{len(excluded)}）"):
        st.dataframe(pd.DataFrame({"title": [d["title"] for d in excluded],
                                   "reason": [EXCLUDED_REASONS.get(d["language"], "") for d in excluded]}),
                     hide_index=True, width="stretch",
                     column_config={"title": st.column_config.TextColumn("論文", width="large"),
                                    "reason": st.column_config.TextColumn("理由", width="medium")})


def selection_key(docs: list[dict], prefix: str = "ai") -> str:
    """論文の組み合わせ（＝STEP 3 の実行やアップロード）ごとに、チェックの状態や結果を分けて覚えるための名前。"""
    titles = "\n".join(d["title"] for d in docs)
    return f"{prefix}_selected_" + hashlib.sha256(titles.encode("utf-8")).hexdigest()[:12]


def _visible_columns(rows: list[dict], columns: list[str]) -> list[str]:
    """表に出す列（会議・年などが全部空の列は出さない。手元の論文では空になる）。"""
    return [c for c in columns if any(r.get(c) not in (None, "") for r in rows)]


def choose_papers(docs: list[dict], key: str) -> list[int]:
    """判定する論文をチェックで選ぶ表。選んだ論文の番号（docs の中の位置）を返す。
    最初は先頭の MAX_AI_PAPERS 本にチェックを入れておく。"""
    selected: set[int] = st.session_state.setdefault(key, set(range(min(MAX_AI_PAPERS, len(docs)))))
    rows = [{"selected": i in selected, "conference": d.get("conference"), "year": d.get("year"),
             "title": d["title"], "urls": len(d["records"])} for i, d in enumerate(docs)]
    columns = ["selected"] + _visible_columns(rows, ["conference", "year"]) + ["title", "urls"]
    edited = st.data_editor(
        pd.DataFrame(rows)[columns], hide_index=True, width="stretch", height=min(400, 38 + 35 * len(rows)),
        disabled=[c for c in columns if c != "selected"],
        column_config={
            "selected": st.column_config.CheckboxColumn("判定する", width=90),
            "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
            "year": st.column_config.NumberColumn("年", format="%d", width="small"),
            "title": st.column_config.TextColumn("タイトル", width="large"),
            "urls": st.column_config.NumberColumn("URL数", width="small",
                                                  help="URLが多い論文ほど、データの置き場所が書かれている可能性があります"),
        },
        key=key + "_editor",
    )
    selected.clear()
    selected.update(i for i, checked in edited["selected"].items() if checked)
    return sorted(selected)


def show_ai_result(result: dict) -> None:
    if result["stopped"]:
        st.warning(result["stopped"])
    if not result["papers"]:
        return
    papers = pd.DataFrame(result["papers"])
    counts = papers["kind"].value_counts()
    cols = st.columns(4)
    for col, kind in zip(cols, ("公開", "要申請", "非公開", "不明")):
        col.metric(kind, int(counts.get(kind, 0)))
    st.caption("公開＝誰でも、またはアカウント登録で入手できる／要申請＝著者などに頼めば入手できる／"
               "非公開＝入手できない／不明＝本文からは判断できない（「判定不能」はAIの答えが決められた形にならなかったもの）。"
               "AIの判断なので、根拠の文とリンク先を確かめてください。")

    common = {
        "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
        "year": st.column_config.NumberColumn("年", format="%d", width="small"),
    }
    meta = _visible_columns(result["papers"], ["conference", "year"])
    # タブの名前は短くする（スマホの幅でも3つが1行に収まるように）。詳しい説明は各タブの中に書く
    tab_papers, tab_data, tab_urls = st.tabs([f"論文（{len(papers)}）",
                                              f"データセット（{len(result['datasets'])}）",
                                              f"URL（{len(result['urls'])}）"])
    with tab_papers:
        st.caption("論文ごとの判定です。「根拠の文」は、AIが判断の手がかりにした論文中の文です。")
        st.dataframe(papers[meta + ["title", "shares", "kind", "n_datasets", "evidence"]],
                     hide_index=True, width="stretch", column_config={
                         **common,
                         "title": st.column_config.TextColumn("タイトル", width="large"),
                         "shares": st.column_config.TextColumn("データあり？", width="small"),
                         "kind": st.column_config.TextColumn("分類", width="small"),
                         "n_datasets": st.column_config.NumberColumn("データセット数", width="small"),
                         "evidence": st.column_config.TextColumn("根拠の文", width="large"),
                     })
    with tab_data:
        st.caption("見つかったデータセットの名前・URL・入手方法（公開／要ログイン／要申請）です。")
        if result["datasets"]:
            st.dataframe(pd.DataFrame(result["datasets"])[meta + ["title", "name", "url", "availability", "evidence"]],
                         hide_index=True, width="stretch", column_config={
                             **common,
                             "title": st.column_config.TextColumn("論文", width="medium"),
                             "name": st.column_config.TextColumn("データセット", width="medium"),
                             "url": st.column_config.LinkColumn("URL", width="medium"),
                             "availability": st.column_config.TextColumn("入手方法", width="small"),
                             "evidence": st.column_config.TextColumn("根拠の文", width="large"),
                         })
            st.caption("URLが空のものは、論文に名前と参考文献だけが書かれていて、リンクがなかったものです。")
        else:
            st.info("手に入れられるデータセットは見つかりませんでした。")
    with tab_urls:
        st.caption("論文中のURLのうち、AIが「データの置き場所」と判断したものです。")
        if result["urls"]:
            st.dataframe(pd.DataFrame(result["urls"])[meta + ["title", "url", "page", "reason"]],
                         hide_index=True, width="stretch", column_config={
                             **common,
                             "title": st.column_config.TextColumn("論文", width="medium"),
                             "url": st.column_config.LinkColumn("URL", width="large"),
                             "page": st.column_config.NumberColumn("ページ", width="small"),
                             "reason": st.column_config.TextColumn("AIの理由（英語）", width="large"),
                         })
        else:
            st.info("データの置き場所と判断されたURLはありませんでした。")

    if result["datasets"]:
        from ui_common import csv_bytes

        st.download_button("データセットの一覧をCSVで保存", data=csv_bytes(pd.DataFrame(result["datasets"])),
                           file_name="ai_datasets.csv", mime="text/csv")


