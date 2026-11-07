"""段階2：本文を取得できた論文から、URLを抽出して一覧にする。

使い方（先に scripts/build_papers_status.py を実行して、本文を data/cache/text/ に保存しておく）
    python scripts/extract_paper_urls.py

入力 … data/papers_status.csv（本文を取得できた論文）と、保存した本文・ハイパーリンク
出力 … data/paper_urls.csv（論文ごとのURL：ページ番号・URL・取得元）と、画面の集計

先生のデータセットの答え（データの公開の有無・公開先のURLなど）はここでは使わない。外部にも何も送らない。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.fulltext import SOURCE_NONE, load_cached  # noqa: E402
from research.paper_urls import extract_from_pages  # noqa: E402


def host_of(url: str) -> str:
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    return host.removeprefix("www.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本文を取得できた論文からURLを抽出する")
    parser.add_argument("--status", default=str(ROOT / "data" / "papers_status.csv"))
    parser.add_argument("--output", default=str(ROOT / "data" / "paper_urls.csv"))
    args = parser.parse_args(argv)

    status = pd.read_csv(args.status)
    targets = status[status["fulltext_source"] != SOURCE_NONE]
    print(f"本文を取得できた論文: {len(targets)} 本")

    rows, per_paper, missing = [], [], []
    for _, p in targets.iterrows():
        cached = load_cached(p["pdf_url"], ROOT / "data" / "cache" / "text")
        if cached is None:
            missing.append(p["title"])
            continue
        pages, links = cached
        records = extract_from_pages(pages, links)
        per_paper.append({"venue": p["venue"], "urls": len(records)})
        for r in records:
            rows.append({"row_id": p["row_id"], "role": p["role"], "venue": p["venue"], "year": p["year"],
                         "title": p["title"], "page": r.page, "url": r.url, "source": r.source})

    if missing:
        print(f"注意: 本文かハイパーリンクが保存されていない論文が {len(missing)} 本あります。"
              "scripts/build_papers_status.py をもう一度実行してください。")

    df = pd.DataFrame(rows, columns=["row_id", "role", "venue", "year", "title", "page", "url", "source"])
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"保存しました: {args.output}\n")

    pp = pd.DataFrame(per_paper)
    if pp.empty:
        print("URLを抽出できる論文がありませんでした。")
        return 1
    print(f"URLを抽出した論文: {len(pp)} 本、URL {len(df)} 件（1本あたり平均 {pp['urls'].mean():.1f} 件）")
    print(f"URLが1件もない論文: {int((pp['urls'] == 0).sum())} 本")
    print("\n会議別（本数・URL数・1本あたり）")
    for venue, g in pp.groupby("venue"):
        print(f"  {venue}: {len(g)} 本、{int(g['urls'].sum())} 件、平均 {g['urls'].mean():.1f} 件")
    print("\n取得元（本文テキスト／リンク注釈）")
    for source, n in df["source"].value_counts().items():
        print(f"  {source}: {n} 件")
    print("\nよく出てくるサイト（上位15）")
    for host, n in Counter(df["url"].map(host_of)).most_common(15):
        print(f"  {n:4} 件  {host}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
