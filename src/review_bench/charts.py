"""Charts for one run, drawn from metrics.json values (static PNGs for the README; summary.md is the table view).

  detection_false_alarms.png  bug-case detection and control false-alarm rates per context condition, per repo,
                              with 95% Wilson intervals (any confidence)
  calibration.png             reliability diagram: mean stated confidence vs share of findings that are correct,
                              one line per condition; marker area grows with the number of findings in the bin

Colors follow the dataviz reference palette (light mode): repos are categorical (blue, orange); conditions are
ordinal (more context = darker blue), because A < B < C is an ordering, not just a set of names.
"""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e4e3df"
REPO_COLORS = {"angular": "#2a78d6", "django": "#eb6834"}
COND_COLORS = {"A": "#86b6ef", "B": "#2a78d6", "C": "#104281"}  # ordinal blue: steps 250 / 450 / 650
COND_LABELS = {"A": "A · diff", "B": "B · + description", "C": "C · + full files"}


def _style(ax) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=TEXT_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=1)
    ax.set_axisbelow(True)


def _figure(ncols: int, width: float):
    fig, axes = plt.subplots(1, ncols, figsize=(width, 3.8), facecolor=SURFACE, squeeze=False)
    for ax in axes[0]:
        _style(ax)
    return fig, axes[0]


def _rates_panel(ax, metrics: dict, key: str, title: str, conditions: list[str], repos: list[str]) -> None:
    offsets = {repo: (i - (len(repos) - 1) / 2) * 0.16 for i, repo in enumerate(repos)}
    for repo in repos:
        xs, ys, los, his = [], [], [], []
        for x, cond in enumerate(conditions):
            r = metrics["groups"].get(f"{repo}/{cond}", {}).get(key, {}).get("0.0")
            if not r or r["n"] == 0:
                continue
            xs.append(x + offsets[repo])
            ys.append(r["rate"])
            los.append(r["rate"] - r["ci95"][0])
            his.append(r["ci95"][1] - r["rate"])
        color = REPO_COLORS.get(repo, TEXT_2)
        ax.errorbar(xs, ys, yerr=[los, his], fmt="none", ecolor=color, elinewidth=2, capsize=0, alpha=0.45)
        ax.scatter(xs, ys, s=64, color=color, edgecolors=SURFACE, linewidths=2, zorder=3, label=repo)
    ax.set_xticks(range(len(conditions)), [COND_LABELS.get(c, c) for c in conditions])
    ax.set_xlim(-0.5, len(conditions) - 0.5)
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title(title, loc="left", color=TEXT, fontsize=11, pad=10)


def detection_chart(metrics: dict, out: Path) -> Path:
    groups = metrics["groups"]
    conditions = sorted({k.split("/")[1] for k in groups})
    repos = sorted({k.split("/")[0] for k in groups} - {"all"})
    fig, (left, right) = _figure(2, 9.5)
    _rates_panel(left, metrics, "detection", "Bug cases caught (higher is better)", conditions, repos)
    _rates_panel(right, metrics, "false_alarm", "Controls with any finding (lower is better)", conditions, repos)
    left.legend(frameon=False, labelcolor=TEXT_2, fontsize=9, loc="upper left")
    fig.text(0.01, 0.01, "Dots: rate at any confidence. Bars: 95% Wilson interval.", color=TEXT_2, fontsize=8)
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    path = out / "detection_false_alarms.png"
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


def calibration_chart(metrics: dict, out: Path) -> Path:
    fig, (ax,) = _figure(1, 7.6)
    ax.grid(axis="both", color=GRID, linewidth=1)
    ax.plot([0, 1], [0, 1], color=TEXT_2, linewidth=1, label="perfect calibration")
    for cond, c in metrics["calibration"].items():
        if not c["bins"]:
            continue
        xs = [b["mean_confidence"] for b in c["bins"]]
        ys = [b["accuracy"] for b in c["bins"]]
        sizes = [24 + 16 * math.sqrt(b["n"]) for b in c["bins"]]
        color = COND_COLORS.get(cond, TEXT_2)
        brier = "n/a" if math.isnan(c["brier"]) else f"{c['brier']:.2f}"
        ax.plot(xs, ys, color=color, linewidth=2, solid_capstyle="round", solid_joinstyle="round")
        ax.scatter(xs, ys, s=sizes, color=color, edgecolors=SURFACE, linewidths=2, zorder=3,
                   label=f"{COND_LABELS.get(cond, cond)} (Brier {brier}, n={c['n_findings']})")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_xlabel("Stated confidence (bin mean)", color=TEXT_2, fontsize=9)
    ax.set_ylabel("Share of findings that are correct", color=TEXT_2, fontsize=9)
    ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0))
    ax.set_title("Calibration of findings", loc="left", color=TEXT, fontsize=11, pad=10)
    ax.legend(frameon=False, labelcolor=TEXT_2, fontsize=8, loc="upper left", bbox_to_anchor=(1.02, 1))
    fig.text(0.01, 0.01, "Correct = matches the known bug; any finding on a control counts as wrong.\n"
             "Unmatched findings on bug cases are excluded. Marker area grows with findings per bin.",
             color=TEXT_2, fontsize=7)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    path = out / "calibration.png"
    fig.savefig(path, dpi=200, facecolor=SURFACE)
    plt.close(fig)
    return path


def draw(metrics: dict, out: Path) -> list[Path]:
    return [detection_chart(metrics, out), calibration_chart(metrics, out)]
