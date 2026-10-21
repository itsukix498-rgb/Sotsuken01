"""論文から公開教育データを探すWebアプリ（Streamlit）の入口。

起動方法:
    streamlit run app.py

ページ構成（左上の ☰ メニューから切り替える）:
    論文を集める
        STEP 1 論文を検索        … views/step1_search.py
        STEP 2 論文を選ぶ        … views/step2_select.py
        STEP 3 URLを抽出         … views/step3_extract.py
    手元のPDF
        手元のPDFからURL抽出     … views/extract.py
"""

import hmac
from pathlib import Path

import streamlit as st
from streamlit import config as st_config

from ui_common import STEP_PAGES, apply_style

st.set_page_config(page_title="Paper Data Finder", page_icon="🔎", layout="wide",
                   initial_sidebar_state="collapsed")
apply_style()


def _password_required() -> str | None:
    """設定された合言葉を返す。未設定（手元で動かすとき）なら None。"""
    try:
        return st.secrets.get("APP_PASSWORD") or None
    except Exception:
        # secrets.toml があるのに読めない（書き間違いなど）ときは、合言葉なしで開けてしまわないよう止める
        if any(Path(p).is_file() for p in st_config.get_option("secrets.files")):
            st.error("合言葉の設定（secrets.toml）を読み込めませんでした。書き方を確認してください。"
                     "（例: APP_PASSWORD = \"合言葉\"、文字コードは BOM なしの UTF-8）")
            st.stop()
        return None  # secrets.toml がない場合（手元で動かすとき）


def check_password() -> bool:
    """合言葉が設定されていれば入力画面を出し、正しく入力されたら True を返す。"""
    expected = _password_required()
    if expected is None or st.session_state.get("authenticated"):
        return True

    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.title("🔎 Paper Data Finder")
        st.write("研究室メンバー向けのアプリです。合言葉を入力してください。")
        with st.form("login"):
            password = st.text_input("合言葉", type="password")
            submitted = st.form_submit_button("入る", type="primary", width="stretch")
        if submitted:
            # 文字列比較の時間差から推測されないよう compare_digest を使う
            if hmac.compare_digest(password.encode(), str(expected).encode()):
                st.session_state["authenticated"] = True
                st.rerun()
            else:
                st.error("合言葉が違います。")
    return False


if not check_password():
    st.stop()

step_icons = {1: "🔍", 2: "☑️", 3: "⬇️"}
pages = {
    "論文を集める": [
        st.Page(path, title=f"STEP {n}　{label}", icon=step_icons[n], default=(n == 1))
        for n, (path, label) in STEP_PAGES.items()
    ],
    "手元のPDF": [
        st.Page("views/extract.py", title="手元のPDFからURL抽出", icon="🔗"),
    ],
}
nav = st.navigation(pages)

with st.sidebar:
    st.caption("論文を集め、本文から公開データの手がかり（URL）を見つけます。")
    st.caption("データ: Crossref / Zenodo / OpenAlex / [J-STAGE](https://www.jstage.jst.go.jp/)（Powered by J-STAGE）")

nav.run()
