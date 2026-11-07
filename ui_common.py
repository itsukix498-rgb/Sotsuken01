"""複数のページで共通して使う表示用の部品。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from extract_urls import UrlRecord

# 「論文を検索して調べる」の各ステップのページ（app.py の st.Page と同じパス）
STEP_PAGES = {
    1: ("views/step1_search.py", "論文を検索"),
    2: ("views/step2_select.py", "論文を選ぶ"),
    3: ("views/step3_extract.py", "URLを抽出"),
    4: ("views/step4_judge.py", "AIで判定"),
}
# ステップ以外のページ
HOME_PAGE = "views/home.py"
GUIDE_PAGE = "views/guide.py"
UPLOAD_PAGE = "views/extract.py"

# 画面全体の見た目の調整（Streamlit の標準部品に CSS を当てる）
# 色は .streamlit/config.toml の primaryColor（深緑 #2E5E4E）に合わせる
_STYLE = """
<style>
:root {
  --pdf-green: #2E5E4E; --pdf-green-dark: #234A3D; --pdf-green-soft: #E8F0EC;
  --pdf-border: rgba(31, 42, 39, 0.14); --pdf-muted: rgba(31, 42, 39, 0.64);
}

/* 本文の幅：大きな画面でも横に伸びすぎないよう上限を付けて中央にそろえる */
[data-testid="stMainBlockContainer"] { max-width: 1100px; padding-left: 2rem; padding-right: 2rem; }
/* スマホ：左右の余白を小さくし、見出しを少し小さくする */
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding-left: 1rem; padding-right: 1rem; padding-top: 3.5rem; }
  h1 { font-size: 1.75rem !important; }
}
/* 説明の表（使い方・対応状況など）：画面より広いときは、ページ全体ではなく表の中だけ横にスクロールする */
[data-testid="stMarkdownContainer"] table { display: block; max-width: 100%; overflow-x: auto; }
/* 1列目の短い見出しは折り返さない（スマホで1文字ずつ改行されないように） */
[data-testid="stMarkdownContainer"] table th:first-child,
[data-testid="stMarkdownContainer"] table td:first-child { white-space: nowrap; }
/* ボタンは指で押しやすい高さにする */
.stButton button, .stDownloadButton button, .stFormSubmitButton button, .stPageLink a { min-height: 2.75rem; }

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
.pdf-step.done { color: var(--pdf-green); border-color: rgba(46, 94, 78, 0.35); }
.pdf-step.done b { background: var(--pdf-green-soft); }
.pdf-step.current { color: #fff; background: var(--pdf-green); border-color: var(--pdf-green); font-weight: 600; }
.pdf-step.current b { background: rgba(255, 255, 255, 0.22); }
@media (max-width: 640px) {
  .pdf-steps { gap: 0.3rem; }
  .pdf-step { flex-direction: column; text-align: center; gap: 0.25rem; padding: 0.45rem 0.15rem; font-size: 0.72rem; }
}

/* 大きな見出し（合言葉のページ・ホーム） */
.pdf-hero { padding: 0.5rem 0 1rem; }
.pdf-hero .pdf-kicker { color: var(--pdf-green); font-weight: 600; font-size: 0.9rem; margin: 0; }
.pdf-hero .pdf-name { font-size: clamp(2rem, 6vw, 3rem); font-weight: 700; line-height: 1.15; margin: 0.3rem 0 0.6rem; }
.pdf-hero .pdf-lead { font-size: clamp(1rem, 2.6vw, 1.2rem); color: var(--pdf-muted); margin: 0; line-height: 1.6; }

/* できることの流れ（1 → 4） */
.pdf-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.5rem; margin: 0.5rem 0 1rem; }
.pdf-flow div { border: 1px solid var(--pdf-border); border-radius: 0.6rem; padding: 0.6rem 0.75rem; font-size: 0.92rem; line-height: 1.4; }
.pdf-flow b { display: block; color: var(--pdf-green); font-size: 0.78rem; margin-bottom: 0.15rem; }
.pdf-flow div.pdf-strong { background: var(--pdf-green-soft); border-color: rgba(46, 94, 78, 0.35); }
@media (max-width: 640px) { .pdf-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* カード（ホームの入口・STEP 4 への案内）。st.container(key=...) に付く st-key-○○ のクラスで見た目を付ける */
[class*="st-key-pdf_card"] {
  border: 1px solid var(--pdf-border); border-radius: 0.8rem; padding: 1.1rem 1.1rem 1rem; height: 100%;
}
/* 横に並んだカードの高さをそろえ、ボタンをカードの下端に置く */
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-pdf_card"]) { height: 100%; }
[class*="st-key-pdf_card"] > div:last-child { margin-top: auto; }
[class*="st-key-pdf_card_main"], .st-key-pdf_cta {
  background: var(--pdf-green-soft); border-color: rgba(46, 94, 78, 0.35);
}
.st-key-pdf_cta { border: 1px solid rgba(46, 94, 78, 0.35); border-radius: 0.8rem; padding: 1.2rem; margin: 1rem 0; }
</style>
"""


def apply_style() -> None:
    """全ページ共通のCSSを読み込む（app.py から毎回呼ぶ）。

    st.html に <style> だけを渡すと再実行やページ移動で消えることがあるため、st.markdown で埋め込む。
    """
    st.markdown(_STYLE, unsafe_allow_html=True)


def hero(kicker: str, name: str, lead: str) -> None:
    """ページ上部の大きな見出し（小さな見出し・アプリ名・説明の一文）。"""
    st.html(f'<div class="pdf-hero"><p class="pdf-kicker">{kicker}</p>'
            f'<p class="pdf-name">{name}</p><p class="pdf-lead">{lead}</p></div>')


# このアプリでできることの流れ（合言葉のページ・ホーム・使い方で共通）
FLOW = [
    ("1", "論文を集める", "会議と年を選んで一覧にする"),
    ("2", "論文を選ぶ", "調べたい論文にチェック"),
    ("3", "URLを抜き出す", "本文から公開先の手がかりを探す"),
    ("4", "AIで判定", "使えるデータセットを見つける"),
]


def flow() -> None:
    """「1 論文を集める → … → 4 AIで判定」の流れを表示する（4 はこのアプリの強みなので目立たせる）。"""
    items = "".join(
        f'<div class="{"pdf-strong" if n == "4" else ""}"><b>{n}</b>{title}<br>'
        f'<span style="color: var(--pdf-muted); font-size: 0.82rem;">{desc}</span></div>'
        for n, title, desc in FLOW)
    st.html(f'<div class="pdf-flow">{items}</div>')


def step_header(current: int) -> None:
    """「1 論文を検索 → 2 論文を選ぶ → 3 URLを抽出 → 4 AIで判定」の進み具合を表示する。"""
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
