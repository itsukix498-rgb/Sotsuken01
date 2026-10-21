"""論文から公開教育データを探すWebアプリ（Streamlit）の入口。

起動方法:
    streamlit run app.py

ページ構成:
    ① 論文を集める   … pages/collect.py
    ② URLを抽出する  … pages/extract.py
"""

import hmac

import streamlit as st

st.set_page_config(page_title="Paper Data Finder", page_icon="🔎", layout="wide")


def _password_required() -> str | None:
    """設定された合言葉を返す。未設定（手元で動かすとき）なら None。"""
    try:
        return st.secrets.get("APP_PASSWORD") or None
    except Exception:  # secrets.toml がない場合
        return None


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

pages = [
    st.Page("pages/collect.py", title="① 論文を集める", icon="📚", default=True),
    st.Page("pages/extract.py", title="② URLを抽出する", icon="🔗"),
]
nav = st.navigation(pages)

with st.sidebar:
    st.caption("論文を集め、本文から公開データの手がかり（URL）を見つけます。")
    st.caption("データ: Crossref / Zenodo / OpenAlex")

nav.run()
