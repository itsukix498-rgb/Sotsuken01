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
# 色・文字・角の丸みは .streamlit/config.toml の [theme]（青緑 #1486AD、Noto Sans JP・Montserrat）に合わせる。
# 大学のサイトのような、余白の多い・四角に近い・すっきりした見た目にする
_STYLE = """
<style>
:root {
  --pdf-primary: #1486AD; --pdf-primary-dark: #0F6A89; --pdf-tint: #EEF7FB;
  --pdf-border: #D3E5EC; --pdf-muted: rgba(34, 34, 34, 0.62);
  --pdf-en: "Montserrat", "Noto Sans JP", sans-serif;
}

/* 本文の幅：大きな画面でも横に伸びすぎないよう上限を付けて中央にそろえる */
[data-testid="stMainBlockContainer"] { max-width: 1100px; padding-left: 2rem; padding-right: 2rem; }
/* スマホ：左右の余白を小さくし、見出しを少し小さくする */
@media (max-width: 640px) {
  [data-testid="stMainBlockContainer"] { padding-left: 1rem; padding-right: 1rem; padding-top: 3.5rem; }
  h1 { font-size: 1.75rem !important; }
}
/* 文字の間隔を少し広げて読みやすくする（アイコンの文字には付けない。付けるとアイコンが文字で表示されるため） */
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"], .pdf-hero, .pdf-steps, .pdf-flow { letter-spacing: 0.04em; }
[data-testid="stIconMaterial"] { letter-spacing: normal !important; }
/* 見出し：英字は Montserrat、日本語の文字は Noto Sans JP で表示する */
h1, h2, h3, h4, h5, h6 { font-family: "Montserrat", "Noto Sans JP", sans-serif !important; }

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

/* 見出しの上の小さな英語のラベル（例：STEP 1 / SEARCH） */
.pdf-eyebrow {
  display: flex; align-items: center; gap: 0.6rem; margin: 0 0 -0.4rem; color: var(--pdf-primary);
  font-family: var(--pdf-en); font-size: 0.8rem; font-weight: 500; letter-spacing: 0.18em; text-transform: uppercase;
}
.pdf-eyebrow::before { content: ""; width: 1.6rem; height: 1px; background: var(--pdf-primary); }

/* ステップの進み具合の表示 */
.pdf-steps { display: flex; gap: 0.5rem; margin: 0 0 1.25rem; }
.pdf-step {
  flex: 1; display: flex; align-items: center; gap: 0.5rem; padding: 0.55rem 0.75rem;
  border-radius: 0.25rem; border: 1px solid var(--pdf-border); color: var(--pdf-muted);
  font-size: 0.9rem; line-height: 1.3; min-width: 0;
}
.pdf-step b { flex: none; display: inline-flex; align-items: center; justify-content: center; font-family: var(--pdf-en);
  width: 1.6rem; height: 1.6rem; border-radius: 50%; background: var(--pdf-tint); font-size: 0.85rem; font-weight: 500; }
.pdf-step.done { color: var(--pdf-primary); }
.pdf-step.current { color: #fff; background: var(--pdf-primary); border-color: var(--pdf-primary); font-weight: 500; }
.pdf-step.current b { background: rgba(255, 255, 255, 0.22); }
@media (max-width: 640px) {
  .pdf-steps { gap: 0.3rem; }
  .pdf-step { flex-direction: column; text-align: center; gap: 0.25rem; padding: 0.45rem 0.15rem; font-size: 0.72rem; }
}

/* 大きな見出し（合言葉のページ・ホーム）：薄い水色の帯に、アプリ名を大きく表示する */
.pdf-hero {
  background: var(--pdf-tint); border-top: 3px solid var(--pdf-primary);
  padding: 2.4rem 2.2rem 2.2rem; margin: 0 0 1.75rem;
}
.pdf-hero .pdf-kicker { color: var(--pdf-primary); font-weight: 500; font-size: 0.9rem; margin: 0; }
.pdf-hero .pdf-name {
  font-family: var(--pdf-en); font-size: clamp(2.1rem, 6.5vw, 3.4rem); font-weight: 500;
  letter-spacing: 0.02em; line-height: 1.15; margin: 0.5rem 0 0.9rem; color: #222;
}
.pdf-hero .pdf-lead { font-size: clamp(1rem, 2.6vw, 1.15rem); color: #333; margin: 0; line-height: 1.8; }
@media (max-width: 640px) { .pdf-hero { padding: 1.6rem 1.1rem 1.5rem; } }

/* できることの流れ（1 → 4。使い方のページで使う） */
.pdf-flow { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0.5rem; margin: 0.5rem 0 1rem; }
.pdf-flow div { border: 1px solid var(--pdf-border); border-radius: 0.25rem; padding: 0.7rem 0.8rem; font-size: 0.92rem; line-height: 1.5; }
.pdf-flow b { display: block; color: var(--pdf-primary); font-family: var(--pdf-en); font-weight: 500; font-size: 0.8rem; margin-bottom: 0.15rem; }
.pdf-flow div.pdf-strong { background: var(--pdf-tint); border-color: var(--pdf-primary); }
@media (max-width: 640px) { .pdf-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

/* カード（ホームの入口・STEP 4 への案内）。st.container(key=...) に付く st-key-○○ のクラスで見た目を付ける */
[class*="st-key-pdf_card"] {
  border: 1px solid var(--pdf-border); border-top: 3px solid var(--pdf-border); border-radius: 0.25rem;
  padding: 1.3rem 1.2rem 1.1rem; height: 100%;
}
[class*="st-key-pdf_card_main"] { background: var(--pdf-tint); border-top-color: var(--pdf-primary); }
/* 横に並んだカードの高さをそろえ、ボタンをカードの下端に置く */
[data-testid="stLayoutWrapper"]:has(> [class*="st-key-pdf_card"]) { height: 100%; }
[class*="st-key-pdf_card"] > div:last-child { margin-top: auto; }
.st-key-pdf_cta {
  background: var(--pdf-tint); border: 1px solid var(--pdf-border); border-left: 4px solid var(--pdf-primary);
  border-radius: 0.25rem; padding: 1.3rem 1.3rem 1.2rem; margin: 1rem 0 1.5rem;
}

/* AIの判定の「今日あと〇本」 */
.pdf-remaining {
  display: inline-flex; align-items: baseline; gap: 0.35rem; flex-wrap: wrap; padding: 0.35rem 0.9rem;
  border: 1px solid var(--pdf-primary); border-radius: 999px; color: var(--pdf-primary); font-size: 0.88rem;
}
.pdf-remaining b { font-family: var(--pdf-en); font-size: 1.15rem; font-weight: 600; }
.pdf-remaining small { color: var(--pdf-muted); font-size: 0.75rem; }
.pdf-remaining.pdf-empty { border-color: #C03A3A; color: #C03A3A; }
</style>
"""


def apply_style() -> None:
    """全ページ共通のCSSを読み込む（app.py から毎回呼ぶ）。

    st.html に <style> だけを渡すと再実行やページ移動で消えることがあるため、st.markdown で埋め込む。
    """
    st.markdown(_STYLE, unsafe_allow_html=True)


def hero(kicker: str, name: str, lead: str) -> None:
    """ページ上部の大きな見出し（小さな見出し・アプリ名・説明の一文）。薄い水色の帯に表示する。"""
    st.html(f'<div class="pdf-hero"><p class="pdf-kicker">{kicker}</p>'
            f'<p class="pdf-name">{name}</p><p class="pdf-lead">{lead}</p></div>')


def page_title(eyebrow: str, title: str) -> None:
    """ページの見出し。上に小さな英語のラベル（例：STEP 1 / SEARCH）を付ける。"""
    st.html(f'<p class="pdf-eyebrow">{eyebrow}</p>')
    st.title(title)


# このアプリでできることの流れ（使い方のページで使う）
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


MAX_BATCH = 30  # 1回にまとめて取得するPDFの上限（相手サーバーへの負担と、公開サーバーの処理時間を考えて）


def limited_selection(rows: list[dict], indices) -> set[int]:
    """indices の論文のうち、PDFを自動取得できるものを、1回に取得できる本数まで（上から順に）選ぶ。

    J-STAGE は利用規約に配慮して1回 JSTAGE_MAX_BATCH 本まで、全体で MAX_BATCH 本まで。
    """
    from collect_papers import JSTAGE_JOURNALS, JSTAGE_MAX_BATCH, PDF_AUTO

    selected, n_jstage = set(), 0
    for i in indices:
        row = rows[i]
        if row["pdf_status"] != PDF_AUTO or len(selected) >= MAX_BATCH:
            continue
        if row["conference"] in JSTAGE_JOURNALS:
            if n_jstage >= JSTAGE_MAX_BATCH:
                continue
            n_jstage += 1
        selected.add(i)
    return selected


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
