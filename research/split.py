"""論文を「調整用」と「評価用」に分ける（段階4）。

    調整用（練習問題）… 答え合わせをして間違え方を見て、プロンプトを直すのに使う
    評価用（本番の試験）… プロンプトの改善がすべて終わってから、最後に1回だけ正解率を測る。卒論に載せる数字

学会と年の偏りが出ないよう、会議×年のグループごとに同じ割合で分ける（層化抽出）。
乱数の種（seed）を固定するので、何度実行しても同じ分け方になる。
"""

from __future__ import annotations

import random

import pandas as pd

DEV = "調整用"
TEST = "評価用"
DEFAULT_DEV_FRACTION = 0.3
DEFAULT_SEED = 42


def split_papers(papers: pd.DataFrame, dev_fraction: float = DEFAULT_DEV_FRACTION, seed: int = DEFAULT_SEED,
                 strata: tuple[str, ...] = ("venue", "year")) -> pd.DataFrame:
    """row_id ごとに調整用／評価用を決めた表を返す（列: row_id, venue, year, group, split）。

    group（先生のシートの論文か、集めた「公開していない論文」か）も層に含め、
    どちらの種類の論文も同じ割合で調整用に入るようにする。
    """
    rng = random.Random(seed)
    rows = []
    keys = [*strata, "group"]
    for _, g in papers.sort_values("row_id").groupby(keys, sort=True):
        ids = list(g["row_id"])
        rng.shuffle(ids)
        n_dev = round(len(ids) * dev_fraction)
        dev = set(ids[:n_dev])
        for _, r in g.iterrows():
            rows.append({"row_id": r["row_id"], "venue": r["venue"], "year": int(r["year"]), "group": r["group"],
                         "split": DEV if r["row_id"] in dev else TEST})
    return pd.DataFrame(rows).sort_values("row_id").reset_index(drop=True)
