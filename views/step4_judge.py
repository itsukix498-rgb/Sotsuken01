"""STEP 4 AIで判定するページ：STEP 3 で本文を取得した論文を AI が読み、使える教育データセットを判定する。"""

import streamlit as st

from ui_ai import render_ai_section
from ui_common import go_to_step, page_title, step_header

page_title("STEP 4 / AI Check", "AIで判定")
step_header(4)
st.write("STEP 3 で取得した論文を AI（Google Gemini）が読み、**手に入れられる教育データセットがあるか**と、"
         "その**名前・URL・入手方法**を判定します（試験版）。")

batch = st.session_state.get("batch")
docs = (batch or {}).get("docs", [])
if not docs:
    st.info("まだ論文の本文を取得していません。STEP 3 でPDFを取得してから判定してください。")
    back, start = st.columns(2)
    if back.button("STEP 3 へ", type="primary", width="stretch"):
        go_to_step(3)
    if start.button("STEP 1 から始める", width="stretch"):
        go_to_step(1)
    st.stop()

render_ai_section(docs, state_key="ai")

st.divider()
back, again = st.columns(2)
if back.button("← STEP 3 の結果に戻る", width="stretch"):
    go_to_step(3)
if again.button("新しく検索する", width="stretch"):
    for key in ("batch", "ai", "ai_pending"):
        st.session_state.pop(key, None)
    go_to_step(1)
