"""ホーム：最初に開くページ。何ができるアプリかを示し、3つの入口（検索・手元の論文・使い方）を置く。"""

import streamlit as st

from ui_common import GUIDE_PAGE, UPLOAD_PAGE, go_to_step, hero

hero("研究室メンバー向け・研究用", "Paper Data Finder",
     "論文を読んで、使える教育データセットを見つけるツールです。"
     "論文を集めて本文からURLを抜き出し、AIがデータセットの有無と入手方法を判定します。")

# 3つの入口。パソコンでは横に3つ、スマホでは縦に並ぶ
search_col, upload_col, guide_col = st.columns(3)
with search_col:
    with st.container(key="pdf_card_main_search"):
        st.markdown("#### 論文を検索して調べる")
        st.write("会議と年を選んで論文を集め、URLを抜き出し、AIでデータセットの有無を判定します。")
        if st.button("論文を検索する", type="primary", width="stretch", key="home_search"):
            go_to_step(1)
with upload_col:
    with st.container(key="pdf_card_upload"):
        st.markdown("#### 手元の論文を調べる")
        st.write("持っている論文のPDFからURLを抜き出します。英語の論文は、AIでも判定できます。")
        if st.button("PDFをアップロードする", width="stretch", key="home_upload"):
            st.switch_page(UPLOAD_PAGE)
with guide_col:
    with st.container(key="pdf_card_guide"):
        st.markdown("#### 使い方")
        st.write("はじめての方へ。各ステップの使い方と、AIの判定結果の見方を説明します。")
        if st.button("使い方を見る", width="stretch", key="home_guide"):
            st.switch_page(GUIDE_PAGE)

st.caption("AIの判定は試験版です。間違えることがあるので、根拠の文とリンク先を必ず確かめてください。"
           "ページは左上の ☰ メニューからも切り替えられます。")
