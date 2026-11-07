"""STEP 1 論文を検索するページ：会議・学会誌と年を選んで論文一覧を集める。"""

import streamlit as st

from collect_papers import (
    CONFERENCES,
    JSTAGE_INTERVAL,
    JSTAGE_JOURNALS,
    JSTAGE_MAX_BATCH,
    PDF_AUTO,
    YEAR_RANGES,
    collect_papers,
)
from ui_common import go_to_step, step_header

# 1回にまとめて処理するPDFの上限（相手サーバーへの負担と、公開サーバーの処理時間を考えて）
MAX_BATCH = 30
HISTORY_SIZE = 5  # 検索の履歴に残す件数


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def search(conferences: tuple, years: tuple, keyword: str):
    """論文検索（同じ条件なら6時間は結果を使い回して、APIへの問い合わせを減らす）。"""
    papers, notes = collect_papers(list(conferences), list(years), keyword)
    return [p.to_row() for p in papers], notes


def default_selection(rows: list[dict]) -> set[int]:
    """最初にチェックを入れておく論文（PDFを自動取得できるものを、処理できる本数まで）。"""
    selected, n_jstage, n_other = set(), 0, 0
    for i, row in enumerate(rows):
        if row["pdf_status"] != PDF_AUTO:
            continue
        if row["conference"] in JSTAGE_JOURNALS:
            if n_jstage < JSTAGE_MAX_BATCH and n_jstage + n_other < MAX_BATCH:
                selected.add(i)
                n_jstage += 1
        elif n_jstage + n_other < MAX_BATCH:
            selected.add(i)
            n_other += 1
    return selected


st.title("論文を検索")
# ページを移動するとウィジェットの状態は消えるので、前回の条件は別に保存しておき初期値に使う
form = st.session_state.get("form", {})
step_header(1)
st.write("調べたい会議・学会誌と年を選んで、論文の一覧を集めます。")

with st.container(border=True):
    intl = st.pills(
        "国際会議（英語）", list(CONFERENCES), selection_mode="multi", default=form.get("intl", ["EDM"]),
        help="\n".join(f"- **{k}**: {v}" for k, v in CONFERENCES.items()),
    )
    domestic = st.pills(
        "国内の学会誌・大会（日本語・J-STAGE）", list(JSTAGE_JOURNALS), selection_mode="multi",
        default=form.get("domestic", []),
        help="\n".join(f"- **{k}**: {v['material']}" for k, v in JSTAGE_JOURNALS.items()),
    )
    c1, c2 = st.columns([3, 2])
    keyword = c1.text_input("タイトルのキーワード（任意）",
                            value=form.get("keyword", ""), placeholder="例: dropout, knowledge tracing, 学習分析, 生成AI")
    year_from, year_to = c2.select_slider("年", options=list(range(2020, 2027)), value=form.get("years", (2024, 2024)))

    with st.expander("会議・学会誌ごとの対応状況"):
        st.markdown(
            "| 会議・学会誌 | 論文一覧 | PDFの自動取得 |\n|---|---|---|\n"
            f"| LAK | {YEAR_RANGES['LAK'][0]}年〜（Crossref） | ほぼ不可：ACMが自動取得を禁止しています。論文ページから手動で保存してください |\n"
            f"| EDM | {YEAR_RANGES['EDM'][0]}年〜（Zenodo） | ほぼすべて可能（オープンアクセス） |\n"
            f"| AIED | {YEAR_RANGES['AIED'][0]}年〜（Crossref） | 一部のみ：オープンアクセスの論文だけ取得できます |\n"
            + "".join(f"| {k}（{v['material']}） | {YEAR_RANGES[k][0]}年〜（J-STAGE） | 多くが可能 |\n"
                      for k, v in JSTAGE_JOURNALS.items())
            + f"\nJ-STAGEの論文は、利用規約（機械的な大量ダウンロードの禁止）に配慮し、1回{JSTAGE_MAX_BATCH}本まで・"
            f"{JSTAGE_INTERVAL:.0f}秒おきに取得します。"
            "EDM 2022年以前は、論文がZenodoで公開されていないため一覧に出ません。"
            "JSAI全国大会は1年で約1,000件あるので、キーワードで絞るのがおすすめです。"
        )

    conferences = intl + domestic
    years = list(range(year_from, year_to + 1))
    too_many = len(conferences) * len(years) > 6
    if not conferences:
        st.caption("会議・学会誌を1つ以上選んでください。")
    elif too_many:
        st.warning("組み合わせが多すぎます。会議・学会誌×年の組み合わせを6つまでにしてください。")
    else:
        st.caption(f"{len(conferences)} 件 × {len(years)} 年 を検索します。")
    clicked = st.button("検索して次へ", type="primary", disabled=not conferences or too_many, width="stretch")
    if domestic:
        # J-STAGE WebAPI の利用条件として、提供元の表示とJ-STAGEへのリンクが必要
        st.caption("国内の学会誌・大会の論文情報は [J-STAGE](https://www.jstage.jst.go.jp/) から取得しています。"
                   "Powered by J-STAGE")

def open_result(entry: dict) -> None:
    """検索の結果（今の検索、または履歴から選んだもの）を開いて STEP 2 へ進む。"""
    st.session_state["form"] = entry["form"]
    st.session_state["papers"] = entry["rows"]
    st.session_state["search_notes"] = entry["notes"]
    st.session_state["search_label"] = entry["label"]
    st.session_state["selected"] = default_selection(entry["rows"])
    # 前回の抽出結果とAIの判定結果は、別の論文のものなので消す
    for key in ("batch", "ai", "ai_pending"):
        st.session_state.pop(key, None)
    go_to_step(2)


if clicked:
    with st.spinner("論文データベースを検索しています…（数秒〜30秒ほど）"):
        rows, notes = search(tuple(conferences), tuple(years), keyword.strip())
    label = ("・".join(conferences)
             + (f" / {year_from}年" if year_from == year_to else f" / {year_from}〜{year_to}年")
             + (f" / 「{keyword}」" if keyword else ""))
    entry = {"label": label, "rows": rows, "notes": notes,
             "form": {"intl": intl, "domestic": domestic, "keyword": keyword, "years": (year_from, year_to)}}
    # 検索の履歴（この画面を開いている間だけ）。同じ条件は1つにまとめ、新しい順に5件まで残す
    history = [h for h in st.session_state.get("history", []) if h["label"] != label]
    st.session_state["history"] = [entry] + history[:HISTORY_SIZE - 1]
    open_result(entry)

# 検索の履歴：前に検索した結果を、もう一度検索せずに開き直せる
history = st.session_state.get("history", [])
if history:
    st.subheader("検索の履歴")
    st.caption("この画面を開いている間の検索です（ページを閉じたり再読み込みしたりすると消えます）。")
    current = st.session_state.get("search_label")
    for i, entry in enumerate(history):
        with st.container(border=True):
            text_col, button_col = st.columns([3, 1], vertical_alignment="center")
            mark = "（表示中）" if entry["label"] == current else ""
            text_col.markdown(f"**{entry['label']}**{mark}　{len(entry['rows'])} 件")
            if button_col.button("開く", key=f"history_{i}", width="stretch"):
                open_result(entry)
