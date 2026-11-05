"""Metrics for one run directory: detection, false alarms, calibration. Writes metrics.json and summary.md.

Definitions (stated in the README):
  detection rate   share of bug cases where at least one finding matches the known bug (judge verdict)
  false-alarm rate share of control cases with at least one finding at confidence >= threshold
  calibration      per finding: label 1 = matches the known bug (bug cases), label 0 = any finding on a control.
                   Unmatched findings on bug cases are EXCLUDED: they may be other real bugs, so their truth is
                   unknown. Reported as reliability bins and a Brier score.
date split       detection and false alarms at conf >= 0 by merge date: before 2024 vs 2024+ (the dataset's era
                 preference), and before/after --cutoff (the reviewer's training cutoff) when one is given.
Reviews that failed (refusal, truncation, unparseable output) are excluded from rates and counted separately.
All rates come with 95% Wilson intervals; N is small, so intervals are wide.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

THRESHOLDS = (0.0, 0.5, 0.8)
CALIB_BINS = 5  # width 0.2: with a few dozen findings per condition, finer bins are mostly noise


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def rate(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"k": k, "n": n, "rate": k / n if n else math.nan, "ci95": [lo, hi]}


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []


def era_of(merged_at: str | None, cutoff: str | None) -> list[str]:
    if not merged_at:
        return ["unknown date"]
    day = merged_at[:10]
    eras = ["merged before 2024" if day < "2024-01-01" else "merged 2024+"]
    if cutoff:
        eras.append(f"merged before {cutoff}" if day < cutoff else f"merged on/after {cutoff}")
    return eras


def detected(r: dict, judgments: dict, t: float) -> bool:
    j = judgments.get((r["repo"], r["case"], r["condition"]))
    return any(r["findings"][i]["confidence"] >= t for i in (j["matched_finding_indices"] if j else []))


def excluded_cases() -> set[tuple[str, str]]:
    """Cases dropped after a run (status: exclude in data/<repo>/controls.yaml or curation.yaml), e.g. a control in
    which a real bug was found later, or a bug case the author rejected. Their stored reviews stay on disk but no
    longer count."""
    import yaml

    from .common import ROOT

    out = set()
    for repo_dir in sorted(p for p in (ROOT / "data").iterdir() if (p / "curation.yaml").exists()):
        repo = repo_dir.name
        controls = repo_dir / "controls.yaml"
        for c in yaml.safe_load(controls.read_text())["controls"] if controls.exists() else []:
            if c.get("status") == "exclude":
                out.add((repo, f"ctl-{c.get('control_pr') or c.get('short')}"))
        for b in yaml.safe_load((repo_dir / "curation.yaml").read_text())["bugs"]:
            if b.get("status") == "exclude":
                out.add((repo, f"bug-{b['culprit_pr']}" if repo == "angular" else f"bug-{b['culprit'][:10]}"))
    return out


def compute(run_dir: Path, cutoff: str | None = None) -> dict:
    excluded = excluded_cases()
    reviews = [r for r in read_jsonl(run_dir / "reviews.jsonl") if (r["repo"], r["case"]) not in excluded]
    judgments = {(j["repo"], j["case"], j["condition"]): j for j in read_jsonl(run_dir / "judgments.jsonl")}
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in reviews:
        for repo in (r["repo"], "all"):
            groups[(repo, r["condition"])].append(r)

    present = {(r["repo"], r["case"]) for r in read_jsonl(run_dir / "reviews.jsonl")}
    out: dict = {"excluded_cases": sorted(f"{repo}/{case}" for repo, case in excluded & present), "failed_reviews": [{k: r[k] for k in ("repo", "case", "condition", "error")}
                                    for r in reviews if r["findings"] is None], "groups": {}}
    calib_points = defaultdict(list)  # condition -> [(confidence, label)]
    for (repo, cond), rows in sorted(groups.items()):
        ok = [r for r in rows if r["findings"] is not None]
        bugs = [r for r in ok if r["kind"] == "bug"]
        ctls = [r for r in ok if r["kind"] == "control"]
        g = {"detection": {}, "false_alarm": {}, "findings_per_review": {}}
        for t in THRESHOLDS:
            g["detection"][str(t)] = rate(sum(detected(r, judgments, t) for r in bugs), len(bugs))
            g["false_alarm"][str(t)] = rate(sum(any(f["confidence"] >= t for f in r["findings"]) for r in ctls), len(ctls))
        g["findings_per_review"] = {
            "bug": sum(len(r["findings"]) for r in bugs) / len(bugs) if bugs else math.nan,
            "control": sum(len(r["findings"]) for r in ctls) / len(ctls) if ctls else math.nan,
        }
        out["groups"][f"{repo}/{cond}"] = g
        if repo == "all":
            for r in bugs:
                j = judgments.get((r["repo"], r["case"], cond))
                for i in (j["matched_finding_indices"] if j else []):
                    calib_points[cond].append((r["findings"][i]["confidence"], 1))
            for r in ctls:
                calib_points[cond] += [(f["confidence"], 0) for f in r["findings"]]

    by_era: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in reviews:
        if r["findings"] is not None:
            for era in era_of(r.get("merged_at"), cutoff):
                by_era[(era, r["condition"])].append(r)
    out["by_date"] = {
        f"{era}/{cond}": {
            "detection": rate(sum(detected(r, judgments, 0.0) for r in rows if r["kind"] == "bug"),
                              sum(r["kind"] == "bug" for r in rows)),
            "false_alarm": rate(sum(bool(r["findings"]) for r in rows if r["kind"] == "control"),
                                sum(r["kind"] == "control" for r in rows)),
        } for (era, cond), rows in sorted(by_era.items())}

    out["calibration"] = {}
    for cond, pts in sorted(calib_points.items()):
        bins = []
        for b in range(CALIB_BINS):
            lo, hi = b / CALIB_BINS, (b + 1) / CALIB_BINS
            inside = [(c, y) for c, y in pts if lo <= c < hi or (b == CALIB_BINS - 1 and c == 1.0)]
            if inside:
                bins.append({"bin": [lo, hi], "n": len(inside), "mean_confidence": sum(c for c, _ in inside) / len(inside),
                             "accuracy": sum(y for _, y in inside) / len(inside)})
        brier = sum((c - y) ** 2 for c, y in pts) / len(pts) if pts else math.nan
        out["calibration"][cond] = {"n_findings": len(pts), "brier": brier, "bins": bins}
    out["spend_usd"] = sum(r.get("cost_usd", 0) for r in reviews) + sum(j.get("cost_usd", 0) for j in judgments.values())
    return out


def fmt(r: dict) -> str:
    if r["n"] == 0:
        return "n/a"
    return f"{r['rate']:.0%} ({r['k']}/{r['n']}, CI {r['ci95'][0]:.0%}–{r['ci95'][1]:.0%})"


def report(run_dir: Path, cutoff: str | None = None) -> None:
    m = compute(run_dir, cutoff)
    (run_dir / "metrics.json").write_text(json.dumps(m, indent=2) + "\n")
    lines = [f"# Results: {run_dir.name}", ""]
    for title, key in (("Detection rate (bug cases)", "detection"), ("False-alarm rate (controls)", "false_alarm")):
        lines += [f"## {title}", "", "| repo/condition | " + " | ".join(f"conf ≥ {t}" for t in THRESHOLDS) + " |",
                  "|---|" + "---|" * len(THRESHOLDS)]
        for name, g in m["groups"].items():
            lines.append(f"| {name} | " + " | ".join(fmt(g[key][str(t)]) for t in THRESHOLDS) + " |")
        lines.append("")
    lines += ["## By merge date (all repos, any confidence)", "", "| era/condition | detection | false alarms |",
              "|---|---|---|"]
    lines += [f"| {k} | {fmt(v['detection'])} | {fmt(v['false_alarm'])} |" for k, v in m["by_date"].items()]
    lines.append("")
    lines += ["## Calibration (all repos)", "", "| condition | findings | Brier | bins (mean conf → accuracy, n) |",
              "|---|---|---|---|"]
    for cond, c in m["calibration"].items():
        bins = "; ".join(f"{b['mean_confidence']:.2f}→{b['accuracy']:.2f} ({b['n']})" for b in c["bins"])
        lines.append(f"| {cond} | {c['n_findings']} | {c['brier']:.3f} | {bins} |")
    lines += ["", f"Cases excluded after the run: {', '.join(m['excluded_cases']) or 'none'}",
              "", f"Failed reviews (excluded): {len(m['failed_reviews'])}",
              *[f"- {f['repo']}/{f['case']}/{f['condition']}: {f['error']}" for f in m["failed_reviews"]],
              "", f"Spend recorded in this run: ${m['spend_usd']:.2f}", ""]
    from .charts import draw
    charts = draw(m, run_dir)
    lines += ["## Charts", "", *[f"![{c.stem}]({c.name})" for c in charts], ""]
    (run_dir / "summary.md").write_text("\n".join(lines))
    print("\n".join(lines))


def ab_grid(run_base: str, title: str, repos: tuple[str, ...] | None = None, results: Path | None = None,
            conditions: tuple[str, str] = ("A", "B")) -> str:
    """Per-case A vs B hits over a run and its _sK repeats, as markdown: the grid, totals, per-sample totals, and a
    two-sided sign test over the cases where A and B differ. Excluded cases are left out."""
    from math import comb

    from .common import ROOT

    excluded = excluded_cases()
    import re

    results = results or ROOT / "results"
    first, second = conditions
    repeats = [d for d in results.glob(f"{run_base}_s*") if re.fullmatch(rf"{re.escape(run_base)}_s\d+", d.name)]
    dirs = [results / run_base] + sorted(repeats, key=lambda d: int(d.name.rsplit("_s", 1)[1]))
    hits: dict[tuple[str, str], dict[str, str]] = defaultdict(lambda: {first: "", second: ""})
    per_sample = []
    for d in dirs:
        judgments = {(j["repo"], j["case"], j["condition"]): j for j in read_jsonl(d / "judgments.jsonl")}
        sample_hits = {first: 0, second: 0}
        for r in read_jsonl(d / "reviews.jsonl"):
            if r["kind"] != "bug" or r["condition"] not in (first, second) or (r["repo"], r["case"]) in excluded \
                    or (repos and r["repo"] not in repos):
                continue
            hit = r["findings"] is not None and detected(r, judgments, 0.0)
            hits[(r["repo"], r["case"])][r["condition"]] += "x" if hit else "."
            sample_hits[r["condition"]] += hit
        per_sample.append(f"{sample_hits[first]}/{sample_hits[second]}")
    md = [f"## {title}", "", f"{len(hits)} bug cases × {len(dirs)} samples. `x` = the judge matched a finding to the "
          "known bug.", "", f"| case | {first} | {second} |", "|---|---|---|"]
    a_better = b_better = total_a = total_b = n = 0
    for (repo, case), cell in sorted(hits.items()):
        a, b = cell[first].count("x"), cell[second].count("x")
        total_a, total_b, n = total_a + a, total_b + b, n + len(cell[first])
        a_better += a > b
        b_better += b > a
        mark = f" **({first}>{second})**" if a > b else f" *({second}>{first})*" if b > a else ""
        md.append(f"| {repo}/{case}{mark} | `{cell[first]}` {a}/{len(cell[first])} | `{cell[second]}` {b}/{len(cell[second])} |")
    k, m = min(a_better, b_better), a_better + b_better
    p = min(1.0, 2 * sum(comb(m, i) for i in range(k + 1)) / 2 ** m) if m else 1.0
    md += [f"| **total** | **{total_a}/{n} = {total_a / n:.0%}** | **{total_b}/{n} = {total_b / n:.0%}** |", "",
           f"{first}/{second} hits per sample: {', '.join(per_sample)}. Cases where {first} > {second}: {a_better}; "
           f"{second} > {first}: {b_better}; "
           f"two-sided sign test p = {p:.3f}.", ""]
    return "\n".join(md)
