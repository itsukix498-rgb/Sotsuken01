"""段階4の準備：「データを公開していない論文」を集めて、本文を取得する。

先生のデータセットには、データを公開している論文（Selected papers）と対象外の論文（Excluded papers）しか
1本ずつは載っていない。公開していない論文がないと「公開しているか」を見分けられるかを測れないため、
アプリの論文収集の仕組みで会議・年ごとの全論文を集め、先生のシートに載っていない論文を
「公開していない論文」とみなして加える。

使い方
    python scripts/collect_negatives.py            # 会議・年ごとに最大10本（本文が取れたもの）
    python scripts/collect_negatives.py --per-group 5

出力
    data/negatives_status.csv … data/papers_status.csv と同じ列（role は "negative"）
    画面 … 会議・年ごとの、集めた論文の数（先生の集計との比較）と、本文が取れた数

注意
    ・EDM 2020〜2022年は、論文一覧を取る手段がない（Zenodo にない）ので含められない
    ・会議の一覧には、先生の集計に入っていない発表（ポスターなど）が混ざることがある
    ・外部に送るのは DOI・タイトル（Semantic Scholar・Crossref・OpenAlex）と、論文PDFのダウンロードだけ
"""

from __future__ import annotations

import argparse
import random
import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from collect_papers import collect_papers  # noqa: E402
from research.fulltext import SOURCE_NONE, get_fulltext  # noqa: E402
from research.semantic_scholar import SemanticScholarClient  # noqa: E402
from research.teacher_dataset import SheetMap, load_papers  # noqa: E402
from scripts.build_papers_status import extra_pdf_candidates, load_env  # noqa: E402

# 調べる会議と年（EDM は Zenodo に一覧がある 2023 年以降だけ）
GROUPS = [(v, y) for v in ("LAK", "AIED") for y in range(2020, 2025)] + [("EDM", 2023), ("EDM", 2024)]
SEED = 42
MAX_ATTEMPTS = 40  # 会議・年ごとに、本文の取得を試す論文の上限（相手のサーバーに負担をかけないため）


def title_key(title: str) -> str:
    """タイトルの表記の違い（大文字小文字・記号・空白）を無視して比べるための文字列。"""
    return re.sub(r"[^a-z0-9]", "", (title or "").lower())


def is_edm_main_paper(pdf_url: str) -> bool:
    """EDM の Zenodo のファイル名（例: 2024.EDM-long-papers.16.pdf）から、フル論文・ショート論文かを判断する。"""
    name = (pdf_url or "").lower()
    return any(k in name for k in ("long-paper", "short-paper", "full-paper", "long_paper", "short_paper"))


def teacher_keys(xlsx: Path) -> tuple[set[str], set[str]]:
    """先生のシートに載っている論文（データあり・対象外・あとで除外）のDOIとタイトル。これらは集めない。"""
    maps = [SheetMap(sheet=s, role=s, header_row=2, data_start_row=4,
                     columns={"title": "Paper title", "paper_url": "Paper URL (or DOI link if it exists)"})
            for s in ("Selected papers", "Excluded papers", "Archive Additionally eliminated")]
    papers = load_papers(xlsx, maps)
    return {p.doi for p in papers if p.doi}, {title_key(p.title) for p in papers}


def teacher_totals(xlsx: Path) -> dict[tuple[str, int], int]:
    """先生の集計（Overall counts）の、会議・年ごとの論文数（フル＋ショート）。"""
    df = pd.read_excel(xlsx, sheet_name="Overall counts", header=None, dtype=str).iloc[2:]
    df = df[df[1].isin(["LAK", "EDM", "AIED"])]
    df[3] = pd.to_numeric(df[3], errors="coerce")
    df[2] = pd.to_numeric(df[2], errors="coerce")
    return {(v, int(y)): int(n) for (v, y), n in df.groupby([1, 2])[3].sum().items()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="データを公開していない論文を集めて本文を取得する")
    parser.add_argument("--dataset", default=str(ROOT / "data" / "teacher_dataset.xlsx"))
    parser.add_argument("--per-group", type=int, default=10, help="会議・年ごとに集める本数（本文が取れたもの）")
    parser.add_argument("--output", default=str(ROOT / "data" / "negatives_status.csv"))
    args = parser.parse_args(argv)

    load_env()
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    xlsx = Path(args.dataset)
    known_dois, known_titles = teacher_keys(xlsx)
    totals = teacher_totals(xlsx)
    client = SemanticScholarClient(cache_dir=ROOT / "data" / "cache" / "semantic_scholar")
    rng = random.Random(SEED)

    rows = []
    for venue, year in GROUPS:
        papers, notes = collect_papers([venue], [year])
        for n in notes:
            print(f"  注意: {n}")
        if venue == "EDM":
            # Zenodo の EDM のコミュニティには、ポスターや博士課程の発表なども入っている。
            # 先生の集計（フル論文・ショート論文）にそろえるため、ファイル名で long／short／full の論文だけにする
            papers = [p for p in papers if is_edm_main_paper(p.pdf_url)]
        candidates = [p for p in papers if p.doi.lower() not in known_dois and title_key(p.title) not in known_titles]
        print(f"\n{venue} {year}: 一覧 {len(papers)} 本（先生の集計 {totals.get((venue, year), '?')} 本）、"
              f"先生のシートにない論文 {len(candidates)} 本")
        rng.shuffle(candidates)
        candidates = candidates[:MAX_ATTEMPTS]

        # Semantic Scholar で論文を特定する（DOI でまとめて問い合わせ）
        by_doi = client.get_papers([f"DOI:{p.doi}" for p in candidates if p.doi])
        got = 0
        for i, p in enumerate(candidates):
            if got >= args.per_group:
                break
            s2 = by_doi.get(f"DOI:{p.doi}") if p.doi else None
            extra = []
            if p.pdf_url:
                extra.append(("論文一覧", p.pdf_url))  # Zenodo などのPDF（EDM）
            extra += extra_pdf_candidates(_AsTeacher(p), s2)
            ft = get_fulltext(s2, extra, cache_dir=ROOT / "data" / "cache" / "text")
            if ft.source != SOURCE_NONE:
                got += 1
            rows.append({
                "row_id": f"negative:{venue}:{year}:{i + 1}", "role": "negative", "title": p.title, "doi": p.doi,
                "venue": venue, "year": year, "s2_paper_id": (s2 or {}).get("paperId", ""),
                "s2_corpus_id": (s2 or {}).get("corpusId", ""), "found_by": "DOI" if s2 else "",
                "s2_title": (s2 or {}).get("title", ""), "fulltext_source": ft.source, "pdf_from": ft.pdf_from,
                "reason": ft.reason, "pdf_url": ft.pdf_url, "s2orc_available": ft.s2orc_available,
                "pages": ft.pages, "chars": len(ft.text),
            })
        print(f"  本文を取得できた: {got} 本（{min(len(candidates), i + 1) if candidates else 0} 本を試した）")

    df = pd.DataFrame(rows)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    ok = df[df["fulltext_source"] != SOURCE_NONE]
    print(f"\n保存しました: {args.output}")
    print(f"公開していない論文（本文あり）: {len(ok)} 本")
    print(ok.groupby(["venue", "year"]).size().to_string())
    return 0


class _AsTeacher:
    """extra_pdf_candidates に渡すための形（doi と paper_url を持つ）。"""

    def __init__(self, paper):
        self.doi = (paper.doi or "").lower()
        self.paper_url = paper.landing_url


if __name__ == "__main__":
    sys.exit(main())
