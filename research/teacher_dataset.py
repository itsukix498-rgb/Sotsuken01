"""先生のデータセット（研究室の人手調査の結果）を読み込む。

このデータは研究室の未公開データなので、data/ に置き（GitHubには上げない）、
外部のサービス（LLMなど）には送らない。ここでは手元で読み込むだけ。

列の対応は推測で決めず、describe_file() で列の構成を確認してから
data/column_map.json に書く（書き方は column_map.example.json を参照）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# 列の対応で指定できる項目（すべて任意。シートにない項目は書かなくてよい）
MAPPABLE = ("title", "doi", "paper_url", "venue", "year", "paper_type", "has_dataset", "dataset_name", "data_url",
            "exclusion_reason")
# 論文の基本情報以外で、TeacherPaper.extra に入れておく項目
EXTRA_ITEMS = ("paper_type", "has_dataset", "dataset_name", "data_url", "exclusion_reason")


@dataclass
class SheetMap:
    """1つのシートの読み方と、列の対応。"""

    sheet: str
    header_row: int  # 列名が書かれている行（Excelの行番号、1始まり）
    data_start_row: int  # データが始まる行（Excelの行番号、1始まり）
    columns: dict[str, str]  # 項目名（MAPPABLE）→ シートの列名
    role: str = "papers"  # このシートの役割（例: excluded / selected / datasets）。集計の区別に使う


@dataclass
class TeacherPaper:
    """先生のデータセットの論文1本分。"""

    row_id: str  # どのシートの何行目か（例: "selected:12"）
    role: str
    title: str = ""
    doi: str = ""
    paper_url: str = ""
    venue: str = ""
    year: int | None = None
    extra: dict = field(default_factory=dict)  # has_dataset / data_url など、そのほかの項目

    @property
    def s2_id(self) -> str:
        """Semantic Scholar に問い合わせるときのID（DOIがあれば "DOI:..."、なければ空）。"""
        return f"DOI:{self.doi}" if self.doi else ""


def _read_sheets(path: Path) -> dict[str, pd.DataFrame]:
    """Excel ならすべてのシート、CSV なら1枚を、見出しなし（すべての行をデータ）として読む。"""
    if path.suffix.lower() in (".xlsx", ".xlsm", ".xls"):
        return pd.read_excel(path, sheet_name=None, header=None, dtype=str)
    return {path.stem: pd.read_csv(path, header=None, dtype=str, keep_default_na=False)}


def describe_file(path: str | Path, rows: int = 8) -> str:
    """列の構成を確認するために、シートごとの大きさと先頭の数行を文字にして返す（中身は手元で見るだけ）。"""
    path = Path(path)
    out = [f"ファイル: {path.name}"]
    for name, df in _read_sheets(path).items():
        out.append(f"\n=== シート「{name}」 {df.shape[0]}行 × {df.shape[1]}列 ===")
        for i in range(min(rows, len(df))):
            cells = ["" if pd.isna(v) else str(v).replace("\n", " ")[:40] for v in df.iloc[i].tolist()]
            out.append(f"  {i + 1}行目: " + " | ".join(cells))
    return "\n".join(out)


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    """"https://doi.org/10.1145/..." や "https://dl.acm.org/doi/10.1145/..." から DOI だけを取り出す（小文字）。"""
    if not value:
        return ""
    m = DOI_PATTERN.search(str(value))
    if not m:
        return ""
    return m.group(0).rstrip(".,;)").lower()


def _to_year(value: str) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", str(value or ""))
    return int(m.group(0)) if m else None


def load_column_map(path: str | Path) -> list[SheetMap]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    maps = []
    for s in data["sheets"]:
        unknown = set(s["columns"]) - set(MAPPABLE)
        if unknown:
            raise ValueError(f"column_map の項目名が正しくありません: {sorted(unknown)}（使えるのは {MAPPABLE}）")
        maps.append(SheetMap(**s))
    return maps


def load_papers(path: str | Path, maps: list[SheetMap]) -> list[TeacherPaper]:
    """列の対応に従って論文を読み込む。DOIはDOI列か論文URL列から取り出す。"""
    sheets = _read_sheets(Path(path))
    papers: list[TeacherPaper] = []
    for m in maps:
        if m.sheet not in sheets:
            raise ValueError(f"シート「{m.sheet}」が見つかりません（あるシート: {list(sheets)}）")
        df = sheets[m.sheet]
        header = ["" if pd.isna(v) else " ".join(str(v).split()) for v in df.iloc[m.header_row - 1].tolist()]
        col_index = {}
        for item, name in m.columns.items():
            wanted = " ".join(name.split())
            if wanted not in header:
                raise ValueError(f"シート「{m.sheet}」に列「{name}」がありません")
            col_index[item] = header.index(wanted)
        for r in range(m.data_start_row - 1, len(df)):
            row = df.iloc[r]

            def get(item: str) -> str:
                if item not in col_index:
                    return ""
                v = row.iloc[col_index[item]]
                return "" if pd.isna(v) else str(v).strip()

            title = get("title")
            if not title:
                continue  # 空行や集計行は飛ばす
            doi = normalize_doi(get("doi")) or normalize_doi(get("paper_url"))
            papers.append(TeacherPaper(
                row_id=f"{m.sheet}:{r + 1}", role=m.role, title=" ".join(title.split()), doi=doi,
                paper_url=get("paper_url"), venue=get("venue"), year=_to_year(get("year")),
                extra={k: get(k) for k in EXTRA_ITEMS if k in col_index},
            ))
    return papers
