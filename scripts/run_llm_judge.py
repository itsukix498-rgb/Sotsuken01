"""段階3：LLMで論文を判定する（論文ごと：データセットを共有しているか、データセットごと：P／L／O、URLごと：公開先か）。

使い方
    # LLMに渡す文章を、LLMを呼ばずに確かめる（文字数の目安も出る）
    python scripts/run_llm_judge.py --provider gemini --model <モデル名> --years 2020-2022 --preview 2

    # Gemini で使えるモデル名の一覧
    python scripts/run_llm_judge.py --provider gemini --list-models

    # 実行（調整用の 2020〜2022 年の論文だけ）
    python scripts/run_llm_judge.py --provider gemini --model <モデル名> --years 2020-2022
    python scripts/run_llm_judge.py --provider ollama --model <モデル名> --years 2020-2022

途中で止まっても（1日の上限・エラー・Ctrl+C）、同じコマンドでもう一度実行すれば、判定済みの論文はキャッシュから読み、
続きの論文だけをLLMに送る。

出力（results/ は GitHub に上げない）
    results/llm_<モデル名>_<日付>.csv           … 論文ごとの判定
    results/llm_<モデル名>_<日付>_datasets.csv  … データセットごとの判定（名前・URL・P／L／O）
    results/llm_<モデル名>_<日付>_urls.csv      … URLごとの判定（公開先か）
    results/runs.jsonl                          … 実行の記録（モデル・日付・プロンプトの版・設定・トークン数・時間）

外部のLLMに送るのは、論文の本文の一部（URLの前後とデータについて書かれた文）とURLだけ。
先生のデータセットの内容（どの論文がデータありか、P／L／O など）は送らない。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.judge import STATUS_OK, Judge, load_prompt  # noqa: E402
from research.llm import DailyLimitReached, LLMError, get_provider  # noqa: E402
from research.pipeline import build_items, select_targets  # noqa: E402

STATUS_NOT_RUN = "未処理"  # 1日の上限などで、今回は判定できなかった論文


def load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")


def parse_years(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d{4})(?:-(\d{4}))?", text)
    if not m:
        raise argparse.ArgumentTypeError("年は 2020 や 2020-2022 の形で指定してください")
    return int(m.group(1)), int(m.group(2) or m.group(1))


def safe_name(text: str) -> str:
    return re.sub(r"[^\w.-]+", "-", text).strip("-")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLMで論文を判定する（段階3）")
    parser.add_argument("--provider", required=True, choices=["gemini", "ollama"])
    parser.add_argument("--model", help="モデル名（Gemini は --list-models で確認できる）")
    parser.add_argument("--prompt", default="judge_v1", help="prompts/ のプロンプトの版（ファイル名）")
    parser.add_argument("--years", type=parse_years, help="対象の年（例: 2020-2022）。省略するとすべて")
    parser.add_argument("--limit", type=int, default=0, help="先頭から何本だけ処理するか（試すとき用）")
    parser.add_argument("--preview", type=int, default=0, help="LLMを呼ばずに、渡す文章を何本分か表示する")
    parser.add_argument("--list-models", action="store_true", help="Gemini で使えるモデル名を表示する")
    parser.add_argument("--split", choices=["dev", "test", "all"], default="dev",
                        help="dev＝調整用（初期値）、test＝評価用（--final が必要）、all＝すべて")
    parser.add_argument("--final", action="store_true", help="評価用の論文を判定してよいときだけ付ける（最終評価）")
    parser.add_argument("--repeat", type=int, default=0,
                        help="再現性を測るための何回目の判定か（0＝ふつう、1・2＝同じ設定でもう一度判定する）")
    args = parser.parse_args(argv)
    if args.split in ("test", "all") and not args.final:
        parser.error("評価用の論文は、最終評価のときだけ使います。判定してよいときは --final を付けてください")

    load_env()
    if args.list_models:
        from research.llm.gemini import GeminiProvider
        print("\n".join(GeminiProvider("-").list_models()))
        return 0
    if not args.model:
        parser.error("--model を指定してください")

    prompt = load_prompt(args.prompt)
    # 対象の論文（先生の答えの列は使わない）。初期値は調整用だけ
    targets = select_targets(None if args.split == "all" else args.split, args.years)
    if args.limit:
        targets = targets.head(args.limit)

    # 論文ごとに、LLMに渡す材料を作る（ここまではLLMを使わない）
    items = [(p, item) for p, item, _ in build_items(targets)]

    if args.preview:
        for p, item in items[:args.preview]:
            text = prompt.render_user(item)
            print("=" * 80)
            print(text)
            print(f"\n[文字数: 指示文 {len(prompt.system)} ＋ 問題文 {len(text)}"
                  f"（英語ではおよそ4文字で1トークン）、ルールで除外したURL: {len(item.excluded_urls)} 件]")
        lengths = [len(prompt.render_user(i)) for _, i in items]
        if lengths:
            print(f"\n全 {len(items)} 本：問題文の文字数 平均 {sum(lengths) / len(lengths):.0f}、最大 {max(lengths)}")
        return 0

    provider = get_provider(args.provider, args.model)
    judge = Judge(provider, prompt, cache_dir=ROOT / "data" / "cache" / "llm", repeat=args.repeat)
    started = datetime.now()
    print(f"{len(items)} 本を判定します（{args.provider} / {args.model} / プロンプト {prompt.version} / temperature 0"
          f" / {args.split}" + (f" / {args.repeat}回目の繰り返し" if args.repeat else "") + "）")

    paper_rows, dataset_rows, url_rows = [], [], []
    totals = {"input_tokens": 0, "output_tokens": 0, "seconds": 0.0, "llm_calls": 0}
    stop_reason = ""
    for n, (p, item) in enumerate(items, start=1):
        base = {"row_id": p["row_id"], "venue": p["venue"], "year": p["year"], "title": p["title"]}
        if stop_reason:
            paper_rows.append({**base, "status": STATUS_NOT_RUN})
            continue
        try:
            j = judge.judge(item)
        except DailyLimitReached as e:
            stop_reason = str(e)
            print(f"\n{e}")
            paper_rows.append({**base, "status": STATUS_NOT_RUN})
            continue
        except LLMError as e:
            print(f"  ({n}/{len(items)}) エラー: {e}")
            paper_rows.append({**base, "status": STATUS_NOT_RUN, "problems": str(e)})
            continue
        except KeyboardInterrupt:
            stop_reason = "途中で止めました（Ctrl+C）"
            print(f"\n{stop_reason}")
            paper_rows.append({**base, "status": STATUS_NOT_RUN})
            continue

        if not j.cached:
            totals["input_tokens"] += j.input_tokens
            totals["output_tokens"] += j.output_tokens
            totals["seconds"] += j.seconds
            totals["llm_calls"] += j.attempts
        a = j.answer or {}
        paper = a.get("paper") or {}
        paper_rows.append({**base, "status": j.status, "shares_dataset": paper.get("shares_dataset", ""),
                           "evidence": paper.get("evidence", ""), "n_datasets": len(a.get("datasets") or []),
                           "problems": " / ".join(j.problems), "attempts": j.attempts, "model_used": j.model,
                           "input_tokens": j.input_tokens, "output_tokens": j.output_tokens,
                           "seconds": round(j.seconds, 1), "cached": j.cached})
        for d in a.get("datasets") or []:
            dataset_rows.append({**base, "name": d.get("name", ""), "url": d.get("url") or "",
                                 "availability": d.get("availability", ""), "evidence": d.get("evidence", "")})
        answers = {u.get("id"): u for u in a.get("urls") or []}
        for u in item.urls:
            ans = answers.get(u.id, {})
            url_rows.append({**base, "url": u.url, "page": u.page, "source": u.source,
                             "in_references": u.in_references,
                             "is_data_location": ans.get("is_data_location", ""), "reason": ans.get("reason", ""),
                             "decided_by": "LLM"})
        for url in item.excluded_urls:
            url_rows.append({**base, "url": url, "is_data_location": False,
                             "reason": "データと関係ないサイト（ルールで除外）", "decided_by": "ルール"})
        mark = "（キャッシュ）" if j.cached else f"（{j.seconds:.0f}秒）"
        print(f"  ({n}/{len(items)}) {j.status:4} {paper.get('shares_dataset', '-'):7} {p['title'][:55]} {mark}")

    # 保存（results/ は GitHub に上げない）
    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    stem = (f"llm_{safe_name(args.model)}_{started:%Y%m%d}_{prompt.version}_{args.split}"
            + (f"_repeat{args.repeat}" if args.repeat else ""))
    pd.DataFrame(paper_rows).to_csv(out_dir / f"{stem}.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(dataset_rows).to_csv(out_dir / f"{stem}_datasets.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(url_rows).to_csv(out_dir / f"{stem}_urls.csv", index=False, encoding="utf-8-sig")

    papers = pd.DataFrame(paper_rows)
    counts = papers["status"].value_counts().to_dict() if not papers.empty else {}
    log = {
        "started": started.isoformat(timespec="seconds"), "finished": datetime.now().isoformat(timespec="seconds"),
        **judge.settings(), "split": args.split, "repeat": args.repeat,
        "years": list(args.years) if args.years else None, "papers": len(items),
        "status_counts": counts, **{k: round(v, 1) for k, v in totals.items()},
        "output": f"results/{stem}.csv", "stopped": stop_reason,
    }
    with open(out_dir / "runs.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    print(f"\n保存しました: results/{stem}.csv（と _datasets.csv、_urls.csv）")
    print(f"判定の結果: {counts}")
    if not papers.empty and "shares_dataset" in papers:
        print(f"データセットを共有している（LLMの判断）: {papers['shares_dataset'].value_counts().to_dict()}")
    print(f"今回LLMを呼んだ回数 {totals['llm_calls']}、入力 {totals['input_tokens']} トークン、"
          f"出力 {totals['output_tokens']} トークン、{totals['seconds']:.0f} 秒")
    if stop_reason:
        print("続きは、同じコマンドをもう一度実行してください（判定済みの論文はキャッシュから読みます）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
