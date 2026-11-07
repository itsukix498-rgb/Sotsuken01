"""評価結果のページ（段階4）。手元のPCで動かしたときだけ表示する。

results/ には先生のデータセットの内容（どの論文がデータを公開しているか、AIが合っていたか）が入るので、
GitHub には上げていない。公開アプリには results/ がないため、このページはメニューに出ない（app.py で判定）。
"""

import json
from pathlib import Path

import pandas as pd
import streamlit as st

RESULTS = Path(__file__).resolve().parent.parent / "results"

st.title("📊 評価結果（手元のPCだけ）")
st.caption("LLMの判定を、研究室の調査（先生のデータセット）と答え合わせした結果です。"
           "研究室の未公開データを含むので、公開アプリには表示されません。")

runs = sorted((d for d in RESULTS.glob("eval_*") if (d / "summary.json").exists()), reverse=True)
if not runs:
    st.info("まだ評価結果がありません。`python scripts/evaluate_llm.py --provider gemini --model <モデル名>` を実行してください。")
    st.stop()

run = st.selectbox("評価結果", runs, format_func=lambda d: d.name)
s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
st.caption(f"モデル: {s.get('model')} ／ プロンプト: {s.get('prompt_version')} ／ 分け方: {s.get('分け方')} ／ "
           f"論文 {s.get('論文の数')} 本 ／ 作成: {s.get('作成日時')}")

p1, p2 = s["1段目"], s["2段目"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("1段目の一致率", f"{p1['一致率']:.0%}", help="データセットを共有しているか（あり／なし）")
c2.metric("P／L／Oの一致率", f"{p2['P／L／Oの一致率']:.0%}", help="結び付いたデータセットの公開の形")
c3.metric("4分類の一致率", f"{s['4分類の一致率']:.0%}", help="公開／要申請／非公開／不明")
c4.metric("URLの再現率（段階3）", f"{s['URL（段階3）']['再現率']:.0%}",
          help=f"段階2（LLMなし）は {s['URL（段階2）']['再現率']:.0%}")


def show(name: str, title: str, index: bool = False) -> None:
    csv, png = run / f"{name}.csv", run / f"{name}.png"
    st.subheader(title)
    if png.exists():
        st.image(str(png))
    if csv.exists():
        df = pd.read_csv(csv, index_col=0 if index else None)
        st.dataframe(df, width="stretch", hide_index=not index)


tab_url, tab_paper, tab_year, tab_eff, tab_err = st.tabs(
    ["URLの判断", "公開状況", "発表年ごと", "効率・再現性", "間違えた例"])
with tab_url:
    show("url_comparison", "データの公開先URL：LLMの前後の比較")
    st.caption(f"論文の中に書かれていた正解URLに対する段階3の再現率: "
               f"{s.get('論文中にあった正解URLに対する段階3の再現率', 0):.0%}")
with tab_paper:
    show("paper_confusion", "1段目：データセットを共有しているか", index=True)
    show("by_kind", "論文の種類ごとの一致率")
    show("dataset_confusion", "2段目：公開の形（P／L／O）", index=True)
    st.caption(f"見落とした正解データセット {p2['見落とした正解データセット']} 件、"
               f"余分に挙げたデータセット {p2['余分に挙げたデータセット']} 件")
    show("four_class_confusion", "4分類（公開／要申請／非公開／不明）", index=True)
with tab_year:
    show("by_year", "発表年ごとの一致率")
with tab_eff:
    show("efficiency", "効率と、有料APIだった場合の費用の目安")
    st.caption(f"料金は {s.get('料金の確認日')} に公式の料金表で確認した値です。")
    st.subheader("再現性（同じ設定で繰り返し判定したときの一致）")
    if s.get("再現性"):
        st.json(s["再現性"])
    else:
        st.info("繰り返しの判定（--repeat 1、--repeat 2）がまだないので、計算していません。")
with tab_err:
    st.caption("プロンプトを直すための材料です。調整用の論文だけを見てください。")
    errors = run / "errors.csv"
    if errors.exists():
        st.dataframe(pd.read_csv(errors), width="stretch", hide_index=True)
