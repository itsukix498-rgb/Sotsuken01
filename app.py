"""論文PDFからURLを抽出するWebアプリ（Streamlit）。

起動方法:
    streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from extract_urls import (
    PdfOpenError,
    extract_urls_from_pdf,
    open_pdf_bytes,
    records_to_csv,
)

SAMPLE_PDF = Path(__file__).parent / "samples" / "sample_paper.pdf"
SOURCE_LABELS = {
    "text": "本文テキスト",
    "annotation": "リンク注釈",
    "text+annotation": "本文テキスト＋リンク注釈",
}

st.set_page_config(page_title="論文PDF URL抽出", page_icon="🔗", layout="wide")
st.title("🔗 論文PDF URL抽出")
st.caption("論文PDFを1本アップロードすると、本文とハイパーリンクに含まれるURLを一覧にします。")


@st.cache_data(show_spinner="URLを抽出しています…")
def run_extraction(data: bytes, name: str):
    """PDFのバイト列からURL一覧とページ数を返す（同じファイルは再計算しない）。"""
    with open_pdf_bytes(data, name) as doc:
        return extract_urls_from_pdf(doc), doc.page_count


# --- 入力 --------------------------------------------------------------------
uploaded = st.file_uploader("論文PDFを選択（ドラッグ＆ドロップも可）", type=["pdf"])
use_sample = st.button("サンプルPDFで試す", disabled=uploaded is not None or not SAMPLE_PDF.exists())
if use_sample:
    st.session_state["use_sample"] = True
if uploaded is not None:
    st.session_state["use_sample"] = False

if uploaded is not None:
    pdf_name, pdf_bytes = uploaded.name, uploaded.getvalue()
elif st.session_state.get("use_sample"):
    pdf_name, pdf_bytes = SAMPLE_PDF.name, SAMPLE_PDF.read_bytes()
else:
    st.info("PDFをアップロードしてください。")
    st.stop()

# --- 抽出 --------------------------------------------------------------------
try:
    records, page_count = run_extraction(pdf_bytes, pdf_name)
except PdfOpenError as e:
    st.error(str(e))
    st.stop()

# --- 結果表示 ------------------------------------------------------------------
st.subheader(pdf_name)
c1, c2, c3, c4 = st.columns(4)
c1.metric("ページ数", page_count)
c2.metric("URL件数", len(records))
c3.metric("本文から", sum("text" in r.sources for r in records))
c4.metric("リンク注釈から", sum("annotation" in r.sources for r in records))

if not records:
    st.warning("URLは見つかりませんでした。")
    st.stop()

df = pd.DataFrame(
    {
        "page": [r.page for r in records],
        "url": [r.url for r in records],
        "source": [SOURCE_LABELS.get(r.source, r.source) for r in records],
        # スキームなしURL（github.com/... など）もクリックで開けるよう https:// を補う
        "link": [r.url if "://" in r.url else f"https://{r.url}" for r in records],
    }
)

col_filter, col_search = st.columns([2, 3])
selected = col_filter.multiselect("取得元で絞り込み", list(SOURCE_LABELS.values()), default=list(SOURCE_LABELS.values()))
keyword = col_search.text_input("URLで絞り込み（例: github, zenodo, osf）")

view = df[df["source"].isin(selected)]
if keyword:
    view = view[view["url"].str.contains(keyword, case=False, regex=False)]

st.dataframe(
    view,
    hide_index=True,
    width="stretch",
    column_config={
        "page": st.column_config.NumberColumn("ページ", width="small"),
        "url": st.column_config.TextColumn("URL", width="large"),
        "source": st.column_config.TextColumn("取得元", width="medium"),
        "link": st.column_config.LinkColumn("開く", display_text="開く ↗", width="small"),
    },
)
st.caption(f"{len(view)} / {len(df)} 件を表示")

# CSVは絞り込みに関係なく全件（コマンドライン版と同じ形式・BOM付きUTF-8）
st.download_button(
    "CSVをダウンロード",
    data=records_to_csv(records).encode("utf-8-sig"),
    file_name=f"{Path(pdf_name).stem}_urls.csv",
    mime="text/csv",
    type="primary",
)
