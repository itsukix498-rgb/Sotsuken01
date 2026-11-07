"""段階4（評価）のテスト。先生のデータセットは使わず、架空の表で確かめる。"""

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from research.evaluate import (  # noqa: E402
    PaperResult,
    UrlScore,
    cost_estimate,
    errors_table,
    evaluate,
    match_datasets,
    reproducibility,
    to_four_class,
    urls_match,
)
from research.ground_truth import PaperTruth, TruthDataset, build_truth, split_names  # noqa: E402
from research.split import DEV, TEST, split_papers  # noqa: E402


# --- 分け方 -----------------------------------------------------------------------

def _pool():
    rows = []
    for venue in ("LAK", "EDM"):
        for year in (2020, 2021):
            for i in range(10):
                rows.append({"row_id": f"{venue}-{year}-{i}", "venue": venue, "year": year,
                             "group": "teacher" if i < 7 else "negative"})
    return pd.DataFrame(rows)


def test_split_is_stratified_and_reproducible():
    a, b = split_papers(_pool()), split_papers(_pool())
    assert a.equals(b)  # seed が同じなら同じ分け方
    # 会議×年×種類のどのグループでも、約30%が調整用
    for _, g in a.groupby(["venue", "year", "group"]):
        assert (g["split"] == DEV).sum() == round(len(g) * 0.3)
    assert set(a["split"]) == {DEV, TEST}
    assert not a.equals(split_papers(_pool(), seed=7))  # seed を変えると変わる


# --- 正解の表 ---------------------------------------------------------------------

def _teacher_xlsx(tmp_path) -> Path:
    path = tmp_path / "teacher.xlsx"
    sel = pd.DataFrame([["Basic"] + [""] * 5,
                        ["Paper type", "Venue name", "Year", "Paper title", "Paper URL (or DOI link if it exists)",
                         'Data set name(s) (must match the "Selected data sets" sheet)'],
                        ["[c]"] * 6,
                        ["F", "LAK", "2020", "Paper A", "", "Alpha Logs, BetaSet"],
                        ["F", "EDM", "2021", "Paper B", "", "gamma"]])
    ds_cols = ['Data set name (must match the "Selected papers" sheet)',
               "Alternative names for the same data set and/or abbreviation explanation",
               "What is the declared availability of the data set?",
               'Data set URL (listed in the paper directly or acquired over several "jumps")',
               "Can the data set still be acquired (downloaded from a valid URL or otherwise obtained)?",
               "Alternative URL for the data set (or target URL if YB to the previous)"]
    ds = pd.DataFrame([[""] * 6, ds_cols, ["[c]"] * 6,
                       ["Alpha Logs", "-", "P", "https://osf.io/alpha", "Y", "-"],
                       ["Beta Set", "", "L", "https://www.kaggle.com/beta", "Y", "-"],
                       ["Gamma Data", "gamma; GD", "O", "https://example.org/contact", "YB", "https://new.org/g"]])
    with pd.ExcelWriter(path) as w:
        sel.to_excel(w, sheet_name="Selected papers", header=False, index=False)
        ds.to_excel(w, sheet_name="Selected datasets", header=False, index=False)
    return path


def test_build_truth_links_names_and_alternatives(tmp_path):
    statuses = pd.DataFrame([{"row_id": "Selected papers:4", "role": "selected"},
                             {"row_id": "Selected papers:5", "role": "selected"},
                             {"row_id": "Excluded papers:4", "role": "excluded"},
                             {"row_id": "negative:LAK:2020:1", "role": "negative"}])
    t = build_truth(_teacher_xlsx(tmp_path), statuses)
    a = t["Selected papers:4"]
    assert a.label == "yes" and [d.name for d in a.datasets] == ["Alpha Logs", "Beta Set"]  # 「BetaSet」も結び付く
    assert [d.availability for d in a.datasets] == ["P", "L"]
    b = t["Selected papers:5"]
    assert b.datasets[0].name == "Gamma Data"  # 別名「gamma」から結び付く
    assert b.data_urls == ["https://example.org/contact", "https://new.org/g"]
    assert (t["Excluded papers:4"].label, t["Excluded papers:4"].kind) == ("no", "excluded")
    assert (t["negative:LAK:2020:1"].label, t["negative:LAK:2020:1"].kind) == ("no", "negative")


def test_split_names():
    assert split_names("A, B; C\nD") == ["A", "B", "C", "D"]
    assert split_names("-") == []


# --- URLの比べ方 ------------------------------------------------------------------

@pytest.mark.parametrize("a, b, same", [
    ("https://github.com/lab/data", "github.com/lab/data/", True),
    ("https://github.com/lab/data/tree/main/raw", "https://github.com/lab/data", True),  # 下の階層
    ("https://github.com/lab/data.git", "https://github.com/lab/data", True),
    ("https://github.com/lab/data2", "https://github.com/lab/data", False),
    ("https://osf.io/abcde", "https://osf.io/xyz", False),
])
def test_urls_match(a, b, same):
    assert urls_match(a, b) is same


def test_url_score():
    s = UrlScore()
    s.add(["https://osf.io/a", "https://doi.org/x"], ["https://osf.io/a", "https://zenodo.org/b"])
    assert (s.recall, s.precision) == (0.5, 0.5)


# --- 判定の評価 -------------------------------------------------------------------

def _truth(label, datasets=(), kind="selected"):
    return PaperTruth("r", label, kind, list(datasets))


def test_four_class():
    assert to_four_class("yes", ["P", "O"]) == "公開"
    assert to_four_class("yes", ["L"]) == "公開"
    assert to_four_class("yes", ["O"]) == "要申請"
    assert to_four_class("no", []) == "非公開"
    assert to_four_class("unknown", []) == "不明"


def test_match_datasets_by_url_then_name():
    t = _truth("yes", [TruthDataset("Alpha Logs", "P", ["https://osf.io/alpha"]),
                       TruthDataset("Beta Set", "L", ["https://kaggle.com/beta"]),
                       TruthDataset("Gamma", "O", [])])
    pred = [{"name": "logs", "url": "https://osf.io/alpha", "availability": "P"},
            {"name": "the Beta Set data", "url": None, "availability": "P"},
            {"name": "Something else", "url": None, "availability": "O"}]
    pairs, missed, extra = match_datasets(pred, t)
    assert [(tt.name, p["availability"]) for tt, p in pairs] == [("Alpha Logs", "P"), ("Beta Set", "P")]
    assert [m.name for m in missed] == ["Gamma"] and len(extra) == 1


def _result(rid, truth, pred, kind="selected", year=2020, pred_ds=(), truth_ds=(), all_urls=(), llm_urls=()):
    return PaperResult(row_id=rid, venue="LAK", year=year, title=rid, kind=kind, truth=truth, pred=pred,
                       pred_datasets=list(pred_ds), all_urls=list(all_urls), llm_data_urls=list(llm_urls),
                       truth_obj=_truth(truth, truth_ds, kind))


def test_evaluate_tables():
    ds = [TruthDataset("Alpha", "P", ["https://osf.io/a"])]
    results = [
        _result("1", "yes", "yes", pred_ds=[{"name": "Alpha", "url": "https://osf.io/a", "availability": "P"}],
                truth_ds=ds, all_urls=["https://osf.io/a", "https://doi.org/x"], llm_urls=["https://osf.io/a"]),
        _result("2", "yes", "no", truth_ds=ds, all_urls=["https://osf.io/a"], year=2021),
        _result("3", "no", "no", kind="negative", all_urls=["https://doi.org/y"]),
        _result("4", "no", "yes", kind="excluded", pred_ds=[{"name": "X", "url": None, "availability": "O"}]),
        _result("5", "yes", "未処理", truth_ds=ds),
    ]
    out = evaluate(results)
    ps = out["paper_summary"]
    assert (ps["判定した論文"], ps["一致"], ps["未処理"]) == (4, 2, 1)
    assert ps["「あり」の適合率"] == 0.5 and ps["「あり」の再現率"] == 0.5
    assert out["paper_confusion"].loc["yes", "no"] == 1
    url = out["url_comparison"]
    # 未処理の論文は数えない。段階2：正解URL2件をすべて拾い、拾った4件のうち2件が正解
    assert (url.iloc[0]["再現率"], url.iloc[0]["適合率"]) == (1.0, 0.5)
    # 段階3：LLMは正解URL2件のうち1件を公開先とし、公開先とした1件はすべて正解
    assert (url.iloc[1]["再現率"], url.iloc[1]["適合率"]) == (0.5, 1.0)
    assert out["dataset_summary"]["P／L／Oの一致率"] == 1.0
    assert out["four_class_confusion"].loc["非公開", "要申請"] == 1
    assert list(out["by_year"]["年"]) == [2020, 2021]
    errors = errors_table(results)
    assert set(errors["row_id"]) == {"2", "4"}


def test_reproducibility():
    run1 = {"a": ("yes", "公開", ("P",)), "b": ("no", "非公開", ())}
    run2 = {"a": ("yes", "公開", ("L",)), "b": ("no", "非公開", ())}
    r = reproducibility([run1, run2, run1])
    assert r["1段目が一致"] == 1.0 and r["4分類が一致"] == 1.0 and r["P/L/Oまで一致"] == 0.5
    assert reproducibility([run1]) == {}


def test_cost_estimate():
    df = cost_estimate(1_000_000, 100_000, {"m": (1.0, 10.0)})
    assert df.iloc[0]["1本あたり $"] == pytest.approx(2.0)
