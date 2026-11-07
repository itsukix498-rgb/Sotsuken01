"""判定（段階3）と評価（段階4）で共通して使う処理。

    ・本文を取得できた論文を集める（先生のシートの論文 data/papers_status.csv と、
      集めた「公開していない論文」data/negatives_status.csv）
    ・調整用／評価用の分け方（data/split.csv）を読む。なければ作って保存する
    ・論文ごとに、LLMに渡す材料と、段階2で抽出したURLを用意する
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from research.fulltext import SOURCE_NONE, load_cached
from research.llm_input import LlmInput, build_llm_input
from research.paper_urls import extract_from_pages
from research.split import DEV, TEST, split_papers

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATUS_FILES = (DATA / "papers_status.csv", DATA / "negatives_status.csv")
SPLIT_FILE = DATA / "split.csv"
SPLITS = {"dev": DEV, "test": TEST}


def load_statuses(files=STATUS_FILES) -> pd.DataFrame:
    """本文を取得できた論文の一覧（先生のシートの論文＋集めた公開していない論文）。"""
    frames = [pd.read_csv(f) for f in files if Path(f).exists()]
    df = pd.concat(frames, ignore_index=True)
    df = df[df["fulltext_source"] != SOURCE_NONE].copy()
    df["group"] = df["role"].map(lambda r: "negative" if r == "negative" else "teacher")
    df["year"] = df["year"].astype(int)
    return df.reset_index(drop=True)


def load_or_create_split(statuses: pd.DataFrame, path: Path = SPLIT_FILE, recreate: bool = False) -> pd.DataFrame:
    """調整用／評価用の分け方を読む。ファイルがなければ作って保存する。

    分け方は一度決めたら変えない（変えると、評価用の論文を見てしまう可能性があるため）。
    論文が増えた場合は、新しい論文だけを同じ方法で分けて付け足す。
    """
    if path.exists() and not recreate:
        split = pd.read_csv(path)
        new = statuses[~statuses["row_id"].isin(split["row_id"])]
        if not new.empty:
            added = split_papers(new[["row_id", "venue", "year", "group"]])
            split = pd.concat([split, added], ignore_index=True)
            split.to_csv(path, index=False, encoding="utf-8-sig")
        return split
    split = split_papers(statuses[["row_id", "venue", "year", "group"]])
    path.parent.mkdir(parents=True, exist_ok=True)
    split.to_csv(path, index=False, encoding="utf-8-sig")
    return split


def select_targets(split_name: str | None = None, years: tuple[int, int] | None = None) -> pd.DataFrame:
    """判定・評価の対象の論文。split_name は "dev"（調整用）/ "test"（評価用）/ None（すべて）。"""
    statuses = load_statuses()
    split = load_or_create_split(statuses)
    df = statuses.merge(split[["row_id", "split"]], on="row_id", how="left")
    if split_name:
        df = df[df["split"] == SPLITS[split_name]]
    if years:
        df = df[(df["year"] >= years[0]) & (df["year"] <= years[1])]
    return df.reset_index(drop=True)


def build_items(targets: pd.DataFrame, log=print) -> list[tuple[pd.Series, LlmInput, list[str]]]:
    """論文ごとに (論文の行, LLMに渡す材料, 段階2で抽出したURL) を作る。LLMは使わない。"""
    items = []
    for _, p in targets.iterrows():
        cached = load_cached(p["pdf_url"], DATA / "cache" / "text")
        if cached is None:
            log(f"注意: 本文が保存されていません: {str(p['title'])[:60]}")
            continue
        pages, links = cached
        records = extract_from_pages(pages, links)
        items.append((p, build_llm_input(p["title"], pages, records), [r.url for r in records]))
    return items
