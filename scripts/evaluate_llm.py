"""段階4：LLMの判定を、先生のデータセット（正解）と答え合わせする。

使い方
    # 調整用で評価する（初期値）。LLMは呼ばず、段階3で判定済みの答え（キャッシュ）だけを使う
    python scripts/evaluate_llm.py --provider gemini --model gemini-3.5-flash-lite

    # 最終評価（評価用の論文）。プロンプトの改善がすべて終わってから1回だけ
    python scripts/evaluate_llm.py --provider gemini --model gemini-3.5-flash-lite --split test --final

先に、同じ設定で判定しておく
    python scripts/run_llm_judge.py --provider gemini --model gemini-3.5-flash-lite             # 1回目
    python scripts/run_llm_judge.py --provider gemini --model gemini-3.5-flash-lite --repeat 1  # 再現性用
    python scripts/run_llm_judge.py --provider gemini --model gemini-3.5-flash-lite --repeat 2  # 再現性用

出力（results/ は GitHub に上げない。先生のデータセットの内容を含むため）
    results/eval_<モデル>_<プロンプトの版>_<調整用|評価用>_<日付>/
        summary.json                 … 主な数値のまとめ
        url_comparison.csv / .png    … URLの判断：段階2と段階3の比較
        paper_confusion.csv / .png   … 1段目（あり／なし）の混同行列
        dataset_confusion.csv / .png … 2段目（P／L／O）の混同行列
        four_class_confusion.csv / .png … 4分類（公開／要申請／非公開／不明）の混同行列
        by_year.csv / .png           … 発表年ごとの一致率
        by_kind.csv                  … 論文の種類（データあり・対象外・公開していない論文）ごとの一致率
        efficiency.csv               … 1本あたりの時間・トークン数と、有料APIの費用の目安
        errors.csv                   … 間違えた例の一覧（プロンプトを直すための材料）
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research import charts  # noqa: E402
from research.evaluate import (  # noqa: E402
    PaperResult,
    cost_estimate,
    errors_table,
    evaluate,
    reproducibility,
    to_four_class,
)
from research.ground_truth import build_truth  # noqa: E402
from research.judge import STATUS_INVALID, STATUS_NOT_JUDGED, Judge, load_prompt  # noqa: E402
from research.llm import get_provider  # noqa: E402
from research.pipeline import build_items, select_targets  # noqa: E402
from research.prices import PRICES, PRICES_CHECKED  # noqa: E402
from research.split import DEV, TEST  # noqa: E402
from scripts.run_llm_judge import load_env, safe_name  # noqa: E402


def predictions(judge: Judge, items) -> dict[str, tuple]:
    """判定済みの答え（キャッシュ）を読む。row_id → (1段目, データセット, 公開先としたURL, 根拠, Judgement)"""
    out = {}
    for p, item, _ in items:
        j = judge.judge(item)  # cache_only なので LLM は呼ばない
        if j.status == STATUS_NOT_JUDGED:
            out[p["row_id"]] = ("未処理", [], [], "", j)
            continue
        if j.status == STATUS_INVALID:
            out[p["row_id"]] = (STATUS_INVALID, [], [], "", j)
            continue
        a = j.answer or {}
        by_id = {u.get("id"): u for u in a.get("urls") or []}
        data_urls = [u.url for u in item.urls if by_id.get(u.id, {}).get("is_data_location") is True]
        out[p["row_id"]] = ((a.get("paper") or {}).get("shares_dataset", "unknown"), a.get("datasets") or [],
                            data_urls, (a.get("paper") or {}).get("evidence", ""), j)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="LLMの判定を先生のデータセットと答え合わせする（段階4）")
    parser.add_argument("--provider", required=True, choices=["gemini", "ollama"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--prompt", default="judge_v1")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--final", action="store_true", help="評価用（最終評価）を計算してよいときだけ付ける")
    parser.add_argument("--dataset", default=str(ROOT / "data" / "teacher_dataset.xlsx"))
    args = parser.parse_args(argv)
    if args.split == "test" and not args.final:
        parser.error("評価用の論文は、最終評価のときだけ使います。--final を付けてください")

    load_env()
    prompt = load_prompt(args.prompt)
    targets = select_targets(args.split)
    items = build_items(targets)
    truth = build_truth(args.dataset, targets[["row_id", "role"]])
    provider = get_provider(args.provider, args.model)

    # 1回目の答えで評価する。再現性は、繰り返し（repeat 1, 2）の答えがあれば計算する
    main_preds = predictions(Judge(provider, prompt, cache_dir=ROOT / "data" / "cache" / "llm", cache_only=True),
                             items)
    results = []
    for p, item, all_urls in items:
        label, datasets, data_urls, evidence, _ = main_preds[p["row_id"]]
        results.append(PaperResult(row_id=p["row_id"], venue=p["venue"], year=int(p["year"]), title=p["title"],
                                   kind=truth[p["row_id"]].kind, truth=truth[p["row_id"]].label, pred=label,
                                   pred_datasets=datasets, all_urls=all_urls, llm_data_urls=data_urls,
                                   truth_obj=truth[p["row_id"]], evidence=evidence))
    out = evaluate(results)

    runs = []
    for repeat in (0, 1, 2):
        preds = main_preds if repeat == 0 else predictions(
            Judge(provider, prompt, cache_dir=ROOT / "data" / "cache" / "llm", cache_only=True, repeat=repeat), items)
        run = {rid: (lab, to_four_class(lab, [d.get("availability", "") for d in ds]),
                     tuple(sorted(d.get("availability", "") for d in ds)))
               for rid, (lab, ds, _, _, _) in preds.items() if lab not in ("未処理",)}
        if run:
            runs.append(run)
    repro = reproducibility(runs)

    # 効率（判定したときに記録したトークン数・時間。キャッシュに残っている）
    js = [v[4] for v in main_preds.values() if v[0] != "未処理"]
    n = len(js) or 1
    eff = {"論文の数": len(js), "1本あたりの秒数": sum(j.seconds for j in js) / n,
           "1本あたりの入力トークン": sum(j.input_tokens for j in js) / n,
           "1本あたりの出力トークン": sum(j.output_tokens for j in js) / n,
           "1本あたりのLLM呼び出し回数": sum(j.attempts for j in js) / n}
    costs = cost_estimate(eff["1本あたりの入力トークン"], eff["1本あたりの出力トークン"], PRICES)

    # 保存
    split_label = DEV if args.split == "dev" else TEST
    out_dir = ROOT / "results" / f"eval_{safe_name(args.model)}_{prompt.version}_{split_label}_{datetime.now():%Y%m%d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    def save(df: pd.DataFrame, name: str, index: bool = False) -> None:
        df.to_csv(out_dir / f"{name}.csv", index=index, encoding="utf-8-sig")

    save(out["url_comparison"], "url_comparison")
    save(out["paper_confusion"], "paper_confusion", index=True)
    save(out["dataset_confusion"], "dataset_confusion", index=True)
    save(out["four_class_confusion"], "four_class_confusion", index=True)
    save(out["by_year"], "by_year")
    save(out["by_kind"], "by_kind")
    save(pd.concat([pd.DataFrame([eff]), costs], axis=1), "efficiency")
    errors = errors_table(results)
    save(errors, "errors")
    charts.url_comparison_bars(out["url_comparison"], out_dir / "url_comparison.png")
    charts.confusion_heatmap(out["paper_confusion"], "データセットを共有しているか（1段目）",
                             out_dir / "paper_confusion.png")
    charts.confusion_heatmap(out["dataset_confusion"], "公開の形 P／L／O（2段目）", out_dir / "dataset_confusion.png")
    charts.confusion_heatmap(out["four_class_confusion"], "公開状況（4分類）", out_dir / "four_class_confusion.png")
    if not out["by_year"].empty:
        charts.by_year_bars(out["by_year"], out_dir / "by_year.png")

    summary = {
        "作成日時": datetime.now().isoformat(timespec="seconds"), "分け方": split_label,
        **judge_settings(provider, prompt), "論文の数": len(results),
        "1段目": out["paper_summary"], "2段目": out["dataset_summary"],
        "4分類の一致率": out["four_class_accuracy"],
        "URL（段階2）": out["url_comparison"].iloc[0][["再現率", "適合率", "F1"]].to_dict(),
        "URL（段階3）": out["url_comparison"].iloc[1][["再現率", "適合率", "F1"]].to_dict(),
        "論文中にあった正解URLに対する段階3の再現率": out["url_recall_within_extracted"],
        "再現性": repro, "効率": eff, "料金の確認日": PRICES_CHECKED,
        "間違えた例の数": len(errors),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1, default=float),
                                          encoding="utf-8")

    # 画面に主な数字を出す
    ps, ds = out["paper_summary"], out["dataset_summary"]
    print(f"評価（{split_label}）: {len(results)} 本（未処理 {ps['未処理']} 本）")
    print(f"  1段目（データセットを共有しているか）: 一致率 {ps['一致率']:.0%}"
          f"（「あり」の適合率 {ps['「あり」の適合率']:.0%}、再現率 {ps['「あり」の再現率']:.0%}）")
    print(f"  2段目（P／L／O）: 結び付いたデータセット {ds['結び付いたデータセット']} 件、一致率 {ds['P／L／Oの一致率']:.0%}、"
          f"見落とし {ds['見落とした正解データセット']} 件、余分 {ds['余分に挙げたデータセット']} 件")
    print(f"  4分類の一致率: {out['four_class_accuracy']:.0%}")
    u = out["url_comparison"]
    print(f"  URL 段階2: 再現率 {u.iloc[0]['再現率']:.0%}／適合率 {u.iloc[0]['適合率']:.0%}　"
          f"段階3: 再現率 {u.iloc[1]['再現率']:.0%}／適合率 {u.iloc[1]['適合率']:.0%}")
    print(f"  再現性: {repro or '（繰り返しの判定がまだないので未計算）'}")
    print(f"  効率: 1本あたり {eff['1本あたりの秒数']:.1f} 秒、入力 {eff['1本あたりの入力トークン']:.0f}・"
          f"出力 {eff['1本あたりの出力トークン']:.0f} トークン")
    print(f"  間違えた例: {len(errors)} 本 → {out_dir.relative_to(ROOT)}\\errors.csv")
    print(f"\n保存しました: {out_dir.relative_to(ROOT)}")
    return 0


def judge_settings(provider, prompt) -> dict:
    return {**provider.settings(), "prompt_version": prompt.version}


if __name__ == "__main__":
    sys.exit(main())
