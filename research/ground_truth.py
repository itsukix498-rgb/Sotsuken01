"""先生のデータセットから、答え合わせ用の正解の表を作る（段階4）。

    論文ごと（1段目）:
        Selected papers に載っている論文 … あり
        Excluded papers（対象外）の論文  … なし（データ分析をしていないので、データも共有していない）
        集めた「公開していない論文」     … なし
    データセットごと（2段目、「あり」の論文だけ）:
        Selected papers の「Data set name(s)」（カンマ区切りで複数のことがある）を、
        Selected datasets の名前・別名と結び付けて、URL・公開の形（P／L／O）・今も取れるか（Y／YB）を取り出す

この表は手元で答え合わせに使うだけで、外部（LLMなど）には送らない。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from research.teacher_dataset import normalize_doi

TRUTH_YES = "yes"
TRUTH_NO = "no"

# Selected datasets シートの列（列名は2行目、データは4行目から）
DS_NAME = 'Data set name (must match the "Selected papers" sheet)'
DS_ALT = "Alternative names for the same data set and/or abbreviation explanation"
DS_AVAIL = "What is the declared availability of the data set?"
DS_URL = 'Data set URL (listed in the paper directly or acquired over several "jumps")'
DS_STILL = "Can the data set still be acquired (downloaded from a valid URL or otherwise obtained)?"
DS_ALT_URL = "Alternative URL for the data set (or target URL if YB to the previous)"
SP_NAMES = 'Data set name(s) (must match the "Selected data sets" sheet)'


@dataclass
class TruthDataset:
    name: str
    availability: str  # P / L / O
    urls: list[str] = field(default_factory=list)  # 論文に書かれたURLと、別のURL
    still_available: str = ""  # Y / YB


@dataclass
class PaperTruth:
    row_id: str
    label: str  # yes / no
    kind: str  # selected / excluded / negative
    datasets: list[TruthDataset] = field(default_factory=list)
    unmatched_names: list[str] = field(default_factory=list)  # Selected datasets に見つからなかった名前

    @property
    def data_urls(self) -> list[str]:
        return [u for d in self.datasets for u in d.urls]


def name_key(name: str) -> str:
    """データセット名の表記の違い（大文字小文字・記号・空白）を無視して比べるための文字列。"""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _read_sheet(xlsx: Path, sheet: str) -> pd.DataFrame:
    raw = pd.read_excel(xlsx, sheet_name=sheet, header=None, dtype=str)
    header = [" ".join(str(v).split()) for v in raw.iloc[1].tolist()]
    df = raw.iloc[3:].copy()
    df.columns = header
    return df


def _clean(value) -> str:
    v = "" if pd.isna(value) else str(value).strip()
    return "" if v in ("-", "?", "N/A") else v


def load_datasets(xlsx: str | Path) -> dict[str, TruthDataset]:
    """Selected datasets を読み、名前と別名の両方から引ける辞書にする。"""
    df = _read_sheet(Path(xlsx), "Selected datasets")
    index: dict[str, TruthDataset] = {}
    for _, r in df.iterrows():
        name = _clean(r[DS_NAME])
        if not name:
            continue
        urls = [u for u in (_clean(r[DS_URL]), _clean(r[DS_ALT_URL])) if u.startswith("http")]
        d = TruthDataset(name=name, availability=_clean(r[DS_AVAIL]).upper()[:1], urls=urls,
                         still_available=_clean(r[DS_STILL]))
        index.setdefault(name_key(name), d)
        for alt in re.split(r"[;,]", _clean(r[DS_ALT])):
            if name_key(alt):
                index.setdefault(name_key(alt), d)
    return index


def split_names(cell: str) -> list[str]:
    """「Data set name(s)」の欄を、データセット名ごとに分ける（カンマ・セミコロン・改行区切り）。"""
    return [n.strip() for n in re.split(r"[,;\n]", cell or "") if n.strip() and n.strip() not in ("-", "?")]


def build_truth(xlsx: str | Path, statuses: pd.DataFrame) -> dict[str, PaperTruth]:
    """row_id ごとの正解。statuses は papers_status.csv と negatives_status.csv をつないだ表（row_id, role）。"""
    xlsx = Path(xlsx)
    datasets = load_datasets(xlsx)
    selected = _read_sheet(xlsx, "Selected papers")
    # papers_status.csv の row_id は「シート名:Excelの行番号」
    names_by_row = {f"Selected papers:{i + 1}": _clean(v) for i, v in zip(selected.index, selected[SP_NAMES])}

    truths: dict[str, PaperTruth] = {}
    for _, s in statuses.iterrows():
        rid, role = s["row_id"], s["role"]
        if role == "selected":
            t = PaperTruth(rid, TRUTH_YES, "selected")
            for n in split_names(names_by_row.get(rid, "")):
                d = datasets.get(name_key(n))
                if d and d not in t.datasets:
                    t.datasets.append(d)
                elif not d:
                    t.unmatched_names.append(n)
            truths[rid] = t
        else:
            truths[rid] = PaperTruth(rid, TRUTH_NO, "excluded" if role == "excluded" else "negative")
    return truths


def doi_of(value: str) -> str:
    return normalize_doi(value)
