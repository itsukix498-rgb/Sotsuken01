"""2つのページで共通して使う表示用の部品。"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from extract_urls import UrlRecord

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
    selected = col_filter.multiselect("取得元", sources, default=sources, key=f"{key}_src")
    keyword = col_search.text_input("URLで絞り込み", placeholder="例: github, zenodo, osf, kaggle", key=f"{key}_kw")

    view = df[df["source_label"].isin(selected)]
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
