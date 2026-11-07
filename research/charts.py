"""評価結果のグラフ（PNG）を作る。卒論やスライドにそのまま貼れるよう、明るい背景で作る。

色の決め方
    ・混同行列 … 件数の大きさを表すので、青1色の濃淡（薄い＝少ない、濃い＝多い）。セルには件数の数字を書く
    ・URLの比較 … 2つの方法（段階2／段階3）を区別するので、青とオレンジ。凡例を付け、棒の上に値を書く
    ・年ごと    … 1つの系列なので青1色。凡例は付けず、題名で何の値かを書く
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 画面を開かずに画像ファイルだけ作る
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

# 色（明るい背景用）
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834"]  # 青、オレンジ
BLUE_RAMP = ["#f4f8fd", "#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "font.family": ["Yu Gothic", "Meiryo", "MS Gothic", "sans-serif"],
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": INK, "axes.titleweight": "bold", "axes.titlesize": 12, "font.size": 10,
})


def _finish(fig, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)
    return path


def confusion_heatmap(cm: pd.DataFrame, title: str, path: Path) -> Path:
    """混同行列（行＝正解、列＝LLMの答え）。セルに件数を書く。"""
    fig, ax = plt.subplots(figsize=(1.2 * len(cm.columns) + 2.2, 0.8 * len(cm.index) + 1.8))
    values = cm.to_numpy(dtype=float)
    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    vmax = max(values.max(), 1)
    ax.imshow(values, cmap=cmap, vmin=0, vmax=vmax, aspect="auto")
    for i in range(values.shape[0]):
        for j in range(values.shape[1]):
            v = values[i, j]
            ax.text(j, i, f"{int(v)}", ha="center", va="center", fontsize=11,
                    color="#ffffff" if v > vmax * 0.55 else INK)
    ax.set_xticks(range(len(cm.columns)), [str(c) for c in cm.columns])
    ax.set_yticks(range(len(cm.index)), [str(i) for i in cm.index])
    ax.set_xlabel("LLMの答え")
    ax.set_ylabel("正解（先生のデータセット）")
    ax.set_title(title, loc="left")
    # セルの間に細い区切り線を入れる
    ax.set_xticks(np.arange(-0.5, values.shape[1]), minor=True)
    ax.set_yticks(np.arange(-0.5, values.shape[0]), minor=True)
    ax.grid(which="minor", color=SURFACE, linewidth=2)
    ax.tick_params(which="minor", length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    return _finish(fig, path)


def url_comparison_bars(table: pd.DataFrame, path: Path) -> Path:
    """段階2（LLMなし）と段階3（LLMあり）の、URLの再現率・適合率・F1を並べた棒グラフ。"""
    metrics = ["再現率", "適合率", "F1"]
    labels = ["段階2（LLMなし）", "段階3（LLMあり）"]
    x = np.arange(len(metrics))
    width = 0.36
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for k, (_, row) in enumerate(table.iterrows()):
        vals = [row[m] for m in metrics]
        bars = ax.bar(x + (k - 0.5) * width, vals, width - 0.03, color=SERIES[k], label=labels[k], zorder=3)
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.0%}", ha="center", va="bottom",
                    fontsize=9, color=INK_2)
    ax.set_xticks(x, metrics)
    ax.set_ylim(0, 1.12)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.legend(frameon=False, loc="upper left", ncols=2)
    ax.set_title("データの公開先URLの判断：LLMの前後の比較", loc="left")
    return _finish(fig, path)


def by_year_bars(table: pd.DataFrame, path: Path) -> Path:
    """発表年ごとの、1段目（データセットを共有しているか）の一致率。棒の上に本数も書く。"""
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    years = [str(y) for y in table["年"]]
    vals = list(table["1段目の一致率"])
    bars = ax.bar(years, vals, 0.6, color=SERIES[0], zorder=3)
    for b, v, n in zip(bars, vals, table["本数"]):
        ax.text(b.get_x() + b.get_width() / 2, v + 0.02, f"{v:.0%}\n（{n}本）", ha="center", va="bottom",
                fontsize=9, color=INK_2)
    ax.set_ylim(0, 1.2)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.grid(axis="y", color=GRID, linewidth=0.8, zorder=0)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.set_title("発表年ごとの一致率（データセットを共有しているか）", loc="left")
    return _finish(fig, path)
