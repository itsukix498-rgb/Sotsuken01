"""STEP 3 の「AIで判定する（試験版）」の部品。

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


# --- 画面 ---------------------------------------------------------------------------

def render_ai_section(docs: list[dict]) -> None:
    """STEP 3 の結果の下に出す「AIで判定する（試験版）」の欄。"""
    api_key = gemini_api_key()
    if not api_key or not docs:
        return  # キーが設定されていない、または本文を取得できた論文がない

    st.divider()
    st.subheader("🤖 AIで判定する（試験版）")
    result = st.session_state.get("ai")
    pending = st.session_state.get("ai_pending")
    if result is None and pending is not None:
        # 判定の途中。ボタンを押した回の実行だけで判定すると、途中で画面の更新（表の操作など）が届いたときに
        # 実行が打ち切られて、選ぶ画面に戻ってしまう。そこで「判定する論文」を覚えておき、打ち切られても
        # 次の実行で続きから判定する（判定済みの論文は保存した答えを使うので、回数は増えない）
        runs = st.session_state["ai_pending_runs"] = st.session_state.get("ai_pending_runs", 0) + 1
        if runs > 5:  # 何度も打ち切られる（想定外の問題がある）ときは、あきらめて選ぶ画面に戻す
            st.session_state.pop("ai_pending", None)
            st.session_state.pop("ai_pending_runs", None)
            st.error("判定を最後まで終えられませんでした。もう一度試してください。")
        else:
            bar = st.progress(0.0, text="準備中…")

            def progress(done, total, title):
                bar.progress(done / total if total else 1.0,
                             text=f"（{done + 1}/{total}）{title[:60]}" if done < total else "完了しました")

            st.session_state["ai"] = judge_papers([docs[i] for i in pending if i < len(docs)],
                                                  make_provider(api_key), progress)
            st.session_state.pop("ai_pending", None)
            st.session_state.pop("ai_pending_runs", None)
            st.rerun()
    if result is None:
        left = remaining_today()
        st.write("取得した論文を AI（Google Gemini）が読み、**手に入れられる教育データセットがあるか**と、"
                 "その**名前・URL・入手方法**を判定します。")
        st.caption(
            f"- 1回に判定するのは {MAX_AI_PAPERS} 本までです。1本あたり10秒ほどかかります。\n"
            f"- 今日あと {left} 本まで判定できます（アプリを使う全員の合計）。\n"
            "- Gemini には論文の本文の一部（URLの前後の文と、データについて書かれた文）とURLだけを送ります。"
            "無料枠のため、送った内容が Google のサービス改善に使われることがあります。\n"
            "- AIの判断は間違えることがあります。必ず根拠の文とリンク先を確かめてください。")
        target = choose_papers(docs)
        too_many = len(target) > MAX_AI_PAPERS
        if too_many:
            st.warning(f"選べるのは {MAX_AI_PAPERS} 本までです（今 {len(target)} 本を選択中）。チェックを減らしてください。")
        if st.button(f"🤖 選んだ {len(target)} 本をAIで判定する", type="primary",
                     disabled=left == 0 or too_many or not target):
            st.session_state["ai_pending"] = target
            st.rerun()
        return

    show_ai_result(result)
    # 結果を消して、選ぶ画面に戻る（一度判定した論文は保存した答えを使うので、回数は減らない）
    if st.button("🔁 別の論文を選んで判定する"):
        st.session_state.pop("ai", None)
        st.rerun()


def selection_key(docs: list[dict]) -> str:
    """論文の組み合わせ（＝STEP 3 の実行）ごとに、チェックの状態を分けて覚えるための名前。"""
    titles = "\n".join(d["title"] for d in docs)
    return "ai_selected_" + hashlib.sha256(titles.encode("utf-8")).hexdigest()[:12]


def choose_papers(docs: list[dict]) -> list[int]:
    """判定する論文をチェックで選ぶ表。選んだ論文の番号（docs の中の位置）を返す。
    最初は先頭の MAX_AI_PAPERS 本にチェックを入れておく。"""
    batch_key = selection_key(docs)
    selected: set[int] = st.session_state.setdefault(batch_key, set(range(min(MAX_AI_PAPERS, len(docs)))))
    table = pd.DataFrame({
        "selected": [i in selected for i in range(len(docs))],
        "conference": [d["conference"] for d in docs],
        "year": [d["year"] for d in docs],
        "title": [d["title"] for d in docs],
        "urls": [len(d["records"]) for d in docs],
    })
    edited = st.data_editor(
        table, hide_index=True, width="stretch", height=min(400, 38 + 35 * len(table)),
        disabled=["conference", "year", "title", "urls"],
        column_config={
            "selected": st.column_config.CheckboxColumn("判定する", width="small"),
            "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
            "year": st.column_config.NumberColumn("年", format="%d", width="small"),
            "title": st.column_config.TextColumn("タイトル", width="large"),
            "urls": st.column_config.NumberColumn("URL数", width="small",
                                                  help="URLが多い論文ほど、データの置き場所が書かれている可能性があります"),
        },
        key=batch_key + "_editor",
    )
    selected.clear()
    selected.update(i for i, checked in edited["selected"].items() if checked)
    return sorted(selected)


def show_ai_result(result: dict) -> None:
    papers = pd.DataFrame(result["papers"])
    if result["stopped"]:
        st.warning(result["stopped"])
    if papers.empty:
        return
    counts = papers["kind"].value_counts()
    cols = st.columns(4)
    for col, kind in zip(cols, ("公開", "要申請", "非公開", "不明")):
        col.metric(kind, int(counts.get(kind, 0)))
    st.caption("公開＝誰でも、またはアカウント登録で入手できる／要申請＝著者などに頼めば入手できる／"
               "非公開＝入手できない／不明＝本文からは判断できない（「判定不能」はAIの答えが決められた形にならなかったもの）。"
               "AIの判断なので、根拠の文とリンク先を確かめてください。")

    tab_papers, tab_data, tab_urls = st.tabs([f"📄 論文ごと（{len(papers)}）",
                                              f"🗂️ データセット（{len(result['datasets'])}）",
                                              f"🔗 データの置き場所のURL（{len(result['urls'])}）"])
    with tab_papers:
        st.dataframe(papers, hide_index=True, width="stretch", column_config={
            "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
            "year": st.column_config.NumberColumn("年", format="%d", width="small"),
            "title": st.column_config.TextColumn("タイトル", width="large"),
            "shares": st.column_config.TextColumn("データあり？", width="small"),
            "kind": st.column_config.TextColumn("分類", width="small"),
            "n_datasets": st.column_config.NumberColumn("データセット数", width="small"),
            "evidence": st.column_config.TextColumn("根拠の文", width="large"),
        })
    with tab_data:
        if result["datasets"]:
            st.dataframe(pd.DataFrame(result["datasets"]), hide_index=True, width="stretch", column_config={
                "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
                "year": st.column_config.NumberColumn("年", format="%d", width="small"),
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
        if result["urls"]:
            st.dataframe(pd.DataFrame(result["urls"]), hide_index=True, width="stretch", column_config={
                "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
                "year": st.column_config.NumberColumn("年", format="%d", width="small"),
                "title": st.column_config.TextColumn("論文", width="medium"),
                "url": st.column_config.LinkColumn("URL", width="large"),
                "page": st.column_config.NumberColumn("ページ", width="small"),
                "reason": st.column_config.TextColumn("AIの理由（英語）", width="large"),
            })
        else:
            st.info("データの置き場所と判断されたURLはありませんでした。")

    if result["datasets"]:
        from ui_common import csv_bytes

        st.download_button("💾 データセットの一覧をCSVで保存", data=csv_bytes(pd.DataFrame(result["datasets"])),
                           file_name="ai_datasets.csv", mime="text/csv")
