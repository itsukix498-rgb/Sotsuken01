"""論文から公開教育データを探すWebアプリ（Streamlit）の入口。

起動方法:
    streamlit run app.py

ページ構成（左上の ☰ メニューから切り替える）:
    ホーム                         … views/home.py（最初に開くページ）
    使い方                         … views/guide.py
    論文を検索して調べる
        STEP 1 論文を検索          … views/step1_search.py
        STEP 2 論文を選ぶ          … views/step2_select.py
        STEP 3 URLを抽出           … views/step3_extract.py
        STEP 4 AIで判定            … views/step4_judge.py
    手元の論文
        手元の論文を調べる         … views/extract.py
"""

import hmac
from pathlib import Path

import streamlit as st
from streamlit import config as st_config

from ui_common import GUIDE_PAGE, HOME_PAGE, STEP_PAGES, UPLOAD_PAGE, apply_style, flow, hero

st.set_page_config(page_title="Paper Data Finder", page_icon=":material/menu_book:", layout="wide",
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

    _, center, _ = st.columns([1, 3, 1])
    with center:
        hero("研究室メンバー向け・研究用", "Paper Data Finder",
             "論文を読んで、使える教育データセットを見つけるツールです。")
        flow()
        with st.form("login", border=True):
            st.markdown("**合言葉を入力してください**")
            st.caption("このアプリは研究室のメンバーだけが使えます。合言葉は研究室で共有しているものです。")
            password = st.text_input("合言葉", type="password", placeholder="合言葉を入力",
                                     label_visibility="collapsed")
            submitted = st.form_submit_button("入る", type="primary", width="stretch")
            if submitted:
                # 文字列比較の時間差から推測されないよう compare_digest を使う
                if hmac.compare_digest(password.encode(), str(expected).encode()):
                    st.session_state["authenticated"] = True
                    st.rerun()
                else:
                    st.error("合言葉が違います。もう一度入力してください。")
    return False


if not check_password():
    st.stop()

step_icons = {1: ":material/search:", 2: ":material/checklist:", 3: ":material/link:", 4: ":material/fact_check:"}
pages = {
    "": [
        st.Page(HOME_PAGE, title="ホーム", icon=":material/home:", default=True),
        st.Page(GUIDE_PAGE, title="使い方", icon=":material/help:"),
    ],
    "論文を検索して調べる": [
        st.Page(path, title=f"STEP {n}　{label}", icon=step_icons[n])
        for n, (path, label) in STEP_PAGES.items()
    ],
    "手元の論文": [
        st.Page(UPLOAD_PAGE, title="手元の論文を調べる", icon=":material/upload_file:"),
    ],
}
# 評価結果のページは、手元のPCに results/ の評価結果があるときだけメニューに出す
# （研究室の未公開データを含むので GitHub には上げておらず、公開アプリには results/ がない）
if any(Path("results").glob("eval_*/summary.json")):
    pages["研究（手元のPCだけ）"] = [st.Page("views/evaluation.py", title="評価結果", icon=":material/analytics:")]
nav = st.navigation(pages)

with st.sidebar:
    st.caption("論文を集めて本文からURLを抜き出し、AIが使える教育データセットを見つけます。")
    st.caption("データ: Crossref / Zenodo / OpenAlex / [J-STAGE](https://www.jstage.jst.go.jp/)（Powered by J-STAGE）"
               " / AI: Google Gemini")

nav.run()
