"""AIが示した「根拠の文」が、論文の本文に本当にあるかを確かめる（先生の指摘「根拠はどう判断されているか」への対応）。

LLMは呼ばず、すでに判定した答え（data/cache/llm/ のキャッシュ）だけを使う。Gemini の回数は使わない。

使い方
    # 調整用（初期値）を、v3 の答えで確かめる
    python scripts/check_evidence.py --prompt judge_v3

    # 評価用は、最終評価のときだけ
    python scripts/check_evidence.py --prompt judge_v3 --split test --final

確かめること（根拠の文ごと。論文の根拠と、データセットごとの根拠の両方）
    ・本文にあるか：一致（同じ文がある）／ほぼ一致（よく似た文がある）／見つからない（AIが作った可能性）
    ・あったページ
    ・AIに渡した抜粋（URLの前後の文・データについての文）の中にあるか

出力（results/ は GitHub に上げない）
    results/evidence_check_<プロンプトの版>_<調整用|評価用>_<日付>.csv … 根拠の文ごとの結果（手元で開いて確かめる）
    画面には、件数と割合だけを表示する（論文名や根拠の文は表示しない）
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.evidence import EMPTY, MATCH, NEAR, NOT_FOUND, check_evidence, normalize  # noqa: E402
from research.fulltext import load_cached  # noqa: E402
from research.judge import STATUS_OK, Judge, load_prompt  # noqa: E402
from research.llm import get_provider  # noqa: E402
from research.llm_input import build_llm_input  # noqa: E402
from research.paper_urls import extract_from_pages  # noqa: E402
from research.pipeline import DATA, select_targets  # noqa: E402
from research.split import DEV, TEST  # noqa: E402
from scripts.run_llm_judge import load_env  # noqa: E402

STATUSES = (MATCH, NEAR, NOT_FOUND)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AIが示した根拠の文が、論文の本文にあるかを確かめる")
    parser.add_argument("--provider", default="gemini", choices=["gemini", "ollama"])
    parser.add_argument("--model", default="gemini-3.5-flash-lite")
    parser.add_argument("--prompt", default="judge_v3")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--final", action="store_true", help="評価用（最終評価）を使ってよいときだけ付ける")
    args = parser.parse_args(argv)
    if args.split == "test" and not args.final:
        parser.error("評価用の論文は、最終評価のときだけ使います。--final を付けてください")

    load_env()
    judge = Judge(get_provider(args.provider, args.model), load_prompt(args.prompt),
                  cache_dir=DATA / "cache" / "llm", cache_only=True)
    rows, not_judged = [], 0
    for _, p in select_targets(args.split).iterrows():
        cached = load_cached(p["pdf_url"], DATA / "cache" / "text")
        if cached is None:
            continue
        pages, links = cached
        item = build_llm_input(p["title"], pages, extract_from_pages(pages, links))
        j = judge.judge(item)  # cache_only なので LLM は呼ばない
        if j.status != STATUS_OK:
            not_judged += 1
            continue
        excerpts = normalize(item.render_urls() + "\n" + item.render_data_sentences())
        evidences = [("論文", j.answer["paper"]["shares_dataset"], j.answer["paper"].get("evidence", ""))]
        evidences += [("データセット", d.get("name", ""), d.get("evidence", "")) for d in j.answer.get("datasets") or []]
        for level, what, evidence in evidences:
            c = check_evidence(evidence, pages)
            rows.append({"row_id": p["row_id"], "venue": p["venue"], "year": int(p["year"]), "title": p["title"],
                         "level": level, "answer": what, "evidence": evidence, "status": c.status, "page": c.page,
                         "in_excerpts": bool(evidence) and normalize(evidence) in excerpts})

    df = pd.DataFrame(rows)
    split_label = DEV if args.split == "dev" else TEST
    out = ROOT / "results" / f"evidence_check_{args.prompt}_{split_label}_{datetime.now():%Y%m%d}.csv"
    out.parent.mkdir(exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    print(f"{args.prompt} / {split_label}：判定済みの論文 {df['row_id'].nunique()} 本（判定不能・未処理 {not_judged} 本は除く）")
    for level in ("論文", "データセット"):
        part = df[(df["level"] == level) & (df["status"] != EMPTY)]
        counts = Counter(part["status"])
        total = len(part)
        if not total:
            continue
        detail = "、".join(f"{s} {counts.get(s, 0)}件（{counts.get(s, 0) / total:.0%}）" for s in STATUSES)
        print(f"  {level}の根拠 {total}件：{detail}")
        print(f"    そのうち、AIに渡した抜粋の中にそのままあったもの：{int(part['in_excerpts'].sum())}件")
    empty = int((df["status"] == EMPTY).sum())
    if empty:
        print(f"  根拠が空（または短すぎる）もの：{empty}件")
    by_answer = df[(df["level"] == "論文") & (df["status"] != EMPTY)].groupby("answer")["status"].value_counts()
    print("  論文の根拠を、AIの答え（yes/no/unknown）ごとに：")
    for (answer, status), n in by_answer.items():
        print(f"    {answer}：{status} {n}件")
    print(f"保存しました：{out.relative_to(ROOT)}（論文名と根拠の文を含むので、手元で開いて確かめてください）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
