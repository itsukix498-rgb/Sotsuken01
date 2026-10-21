"""複数のページで共通して使う表示用の部品。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from extract_urls import UrlRecord

# 「論文を集める」の各ステップのページ（app.py の st.Page と同じパス）
STEP_PAGES = {
    1: ("views/step1_search.py", "論文を検索"),
    2: ("views/step2_select.py", "論文を選ぶ"),
    3: ("views/step3_extract.py", "URLを抽出"),
}

# 画面全体の見た目の調整（Streamlit の標準部品に CSS を当てる）
_STYLE = """
<style>
/* 選択ボタン（st.pills）が画面幅に収まらないとき、横にはみ出さず次の行に折り返す */
[data-testid="stButtonGroup"] > div { flex-wrap: wrap; row-gap: 0.5rem; }

/* 左上のサイドバー開閉ボタンを、ハンバーガー（☰）と閉じる（×）のアイコンにする。
   アイコンは Material Symbols のフォントで描かれているので、表示する文字（アイコン名）だけ差し替える */
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"],
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"] { font-size: 0 !important; }
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::after { content: "menu"; font-size: 1.9rem; }
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"]::after { content: "close"; font-size: 1.6rem; }
[data-testid="stSidebarCollapseButton"] { visibility: visible !important; }

/* ステップの進み具合の表示 */
.pdf-steps { display: flex; gap: 0.5rem; margin: 0 0 1rem; }
.pdf-step {
  flex: 1; display: flex; align-items: center; gap: 0.5rem; padding: 0.55rem 0.75rem;
  border-radius: 0.6rem; border: 1px solid rgba(49, 51, 63, 0.15); color: rgba(49, 51, 63, 0.55);
  font-size: 0.9rem; line-height: 1.3; min-width: 0;
}
.pdf-step b { flex: none; display: inline-flex; align-items: center; justify-content: center;
  width: 1.6rem; height: 1.6rem; border-radius: 50%; background: rgba(49, 51, 63, 0.08); font-size: 0.85rem; }
.pdf-step.done { color: #1d4ed8; border-color: rgba(37, 99, 235, 0.35); }
.pdf-step.done b { background: rgba(37, 99, 235, 0.12); }
.pdf-step.current { color: #fff; background: #2563eb; border-color: #2563eb; font-weight: 600; }
.pdf-step.current b { background: rgba(255, 255, 255, 0.25); }
@media (max-width: 640px) {
  .pdf-step { flex-direction: column; text-align: center; gap: 0.25rem; padding: 0.5rem 0.25rem; font-size: 0.78rem; }
}
</style>
"""


def apply_style() -> None:
    """全ページ共通のCSSを読み込む（app.py から毎回呼ぶ）。

    st.html に <style> だけを渡すと再実行やページ移動で消えることがあるため、st.markdown で埋め込む。
    """
    st.markdown(_STYLE, unsafe_allow_html=True)


def step_header(current: int) -> None:
    """「1 論文を検索 → 2 論文を選ぶ → 3 URLを抽出」の進み具合を表示する。"""
    items = []
    for n, (_, label) in STEP_PAGES.items():
        state = "done" if n < current else "current" if n == current else ""
        mark = "✓" if n < current else str(n)
        items.append(f'<div class="pdf-step {state}"><b>{mark}</b><span>{label}</span></div>')
    st.html(f'<div class="pdf-steps">{"".join(items)}</div>')


def go_to_step(n: int) -> None:
    """指定したステップのページへ移動する。"""
    st.switch_page(STEP_PAGES[n][0])

SOURCE_LABELS = {
    "text": "本文テキスト",
    "annotation": "リンク注釈",
    "text+annotation": "本文＋リンク注釈",
}


def link_for(url: str) -> str:
    """スキームなしURL（github.com/... など）もクリックで開けるよう https:// を補う。"""
    return url if "://" in url else f"https://{url}"


def url_rows(records: list[UrlRecord], **extra) -> list[dict]:
    """URLの抽出結果を表の行にする。extra には論文名などの列を渡す。"""
    return [
        {**extra, "page": r.page, "url": r.url, "source": r.source, "link": link_for(r.url)}
        for r in records
    ]


def show_url_table(rows: list[dict], key: str, label_column: str | None = None) -> None:
    """URL一覧を、絞り込み欄つきの表で表示する。"""
    if not rows:
        st.info("URLは見つかりませんでした。")
        return
    df = pd.DataFrame(rows)
    df["source_label"] = df["source"].map(SOURCE_LABELS).fillna(df["source"])

    col_filter, col_search = st.columns([2, 3])
    sources = list(SOURCE_LABELS.values())
    # 検索条件と同じボタン形式（pills）で選ぶ。何も選ばれていなければ全部表示する
    selected = col_filter.pills("取得元", sources, selection_mode="multi", default=sources, key=f"{key}_src")
    keyword = col_search.text_input("URLで絞り込み", placeholder="例: github, zenodo, osf, kaggle", key=f"{key}_kw")

    view = df[df["source_label"].isin(selected or sources)]
    if keyword:
        view = view[view["url"].str.contains(keyword, case=False, regex=False)]

    # 一番大事なURLを先頭に置く（スマホなど幅の狭い画面でも見えるように）
    columns = ["url", "link"] + ([label_column] if label_column else []) + ["page", "source_label"]
    label_names = {"title": "論文", "file": "ファイル"}
    st.dataframe(
        view[columns],
        hide_index=True,
        width="stretch",
        column_config={
            label_column or "_": st.column_config.TextColumn(label_names.get(label_column, "論文"), width="medium"),
            "page": st.column_config.NumberColumn("ページ", width="small"),
            "url": st.column_config.TextColumn("URL", width="large", help="セルにマウスを乗せると全文が見えます"),
            "source_label": st.column_config.TextColumn("取得元", width="small"),
            "link": st.column_config.LinkColumn("開く", display_text="開く ↗", width="small"),
        },
    )
    st.caption(f"{len(view)} / {len(df)} 件を表示")


def csv_bytes(df: pd.DataFrame) -> bytes:
    """Excelで文字化けしないよう BOM 付き UTF-8 のCSVにする。"""
    return df.to_csv(index=False).encode("utf-8-sig")
