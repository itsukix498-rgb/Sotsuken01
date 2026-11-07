"""手元の論文を調べるページ：手元のPDF（複数可）をアップロードしてURLを一覧にし、英語の論文はAIでも判定する。"""

from pathlib import Path

import pandas as pd
import streamlit as st

from extract_urls import PdfOpenError, extract_page_texts, extract_urls_from_pdf, open_pdf_bytes
from ui_ai import render_ai_section
from ui_common import csv_bytes, show_url_table, url_rows

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "samples" / "sample_paper.pdf"
OK = "成功"


@st.cache_data(show_spinner=False, max_entries=50)
def run_extraction(data: bytes, name: str):
    """PDFのバイト列から、URL一覧・ページ数・ページごとの文章を返す（同じファイルは再計算しない）。"""
    with open_pdf_bytes(data, name) as doc:
        return extract_urls_from_pdf(doc), doc.page_count, extract_page_texts(doc)


st.title("手元の論文を調べる")
st.write("持っている論文のPDFをアップロードすると、本文とリンクに含まれるURLを一覧にします。"
         "「論文を検索」で自動取得できなかった論文（LAKなど）も、PDFを保存してここで処理できます。"
         "英語の論文は、AIでデータセットの有無も判定できます。")

with st.container(border=True):
    uploaded = st.file_uploader("論文PDFを選択（複数可・ドラッグ＆ドロップも可）", type=["pdf"], accept_multiple_files=True)
    st.caption("アップロードしたPDFはこの画面での処理にだけ使い、保存しません。")
    if not uploaded and SAMPLE_PDF.exists() and st.button("サンプルPDFで試す"):
        st.session_state["use_sample"] = True

files = [(f.name, f.getvalue()) for f in uploaded or []]
if not files and st.session_state.get("use_sample"):
    files = [(SAMPLE_PDF.name, SAMPLE_PDF.read_bytes())]
if uploaded:
    st.session_state["use_sample"] = False
if not files:
    st.info("PDFをアップロードしてください。")
    st.stop()

# --- 抽出 --------------------------------------------------------------------
rows, summary, docs = [], [], []
with st.spinner("URLを抽出しています…"):
    for name, data in files:
        try:
            records, pages, texts = run_extraction(data, name)
        except PdfOpenError as e:
            summary.append({"file": name, "pages": None, "urls": 0, "status": f"失敗：{e}"})
            continue
        rows += url_rows(records, file=name)
        summary.append({"file": name, "pages": pages, "urls": len(records), "status": OK})
        # AIで判定するときの材料（タイトルの代わりにファイル名を使う）
        docs.append({"conference": "", "year": None, "title": name, "pages": texts, "records": records})

# --- 結果表示 ------------------------------------------------------------------
st.subheader("URLの抽出結果")
c1, c2, c3, c4 = st.columns(4)
c1.metric("PDF", len(files))
c2.metric("URL件数", len(rows))
c3.metric("本文から", sum("text" in r["source"] for r in rows))
c4.metric("リンク注釈から", sum("annotation" in r["source"] for r in rows))

for s in summary:
    if s["status"] != OK:
        st.error(f"{s['file']}: {s['status']}")

if len(files) > 1:
    with st.expander("ファイルごとの結果"):
        st.dataframe(pd.DataFrame(summary), hide_index=True, width="stretch", column_config={
            "file": "ファイル", "pages": "ページ数", "urls": "URL数", "status": "結果"})

show_url_table(rows, key="upload_urls", label_column="file" if len(files) > 1 else None)

if rows:
    # CSVは絞り込みに関係なく全件（コマンドライン版と同じ列。複数ファイルのときは file 列を先頭に足す）
    cols = (["file"] if len(files) > 1 else []) + ["page", "url", "source"]
    name = f"{Path(files[0][0]).stem}_urls.csv" if len(files) == 1 else "uploaded_urls.csv"
    st.download_button("URL一覧をCSVで保存", data=csv_bytes(pd.DataFrame(rows)[cols]), file_name=name, mime="text/csv")

# --- AIで判定（英語の論文だけ） --------------------------------------------------
if docs:
    st.divider()
    st.subheader("AIでデータセットの有無を判定する（英語の論文・試験版）")
    st.write("アップロードした論文を AI が読み、**手に入れられる教育データセットがあるか**と、"
             "その**名前・URL・入手方法**を判定します。")
    st.caption("AIには論文の本文の一部が送られます。**すでに公開されている論文だけ**を判定してください"
               "（投稿前の原稿や研究室内の資料は送らないでください）。")
    render_ai_section(docs, state_key="ai_upload", require_consent=True)
