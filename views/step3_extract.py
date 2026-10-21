"""STEP 3 URLを抽出するページ：選んだ論文のPDFを取得し、本文中のURLを一覧にする。"""

import pandas as pd
import streamlit as st

from collect_papers import (
    JSTAGE_INTERVAL,
    JSTAGE_JOURNALS,
    JSTAGE_MAX_BATCH,
    PDF_AUTO,
    PdfDownloadError,
    download_pdf,
    polite_sleep,
)
from extract_urls import PdfOpenError, extract_urls_from_pdf, open_pdf_bytes
from ui_common import csv_bytes, go_to_step, show_url_table, step_header, url_rows

# 1回にまとめて処理するPDFの上限（相手サーバーへの負担と、公開サーバーの処理時間を考えて）
MAX_BATCH = 30

st.title("⬇️ URLを抽出")
step_header(3)

rows = st.session_state.get("papers")
if not rows:
    st.info("まだ論文を検索していません。STEP 1 から始めてください。")
    if st.button("← STEP 1 へ", type="primary"):
        go_to_step(1)
    st.stop()

df = pd.DataFrame(rows)
selected = sorted(st.session_state.get("selected", set()))
chosen_auto = df.loc[selected] if selected else df.iloc[0:0]
chosen_auto = chosen_auto[chosen_auto["pdf_status"] == PDF_AUTO]

# J-STAGEは利用規約（機械的な大量ダウンロードの禁止）に配慮して、ほかより少ない本数に抑える
is_jstage = chosen_auto["conference"].isin(list(JSTAGE_JOURNALS))
jstage_part = chosen_auto[is_jstage].head(JSTAGE_MAX_BATCH)
other_part = chosen_auto[~is_jstage].head(MAX_BATCH - len(jstage_part))
target = pd.concat([other_part, jstage_part])

batch = st.session_state.get("batch")

if not batch:
    if target.empty:
        st.info("PDFを自動取得できる論文が選ばれていません。STEP 2 で論文を選んでください。")
        if st.button("← STEP 2 へ", type="primary"):
            go_to_step(2)
        st.stop()

    with st.container(border=True):
        st.subheader(f"{len(target)} 本のPDFを取得します")
        if is_jstage.sum() > JSTAGE_MAX_BATCH:
            st.warning(f"J-STAGEの論文は、利用規約に配慮して1回 {JSTAGE_MAX_BATCH} 本までにしています"
                       f"（今 {int(is_jstage.sum())} 本選択中）。先頭の {JSTAGE_MAX_BATCH} 本だけ処理します。")
        if (~is_jstage).sum() > len(other_part):
            st.warning(f"一度に処理できるのは {MAX_BATCH} 本までです。先頭から {MAX_BATCH} 本だけ処理します。")
        # 1本あたり：ダウンロード数秒＋待ち時間（J-STAGEは3秒、ほかは1秒）として目安を出す
        seconds = len(other_part) * 4 + len(jstage_part) * (3 + JSTAGE_INTERVAL)
        estimate = "1分以内" if seconds <= 60 else f"約{round(seconds / 60)}分"
        st.caption(f"相手のサーバーに負担をかけないよう1本ずつ取得するため、目安で{estimate}かかります。"
                   "取得したPDFは保存されません。")
        with st.expander("取得する論文の一覧"):
            st.dataframe(target[["conference", "year", "title"]], hide_index=True, width="stretch",
                         column_config={"conference": "会議・学会誌", "year": st.column_config.NumberColumn("年", format="%d"),
                                        "title": "タイトル"})
        back, run_col = st.columns(2)
        if back.button("← 論文を選び直す", width="stretch"):
            go_to_step(2)
        run = run_col.button("⬇️ PDFを取得してURLを抽出", type="primary", width="stretch")

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
                polite_sleep(JSTAGE_INTERVAL if paper["conference"] in JSTAGE_JOURNALS else 1.0)
        progress.progress(1.0, text="完了しました")
        st.session_state["batch"] = {"results": results, "urls": url_list}
        st.rerun()
    st.stop()

# --- 結果 ---------------------------------------------------------------------
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
            "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
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

st.divider()
back, again = st.columns(2)
if back.button("← 別の論文を選ぶ", width="stretch"):
    st.session_state.pop("batch", None)
    go_to_step(2)
if again.button("🔍 新しく検索する", width="stretch"):
    st.session_state.pop("batch", None)
    go_to_step(1)
