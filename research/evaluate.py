"""LLMの判定を、先生のデータセット（正解）と比べて評価する（段階4）。

評価する内容
    ①URLの判断   … 正解のデータセットのURLを、どれだけ拾えたか（再現率）、拾ったうち何割が正解か（適合率）
                    段階2（LLMなし：抽出したURLを全部「公開先」とみなす）と段階3（LLMが公開先と判断したURL）を比べる
    ②公開状況     … 1段目（あり／なし）の一致率と混同行列、2段目（P／L／O）の混同行列、
                    4分類（公開／要申請／非公開／不明）に直した混同行列
    発表年ごと     … 年ごとの一致率（オープンアクセスの偏りを確かめるため）
    再現性         … 同じ設定で複数回判定したときに、答えが一致した割合
    効率           … 1本あたりの時間・トークン数と、有料APIだった場合の費用の目安

ここで扱う正解は手元で使うだけで、外部には送らない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from extract_urls import normalize_url
from research.ground_truth import TRUTH_NO, TRUTH_YES, PaperTruth, name_key

PRED_LABELS = ("yes", "no", "unknown", "判定不能", "未処理")
FOUR_CLASSES = ("公開", "要申請", "非公開", "不明")


# --- URL --------------------------------------------------------------------------

def _url_key(url: str) -> str:
    key = normalize_url(url).lower()
    return re.sub(r"\.git$", "", key)


def urls_match(a: str, b: str) -> bool:
    """同じデータの場所を指しているか。表記の違いと、片方がもう片方の下の階層である場合（リポジトリとその中のフォルダ）も同じとみなす。"""
    ka, kb = _url_key(a), _url_key(b)
    if not ka or not kb:
        return False
    return ka == kb or ka.startswith(kb + "/") or kb.startswith(ka + "/")


@dataclass
class UrlScore:
    truth_total: int = 0  # 正解のデータセットURLの数
    truth_found: int = 0  # そのうち、予測したURLのどれかと一致した数
    pred_total: int = 0  # 予測したURLの数（「公開先」としたURL）
    pred_correct: int = 0  # そのうち、正解のURLのどれかと一致した数

    @property
    def recall(self) -> float:
        return self.truth_found / self.truth_total if self.truth_total else 0.0

    @property
    def precision(self) -> float:
        return self.pred_correct / self.pred_total if self.pred_total else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def add(self, predicted: list[str], truth: list[str]) -> None:
        self.truth_total += len(truth)
        self.truth_found += sum(any(urls_match(t, p) for p in predicted) for t in truth)
        self.pred_total += len(predicted)
        self.pred_correct += sum(any(urls_match(p, t) for t in truth) for p in predicted)


# --- 論文ごと・データセットごと --------------------------------------------------------

def to_four_class(label: str, availabilities: list[str]) -> str:
    """2段の答えを、4分類（公開／要申請／非公開／不明）に直す。

    あり＋P か L を含む → 公開（L はログインが必要だが、申請なしで取れるので公開に数える）
    あり＋O だけ       → 要申請
    なし               → 非公開
    不明・判定不能など → 不明
    """
    if label == TRUTH_YES:
        if any(a in ("P", "L") for a in availabilities):
            return "公開"
        return "要申請" if availabilities else "不明"
    if label == TRUTH_NO:
        return "非公開"
    return "不明"


def _name_similar(a: str, b: str) -> bool:
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    if ka == kb or (min(len(ka), len(kb)) >= 5 and (ka in kb or kb in ka)):
        return True
    wa = set(re.findall(r"[a-z0-9]+", a.lower())) - {"the", "data", "dataset", "set", "of", "and"}
    wb = set(re.findall(r"[a-z0-9]+", b.lower())) - {"the", "data", "dataset", "set", "of", "and"}
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.5


def match_datasets(predicted: list[dict], truth: PaperTruth) -> tuple[list[tuple], list, list]:
    """予測したデータセットと正解のデータセットを結び付ける（URLが一致するもの、次に名前が似ているもの）。

    戻り値: (結び付いた組 [(正解, 予測)], 見落とした正解, 余分な予測)
    """
    remaining = list(truth.datasets)
    pairs, extra = [], []
    for p in predicted:
        hit = None
        if p.get("url"):
            hit = next((t for t in remaining if any(urls_match(p["url"], u) for u in t.urls)), None)
        if hit is None:
            hit = next((t for t in remaining if _name_similar(p.get("name", ""), t.name)), None)
        if hit is None:
            extra.append(p)
        else:
            remaining.remove(hit)
            pairs.append((hit, p))
    return pairs, remaining, extra


@dataclass
class PaperResult:
    """論文1本分の、正解と予測。"""

    row_id: str
    venue: str
    year: int
    title: str
    kind: str  # selected / excluded / negative
    truth: str  # yes / no
    pred: str  # yes / no / unknown / 判定不能 / 未処理
    pred_datasets: list[dict] = field(default_factory=list)
    all_urls: list[str] = field(default_factory=list)  # 段階2で抽出したURL（LLMなしの比較用）
    llm_data_urls: list[str] = field(default_factory=list)  # LLMが「公開先」と判断したURL
    truth_obj: PaperTruth | None = None
    evidence: str = ""


def evaluate(results: list[PaperResult]) -> dict:
    """すべての評価の表を計算して、辞書で返す（値は pandas の表か数値）。"""
    out: dict = {}
    # まだ判定していない論文は、どの評価にも入れない（LLMの前後を同じ論文で比べるため）
    judged = [r for r in results if r.pred != "未処理"]

    # ①URLの判断（段階2と段階3の比較）
    before, after = UrlScore(), UrlScore()
    for r in judged:
        truth_urls = r.truth_obj.data_urls if r.truth_obj else []
        before.add(r.all_urls, truth_urls)
        after.add(r.llm_data_urls, truth_urls)
    # 正解のURLのうち、そもそも論文の中に書かれていたもの（段階2で拾えたもの）だけで見た、LLMの再現率
    in_paper = UrlScore()
    for r in judged:
        truth_urls = [t for t in (r.truth_obj.data_urls if r.truth_obj else [])
                      if any(urls_match(t, u) for u in r.all_urls)]
        in_paper.add(r.llm_data_urls, truth_urls)
    out["url_comparison"] = pd.DataFrame([
        {"方法": "段階2（LLMなし：抽出したURLをすべて公開先とみなす）", "正解URL": before.truth_total,
         "見つけた正解URL": before.truth_found, "再現率": before.recall, "公開先としたURL": before.pred_total,
         "そのうち正解": before.pred_correct, "適合率": before.precision, "F1": before.f1},
        {"方法": "段階3（LLMが公開先と判断したURLだけ）", "正解URL": after.truth_total,
         "見つけた正解URL": after.truth_found, "再現率": after.recall, "公開先としたURL": after.pred_total,
         "そのうち正解": after.pred_correct, "適合率": after.precision, "F1": after.f1},
    ])
    out["url_recall_within_extracted"] = in_paper.recall

    # ②公開状況：1段目（あり／なし）
    cm = pd.crosstab(pd.Series([r.truth for r in judged], name="正解"),
                     pd.Series([r.pred for r in judged], name="LLMの答え"))
    out["paper_confusion"] = cm.reindex(index=[TRUTH_YES, TRUTH_NO],
                                        columns=[c for c in PRED_LABELS if c != "未処理"], fill_value=0)
    n = len(judged)
    correct = sum(r.truth == r.pred for r in judged)
    tp = sum(r.truth == TRUTH_YES and r.pred == TRUTH_YES for r in judged)
    fp = sum(r.truth == TRUTH_NO and r.pred == TRUTH_YES for r in judged)
    fn = sum(r.truth == TRUTH_YES and r.pred != TRUTH_YES for r in judged)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    out["paper_summary"] = {"判定した論文": n, "一致": correct, "一致率": correct / n if n else 0.0,
                            "「あり」の適合率": prec, "「あり」の再現率": rec,
                            "「あり」のF1": 2 * prec * rec / (prec + rec) if prec + rec else 0.0,
                            "未処理": len(results) - n}

    # 種類ごと（データあり・対象外・集めた公開していない論文）の一致率
    out["by_kind"] = pd.DataFrame([
        {"種類": kind, "本数": len(g), "一致": sum(r.truth == r.pred for r in g),
         "一致率": sum(r.truth == r.pred for r in g) / len(g)}
        for kind in ("selected", "excluded", "negative")
        if (g := [r for r in judged if r.kind == kind])
    ])

    # 2段目（P／L／O）：正解も予測も「あり」の論文で、結び付いたデータセットどうしを比べる
    pairs, missed, extra = [], 0, 0
    for r in judged:
        if r.truth == TRUTH_YES and r.pred == TRUTH_YES and r.truth_obj:
            p, m, e = match_datasets(r.pred_datasets, r.truth_obj)
            pairs += p
            missed += len(m)
            extra += len(e)
    if pairs:
        cm2 = pd.crosstab(pd.Series([t.availability for t, _ in pairs], name="正解"),
                          pd.Series([p.get("availability", "") for _, p in pairs], name="LLMの答え"))
        out["dataset_confusion"] = cm2.reindex(index=["P", "L", "O"], columns=["P", "L", "O"], fill_value=0)
    else:
        out["dataset_confusion"] = pd.DataFrame(0, index=["P", "L", "O"], columns=["P", "L", "O"])
    out["dataset_summary"] = {"結び付いたデータセット": len(pairs),
                              "P／L／Oが一致": sum(t.availability == p.get("availability") for t, p in pairs),
                              "P／L／Oの一致率": (sum(t.availability == p.get("availability") for t, p in pairs)
                                              / len(pairs)) if pairs else 0.0,
                              "見落とした正解データセット": missed, "余分に挙げたデータセット": extra}

    # 4分類（公開／要申請／非公開／不明）
    truth4 = [to_four_class(r.truth, [d.availability for d in (r.truth_obj.datasets if r.truth_obj else [])])
              for r in judged]
    pred4 = [to_four_class(r.pred, [d.get("availability", "") for d in r.pred_datasets]) for r in judged]
    cm4 = pd.crosstab(pd.Series(truth4, name="正解"), pd.Series(pred4, name="LLMの答え"))
    out["four_class_confusion"] = cm4.reindex(index=list(FOUR_CLASSES[:3]), columns=list(FOUR_CLASSES), fill_value=0)
    out["four_class_accuracy"] = sum(a == b for a, b in zip(truth4, pred4)) / len(judged) if judged else 0.0

    # 発表年ごと
    rows = []
    for year in sorted({r.year for r in judged}):
        g = [r for r in judged if r.year == year]
        s = UrlScore()
        for r in g:
            s.add(r.llm_data_urls, r.truth_obj.data_urls if r.truth_obj else [])
        rows.append({"年": year, "本数": len(g), "1段目の一致率": sum(r.truth == r.pred for r in g) / len(g),
                     "URLの再現率": s.recall if s.truth_total else None})
    out["by_year"] = pd.DataFrame(rows)
    return out


def errors_table(results: list[PaperResult]) -> pd.DataFrame:
    """間違えた例の一覧（調整用だけで作る）。プロンプトを直すための材料。"""
    rows = []
    for r in results:
        if r.pred == "未処理":
            continue
        truth_urls = r.truth_obj.data_urls if r.truth_obj else []
        missed_urls = [t for t in truth_urls if not any(urls_match(t, p) for p in r.llm_data_urls)]
        missed_in_paper = [t for t in missed_urls if any(urls_match(t, u) for u in r.all_urls)]
        wrong_urls = [p for p in r.llm_data_urls if not any(urls_match(p, t) for t in truth_urls)]
        problems = []
        if r.truth != r.pred:
            problems.append(f"1段目: 正解 {r.truth} → LLM {r.pred}")
        if r.truth == TRUTH_YES and r.pred == TRUTH_YES and r.truth_obj:
            pairs, missed, extra = match_datasets(r.pred_datasets, r.truth_obj)
            for t, p in pairs:
                if t.availability != p.get("availability"):
                    problems.append(f"P/L/O: {t.name} 正解 {t.availability} → LLM {p.get('availability')}")
            if missed:
                problems.append("見落としたデータセット: " + ", ".join(t.name for t in missed))
            if extra:
                problems.append("余分なデータセット: " + ", ".join(p.get("name", "") for p in extra))
        if missed_in_paper:
            problems.append("論文中にあったのに公開先としなかった正解URL: " + " ".join(missed_in_paper))
        if wrong_urls:
            problems.append("正解ではないのに公開先としたURL: " + " ".join(wrong_urls))
        if problems:
            rows.append({"row_id": r.row_id, "会議": r.venue, "年": r.year, "タイトル": r.title, "種類": r.kind,
                         "正解": r.truth, "LLM": r.pred, "LLMの根拠": r.evidence,
                         "正解のデータセット": "; ".join(f"{d.name} ({d.availability})"
                                                  for d in (r.truth_obj.datasets if r.truth_obj else [])),
                         "LLMのデータセット": "; ".join(f"{d.get('name')} ({d.get('availability')})"
                                                 for d in r.pred_datasets),
                         "問題点": " / ".join(problems)})
    return pd.DataFrame(rows)


def reproducibility(runs: list[dict[str, tuple]]) -> dict:
    """同じ設定で複数回判定した結果が一致した割合。

    runs: 1回分ごとに {row_id: (1段目の答え, 4分類, P/L/O の並び)} の辞書
    """
    if len(runs) < 2:
        return {}
    ids = set.intersection(*(set(r) for r in runs))
    if not ids:
        return {}
    out = {"論文の数": len(ids), "回数": len(runs)}
    for i, label in enumerate(("1段目が一致", "4分類が一致", "P/L/Oまで一致")):
        agree = sum(all(run[rid][i] == runs[0][rid][i] for run in runs) for rid in ids)
        out[label] = agree / len(ids)
    return out


def cost_estimate(input_tokens: float, output_tokens: float, prices: dict[str, tuple[float, float]]) -> pd.DataFrame:
    """1本あたりのトークン数から、有料APIだった場合の費用を計算する（prices は 100万トークンあたりのドル）。"""
    rows = []
    for model, (pin, pout) in prices.items():
        per_paper = input_tokens / 1e6 * pin + output_tokens / 1e6 * pout
        rows.append({"モデル（有料の場合）": model, "入力 $/100万": pin, "出力 $/100万": pout,
                     "1本あたり $": per_paper, "1,000本あたり $": per_paper * 1000})
    return pd.DataFrame(rows)
