"""STEP 2 論文を選ぶページ：検索結果から、PDFを取得してURLを抽出する論文を選ぶ。"""

import pandas as pd
import streamlit as st

from collect_papers import JSTAGE_MAX_BATCH, PDF_AUTO
from ui_common import MAX_BATCH, csv_bytes, go_to_step, limited_selection, page_title, step_header

page_title("STEP 2 / Select", "論文を選ぶ")
step_header(2)

rows = st.session_state.get("papers")
if rows is None:
    st.info("まだ論文を検索していません。STEP 1 で条件を選んでください。")
    if st.button("← STEP 1 へ", type="primary"):
        go_to_step(1)
    st.stop()

for note in st.session_state.get("search_notes", []):
    st.warning(note)

st.caption(st.session_state.get("search_label", ""))
if not rows:
    st.info("論文が見つかりませんでした。条件を変えてもう一度検索してください。")
    if st.button("← 条件を変える", type="primary"):
        go_to_step(1)
    st.stop()

df = pd.DataFrame(rows)
selected: set[int] = st.session_state.setdefault("selected", set())

n_auto = int((df["pdf_status"] == PDF_AUTO).sum())
m1, m2, m3 = st.columns(3)
m1.metric("見つかった論文", len(df))
m2.metric("PDFを自動取得できる", n_auto)
m3.metric("手動でダウンロードが必要", len(df) - n_auto)

st.write("PDFを取得してURLを抜き出したい論文に、**「取得する」の列でチェック**を付けてください。")
only_auto = st.toggle("PDFを自動取得できる論文だけ表示", value=n_auto > 0, key="only_auto")
view = df[df["pdf_status"] == PDF_AUTO] if only_auto else df

# まとめて選ぶ・外すボタン。表のチェックの記録（ウィジェットの状態）を作り直すため、表の名前（key）の番号を変える
all_col, none_col, _ = st.columns([1, 1, 2])
if all_col.button("すべて選ぶ", width="stretch", help=f"PDFを自動取得できる論文を、上から{MAX_BATCH}本まで選びます"):
    selected.clear()
    selected.update(limited_selection(rows, view.index))
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
    st.rerun()
if none_col.button("すべて外す", width="stretch"):
    selected.clear()
    st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
    st.rerun()

# チェックの状態は session_state に保存しておき、ページを移動しても消えないようにする
view = view.assign(selected=[i in selected for i in view.index])

edited = st.data_editor(
    view[["selected", "conference", "year", "title", "authors", "pdf_status", "landing_url"]],
    hide_index=True,
    width="stretch",
    height=min(460, 38 + 35 * len(view)),
    disabled=["conference", "year", "title", "authors", "pdf_status", "landing_url"],
    column_config={
        "selected": st.column_config.CheckboxColumn("取得する", help="PDFを取得してURLを抜き出す論文にチェック", width=90),
        "conference": st.column_config.TextColumn("会議・学会誌", width="small"),
        "year": st.column_config.NumberColumn("年", format="%d", width="small"),
        "title": st.column_config.TextColumn("タイトル", width="large"),
        "authors": st.column_config.TextColumn("著者", width="medium"),
        "pdf_status": st.column_config.TextColumn("PDF", width="small"),
        "landing_url": st.column_config.LinkColumn("論文ページ", display_text="開く ↗", width="small"),
    },
    key=f"editor_{st.session_state.get('search_label')}_{only_auto}_{st.session_state.get('editor_version', 0)}",
)
# 表に出ている行だけ、チェックの状態を更新する（非表示の行の選択はそのまま残す）
for i, checked in edited["selected"].items():
    (selected.add if checked else selected.discard)(i)

chosen = df.loc[sorted(selected)] if selected else df.iloc[0:0]
chosen_auto = chosen[chosen["pdf_status"] == PDF_AUTO]
st.caption(f"{len(chosen)} 本を選択中（うちPDFを自動取得できるもの {len(chosen_auto)} 本）")
if chosen_auto.empty:
    st.caption("論文にチェックを付けると、次へ進めます。")
if len(chosen_auto) > MAX_BATCH:
    st.warning(f"一度に取得できるのは {MAX_BATCH} 本までです（J-STAGE は {JSTAGE_MAX_BATCH} 本まで）。"
               f"STEP 3 では、選んだ論文のうち上から {MAX_BATCH} 本だけを取得します。")
if len(chosen) > len(chosen_auto):
    st.info(f"「手動でダウンロード」の論文 {len(chosen) - len(chosen_auto)} 本は自動処理されません。"
            "論文ページからPDFを保存し、メニューの「手元の論文を調べる」でまとめてアップロードしてください。")

st.download_button(
    "論文一覧をCSVで保存",
    data=csv_bytes(df[["conference", "year", "title", "authors", "doi", "landing_url", "pdf_url", "pdf_status"]]),
    file_name="papers.csv", mime="text/csv",
)

st.divider()
back, nxt = st.columns(2)
if back.button("← 条件を変える", width="stretch"):
    go_to_step(1)
if nxt.button("次へ：PDFを取得 →", type="primary", width="stretch", disabled=len(chosen_auto) == 0):
    go_to_step(3)
