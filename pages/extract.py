"""② URLを抽出するページ：手元のPDF（複数可）をアップロードしてURLを一覧にする。"""

from pathlib import Path

import pandas as pd
import streamlit as st

from extract_urls import PdfOpenError, extract_urls_from_pdf, open_pdf_bytes
from ui_common import csv_bytes, show_url_table, url_rows

SAMPLE_PDF = Path(__file__).resolve().parent.parent / "samples" / "sample_paper.pdf"


@st.cache_data(show_spinner=False, max_entries=50)
def run_extraction(data: bytes, name: str):
    """PDFのバイト列からURL一覧とページ数を返す（同じファイルは再計算しない）。"""
    with open_pdf_bytes(data, name) as doc:
        return extract_urls_from_pdf(doc), doc.page_count


st.title("🔗 URLを抽出する")
st.write("手元の論文PDFをアップロードすると、本文とハイパーリンクに含まれるURLを一覧にします。"
         "「① 論文を集める」で自動取得できなかった論文（LAKなど）もここで処理できます。")

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
rows, summary = [], []
with st.spinner("URLを抽出しています…"):
    for name, data in files:
        try:
            records, pages = run_extraction(data, name)
        except PdfOpenError as e:
            summary.append({"file": name, "pages": None, "urls": 0, "status": f"⚠️ {e}"})
            continue
        rows += url_rows(records, file=name)
        summary.append({"file": name, "pages": pages, "urls": len(records), "status": "✅ 成功"})

# --- 結果表示 ------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("PDF", len(files))
c2.metric("URL件数", len(rows))
c3.metric("本文から", sum("text" in r["source"] for r in rows))
c4.metric("リンク注釈から", sum("annotation" in r["source"] for r in rows))

for s in summary:
    if s["status"] != "✅ 成功":
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
    st.download_button("💾 CSVをダウンロード", data=csv_bytes(pd.DataFrame(rows)[cols]), file_name=name,
                       mime="text/csv", type="primary")
