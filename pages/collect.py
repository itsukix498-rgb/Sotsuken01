"""① 論文を集めるページ：会議と年で論文を検索し、PDFを取得してURLを抽出する。"""

import pandas as pd
import streamlit as st

from collect_papers import (
    CONFERENCES,
    PDF_AUTO,
    YEAR_RANGES,
    PdfDownloadError,
    collect_papers,
    download_pdf,
    polite_sleep,
)
from extract_urls import PdfOpenError, extract_urls_from_pdf, open_pdf_bytes
from ui_common import csv_bytes, show_url_table, url_rows

# 1回にまとめて処理するPDFの上限（相手サーバーへの負担と、公開サーバーの処理時間を考えて）
MAX_BATCH = 30


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def search(conferences: tuple, years: tuple, keyword: str):
    """論文検索（同じ条件なら6時間は結果を使い回して、APIへの問い合わせを減らす）。"""
    papers, notes = collect_papers(list(conferences), list(years), keyword)
    return [p.to_row() for p in papers], notes


st.title("📚 論文を集める")
st.write("国際会議の論文を検索し、無料で読めるPDFを取得して、本文中のURLを一覧にします。")

# --- STEP 1 検索条件 -------------------------------------------------------------
with st.container(border=True):
    st.subheader("STEP 1　検索条件")
    c1, c2 = st.columns([3, 2])
    with c1:
        conferences = st.pills(
            "会議（複数選べます）", list(CONFERENCES), selection_mode="multi", default=["EDM"],
            format_func=lambda c: c, help="\n".join(f"- **{k}**: {v}" for k, v in CONFERENCES.items()),
        )
        keyword = st.text_input("タイトルのキーワード（任意）", placeholder="例: dropout, knowledge tracing, LLM")
    with c2:
        year_from, year_to = st.select_slider("年", options=list(range(2020, 2027)), value=(2024, 2024))
        st.caption("1回の検索は、会議×年の組み合わせ6つまでにしてください。")

    with st.expander("会議ごとの対応状況"):
        st.markdown(
            "| 会議 | 論文一覧 | PDFの自動取得 |\n|---|---|---|\n"
            f"| LAK | {YEAR_RANGES['LAK'][0]}年〜（Crossref） | ほぼ不可：ACMが自動取得を禁止しています。論文ページから手動で保存してください |\n"
            f"| EDM | {YEAR_RANGES['EDM'][0]}年〜（Zenodo） | ほぼすべて可能（オープンアクセス） |\n"
            f"| AIED | {YEAR_RANGES['AIED'][0]}年〜（Crossref） | 一部のみ：オープンアクセスの論文だけ取得できます |\n\n"
            "EDM 2022年以前は、論文がZenodoで公開されていないため一覧に出ません。"
        )

    years = list(range(year_from, year_to + 1))
    too_many = len(conferences) * len(years) > 6
    if too_many:
        st.warning("組み合わせが多すぎます。会議か年の範囲を減らしてください。")
    clicked = st.button("🔍 論文を検索", type="primary", disabled=not conferences or too_many)

if clicked:
    with st.spinner("論文データベースを検索しています…（数秒〜30秒ほど）"):
        rows, notes = search(tuple(conferences), tuple(years), keyword.strip())
    st.session_state["papers"] = rows
    st.session_state["search_notes"] = notes
    st.session_state["search_label"] = f"{'・'.join(conferences)} / {year_from}〜{year_to}年" + (f" / 「{keyword}」" if keyword else "")
    st.session_state.pop("batch", None)  # 前回の抽出結果は消す

rows = st.session_state.get("papers")
if rows is None:
    st.info("条件を選んで「論文を検索」を押してください。")
    st.stop()

# --- STEP 2 論文を選ぶ -----------------------------------------------------------
for note in st.session_state.get("search_notes", []):
    st.warning(note)

with st.container(border=True):
    st.subheader("STEP 2　論文を選ぶ")
    st.caption(st.session_state.get("search_label", ""))
    if not rows:
        st.info("論文が見つかりませんでした。条件を変えてみてください。")
        st.stop()

    df = pd.DataFrame(rows)
    n_auto = int((df["pdf_status"] == PDF_AUTO).sum())
    m1, m2, m3 = st.columns(3)
    m1.metric("見つかった論文", len(df))
    m2.metric("PDFを自動取得できる", n_auto)
    m3.metric("手動でダウンロードが必要", len(df) - n_auto)

    only_auto = st.toggle("PDFを自動取得できる論文だけ表示", value=n_auto > 0)
    view = df[df["pdf_status"] == PDF_AUTO] if only_auto else df
    view = view.assign(selected=view["pdf_status"] == PDF_AUTO)

    edited = st.data_editor(
        view[["selected", "conference", "year", "title", "authors", "pdf_status", "landing_url"]],
        hide_index=True,
        width="stretch",
        height=min(420, 38 + 35 * len(view)),
        disabled=["conference", "year", "title", "authors", "pdf_status", "landing_url"],
        column_config={
            "selected": st.column_config.CheckboxColumn("選択", help="URL抽出する論文にチェック", width="small"),
            "conference": st.column_config.TextColumn("会議", width="small"),
            "year": st.column_config.NumberColumn("年", format="%d", width="small"),
            "title": st.column_config.TextColumn("タイトル", width="large"),
            "authors": st.column_config.TextColumn("著者", width="medium"),
            "pdf_status": st.column_config.TextColumn("PDF", width="small"),
            "landing_url": st.column_config.LinkColumn("論文ページ", display_text="開く ↗", width="small"),
        },
        key=f"editor_{st.session_state.get('search_label')}_{only_auto}",
    )
    chosen = df.loc[edited.index[edited["selected"]]]
    chosen_auto = chosen[chosen["pdf_status"] == PDF_AUTO]

    left, right = st.columns([3, 2])
    left.download_button(
        "📄 論文一覧をCSVで保存",
        data=csv_bytes(df[["conference", "year", "title", "authors", "doi", "landing_url", "pdf_url", "pdf_status"]]),
        file_name="papers.csv", mime="text/csv",
    )
    if len(chosen) > len(chosen_auto):
        right.caption(f"「手動」の論文 {len(chosen) - len(chosen_auto)} 本は自動処理されません。"
                      "論文ページからPDFを保存し、「② URLを抽出する」でまとめてアップロードしてください。")

# --- STEP 3 PDFを取得してURL抽出 ----------------------------------------------------
with st.container(border=True):
    st.subheader("STEP 3　PDFを取得してURLを抽出")
    count = len(chosen_auto)
    if count > MAX_BATCH:
        st.warning(f"一度に処理できるのは {MAX_BATCH} 本までです（今 {count} 本選択中）。先頭の {MAX_BATCH} 本だけ処理します。")
    target = chosen_auto.head(MAX_BATCH)
    # 1本あたり3〜6秒（ダウンロード＋待ち時間）として目安を出す
    minutes = len(target) * 6 / 60
    estimate = "1分以内" if minutes <= 1 else f"{len(target) * 3 // 60 or 1}〜{round(minutes)}分"
    st.caption(f"{len(target)} 本のPDFを取得します。相手のサーバーに負担をかけないよう1本ずつ取得するため、"
               f"目安で{estimate}かかります。PDFは保存されません。")
    run = st.button("⬇️ PDFを取得してURLを抽出", type="primary", disabled=len(target) == 0)

if run:
    results, url_list = [], []
    progress = st.progress(0.0, text="準備中…")
    for i, (_, paper) in enumerate(target.iterrows(), start=1):
        progress.progress((i - 1) / len(target), text=f"（{i}/{len(target)}）{paper['title'][:60]}")
        status, error, n_urls = "✅ 成功", "", 0
        try:
            with open_pdf_bytes(download_pdf(paper["pdf_url"]), paper["title"]) as doc:
                records = extract_urls_from_pdf(doc)
            n_urls = len(records)
            url_list += url_rows(records, conference=paper["conference"], year=paper["year"],
                                 title=paper["title"], doi=paper["doi"])
        except (PdfDownloadError, PdfOpenError) as e:
            status, error = "⚠️ 失敗", str(e)
        results.append({"conference": paper["conference"], "year": paper["year"], "title": paper["title"],
                        "status": status, "urls": n_urls, "error": error, "landing_url": paper["landing_url"]})
        if i < len(target):
            polite_sleep(1.0)
    progress.progress(1.0, text="完了しました")
    st.session_state["batch"] = {"results": results, "urls": url_list}

batch = st.session_state.get("batch")
if batch:
    res = pd.DataFrame(batch["results"])
    ok = int((res["status"] == "✅ 成功").sum())
    st.success(f"{len(res)} 本中 {ok} 本のPDFを処理し、URLを {len(batch['urls'])} 件見つけました。")

    tab_urls, tab_papers = st.tabs([f"🔗 URL一覧（{len(batch['urls'])}）", f"📄 論文ごとの結果（{len(res)}）"])
    with tab_urls:
        show_url_table(batch["urls"], key="batch_urls", label_column="title")
    with tab_papers:
        st.dataframe(
            res, hide_index=True, width="stretch",
            column_config={
                "conference": st.column_config.TextColumn("会議", width="small"),
                "year": st.column_config.NumberColumn("年", format="%d", width="small"),
                "title": st.column_config.TextColumn("タイトル", width="large"),
                "status": st.column_config.TextColumn("結果", width="small"),
                "urls": st.column_config.NumberColumn("URL数", width="small"),
                "error": st.column_config.TextColumn("失敗の理由", width="medium"),
                "landing_url": st.column_config.LinkColumn("論文ページ", display_text="開く ↗", width="small"),
            },
        )

    if batch["urls"]:
        urls_df = pd.DataFrame(batch["urls"])[["conference", "year", "title", "doi", "page", "url", "source"]]
        st.download_button("💾 URL一覧をCSVで保存", data=csv_bytes(urls_df), file_name="paper_urls.csv",
                           mime="text/csv", type="primary")
