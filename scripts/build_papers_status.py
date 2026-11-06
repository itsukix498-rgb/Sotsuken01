"""先生のデータセットの論文について、Semantic Scholar で論文を特定し、本文を取得して状況をまとめる。

使い方
    # 1. 列の構成を確認する（先頭の数行を表示するだけ。外部には何も送らない）
    python scripts/build_papers_status.py --describe data/<先生のファイル>.xlsx

    # 2. data/column_map.json を書いたら、少数で試す
    python scripts/build_papers_status.py data/<先生のファイル>.xlsx --limit 10

    # 3. 全件
    python scripts/build_papers_status.py data/<先生のファイル>.xlsx

出力
    data/papers_status.csv … 論文ごとの結果（論文ID・タイトル・DOI・paperId・本文の取得元・取得できなかった理由など）
    画面 … 本文を取得できた論文の数と割合（会議別・年別）

外部に送るもの
    Semantic Scholar には DOI とタイトルだけを送る。先生のデータの判定結果などは送らない。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.fulltext import SOURCE_NONE, get_fulltext  # noqa: E402
from research.openalex import oa_pdf_urls  # noqa: E402
from research.semantic_scholar import SemanticScholarClient, SemanticScholarError  # noqa: E402
from research.teacher_dataset import describe_file, load_column_map, load_papers  # noqa: E402

# タイトル検索の結果を同じ論文とみなす一致度の下限（これ未満は「見つからない」扱い）
MIN_MATCH_SCORE = 0.8


def load_env() -> None:
    """.env があれば読み込む（python-dotenv がなければ何もしない）。"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


# 先生のシートの論文URLのうち、論文のPDFそのもの（または公開の論文集）として使えるもの
PDF_LIKE_HOSTS = ("educationaldatamining.org", "zenodo.org", "arxiv.org")


def teacher_pdf_url(paper_url: str) -> str:
    """先生のシートのURLが、そのままPDFとして取れそうなら返す（出版社の紹介ページは使わない）。"""
    url = (paper_url or "").strip()
    host = url.split("//", 1)[-1].split("/", 1)[0].lower()
    if url.lower().endswith(".pdf") or any(host.endswith(h) for h in PDF_LIKE_HOSTS):
        return url
    return ""


def extra_pdf_candidates(p, s2: dict | None) -> list[tuple[str, str]]:
    """Semantic Scholar 以外のPDFの候補（OpenAlex、先生のシートのURL）。"""
    doi = p.doi or ((s2 or {}).get("externalIds") or {}).get("DOI", "").lower()
    extra = [("OpenAlex", u) for u in oa_pdf_urls(doi, cache_dir=ROOT / "data" / "cache" / "openalex")]
    if teacher_pdf_url(p.paper_url):
        extra.append(("先生のシート", teacher_pdf_url(p.paper_url)))
    return extra


def pick_per_venue(papers, n: int) -> list:
    """会議ごとに、年がばらけるよう等間隔に n 本ずつ選ぶ（毎回同じ論文が選ばれる）。"""
    picked = []
    for venue in sorted({p.venue for p in papers}):
        group = [p for p in papers if p.venue == venue]
        step = max(len(group) // n, 1)
        picked += group[::step][:n]
    return picked


def resolve_papers(papers, client: SemanticScholarClient, log=print) -> list[tuple]:
    """各論文を Semantic Scholar で特定する。DOIでまとめて問い合わせ、見つからなければタイトルで探す。"""
    by_doi = client.get_papers([p.s2_id for p in papers if p.s2_id])
    resolved = []
    for i, p in enumerate(papers, start=1):
        s2, how = (by_doi.get(p.s2_id), "DOI") if p.s2_id else (None, "")
        if s2 is None and p.title:
            match = client.match_title(p.title)
            if match and (match.get("matchScore") or 0) >= MIN_MATCH_SCORE:
                s2, how = match, "タイトル"
            elif match:
                how = f"タイトル（一致度 {match.get('matchScore', 0):.2f} で不採用）"
        resolved.append((p, s2, how))
        if i % 50 == 0:
            log(f"  論文の特定: {i}/{len(papers)}")
    return resolved


def summarize(df: pd.DataFrame) -> str:
    """本文を取得できた論文の数と割合を、会議別・年別にまとめる。"""
    df = df.assign(got=df["fulltext_source"] != SOURCE_NONE)
    lines = [f"全体: {int(df['got'].sum())} / {len(df)} 本（{df['got'].mean():.0%}）"]
    for col, label in (("venue", "会議別"), ("year", "年別")):
        g = df.groupby(col, dropna=False)["got"].agg(["sum", "count"])
        lines.append(f"\n{label}")
        for key, row in g.iterrows():
            lines.append(f"  {key}: {int(row['sum'])} / {int(row['count'])} 本（{row['sum'] / row['count']:.0%}）")
    reasons = df.loc[~df["got"], "reason"].value_counts()
    if len(reasons):
        lines.append("\n取得できなかった理由")
        for reason, n in reasons.items():
            lines.append(f"  {n} 本: {reason}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="先生のデータセットの論文の本文を取得し、状況をCSVにまとめる")
    parser.add_argument("dataset", help="先生のデータセット（data/ の中の Excel / CSV）")
    parser.add_argument("--describe", action="store_true", help="列の構成（先頭の数行）を表示するだけ")
    parser.add_argument("--map", default=str(ROOT / "data" / "column_map.json"), help="列の対応のファイル")
    parser.add_argument("--limit", type=int, default=0, help="先頭から何本だけ処理するか（試すとき用）")
    parser.add_argument("--per-venue", type=int, default=0,
                        help="会議ごとに何本ずつ処理するか（試すとき用。会議が偏らないように選ぶ）")
    parser.add_argument("--output", default=str(ROOT / "data" / "papers_status.csv"))
    args = parser.parse_args(argv)

    if args.describe:
        print(describe_file(args.dataset))
        return 0

    load_env()
    # 壊れ気味のPDFで出る MuPDF の細かい警告は、結果に影響しないので表示しない
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    client = SemanticScholarClient(cache_dir=ROOT / "data" / "cache" / "semantic_scholar")
    if not client.api_key:
        print("注意: SEMANTIC_SCHOLAR_API_KEY が設定されていません（.env）。キーなしは混雑で失敗しやすいです。")

    papers = load_papers(args.dataset, load_column_map(args.map))
    if args.per_venue:
        papers = pick_per_venue(papers, args.per_venue)
    if args.limit:
        papers = papers[:args.limit]
    print(f"論文 {len(papers)} 本を処理します（DOIあり {sum(bool(p.doi) for p in papers)} 本）")

    try:
        resolved = resolve_papers(papers, client)
    except SemanticScholarError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1

    rows = []
    for i, (p, s2, how) in enumerate(resolved, start=1):
        ft = get_fulltext(s2, extra_pdf_candidates(p, s2), cache_dir=ROOT / "data" / "cache" / "text")
        rows.append({
            "row_id": p.row_id, "role": p.role, "title": p.title, "doi": p.doi, "venue": p.venue, "year": p.year,
            "s2_paper_id": (s2 or {}).get("paperId", ""), "s2_corpus_id": (s2 or {}).get("corpusId", ""),
            "found_by": how, "s2_title": (s2 or {}).get("title", ""),
            "fulltext_source": ft.source, "pdf_from": ft.pdf_from, "reason": ft.reason, "pdf_url": ft.pdf_url,
            "s2orc_available": ft.s2orc_available, "pages": ft.pages, "chars": len(ft.text),
        })
        print(f"  ({i}/{len(resolved)}) {ft.source:4} {p.title[:60]}" + (f"  … {ft.reason}" if ft.reason else ""))

    df = pd.DataFrame(rows)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output, index=False, encoding="utf-8-sig")
    print(f"\n保存しました: {args.output}（Semantic Scholar へのリクエスト {client.requests_sent} 回）\n")
    print(summarize(df))
    return 0


if __name__ == "__main__":
    sys.exit(main())
