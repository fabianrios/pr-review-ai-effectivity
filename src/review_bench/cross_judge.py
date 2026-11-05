"""Second, independent judge for validating the first judge without a human expert.

A different model re-grades every stored judgment of a run and its repeats (results/<run>/ and results/<run>_sK/).
It sees the same input as the first judge plus the diff of the commit that fixed the bug (data/*/cases/*/fix.patch),
and never sees the first verdict. The verdicts go to crossjudgments.jsonl next to each judgments.jsonl, and the
agreement between the two judges, with every disagreement spelled out, to results/<run>/judge_agreement.md.
"""

from __future__ import annotations

import json
from pathlib import Path

from .common import ROOT
from .llm import PRICES, Client, response_text, spent_so_far
from .prompts import cross_judge_request, load_case

EXPECTED_OUTPUT_TOKENS = 700  # about twice the first judge's measured mean, as a margin for a more verbose model


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def run_dirs(base: str) -> list[Path]:
    results = ROOT / "results"
    return [results / base] + sorted(results.glob(f"{base}_s*"))


def cross_judge(base: str, model: str, effort: str, budget: float, workers: int, yes: bool) -> None:
    from .evaluate import run_pool, write_jsonl

    dirs = run_dirs(base)
    jobs = [(d, j) for d in dirs for j in read_jsonl(d / "judgments.jsonl")]
    cases = {(j["repo"], j["case"]): load_case(ROOT / "data" / j["repo"] / "cases" / j["case"]) for _, j in jobs}

    client = Client(budget)
    requests = [cross_judge_request(cases[(j["repo"], j["case"])], j["findings"], model, effort) for _, j in jobs]
    input_tokens = sum(client.count_tokens(model, r["system"], r["messages"]) for r in requests)
    price_in, price_out = PRICES[model]
    expected = input_tokens / 1e6 * price_in + len(jobs) * EXPECTED_OUTPUT_TOKENS / 1e6 * price_out
    worst = input_tokens / 1e6 * price_in + len(jobs) * 2000 / 1e6 * price_out
    print(f"{len(jobs)} judgments in {len(dirs)} run(s) to cross-judge with {model} at effort {effort}: "
          f"{input_tokens:,} input tokens, about ${expected:.2f} (${worst:.2f} if every answer is long).")
    if not yes:
        raise SystemExit("Not started. Re-run with --yes.")

    def judge_one(job_index: int) -> dict:
        run_dir, first = jobs[job_index]
        res = client.create(requests[job_index], tag=f"crossjudge:{first['repo']}/{first['case']}/{first['condition']}")
        try:
            verdict = json.loads(response_text(res.response))
            matched = sorted({i for i in verdict["matched_finding_indices"] if 0 <= i < len(first["findings"])})
            error = None
        except (json.JSONDecodeError, KeyError) as e:
            verdict, matched, error = {}, [], f"unparseable judge output: {e}"
        return {"run": run_dir.name, "repo": first["repo"], "case": first["case"], "condition": first["condition"],
                "judge_model": model, "matched_finding_indices": matched, "justification": verdict.get("justification"),
                "error": error, "cost_usd": res.cost_usd, "cached": res.cached}

    fresh = run_pool([(i,) for i in range(len(jobs))], judge_one, workers, "crossjudge")
    if len(fresh) < len(jobs):
        raise SystemExit("Stopped before every cross-judgment finished; nothing written.")
    for d in dirs:
        write_jsonl(d / "crossjudgments.jsonl",
                    sorted((r for r in fresh if r["run"] == d.name), key=lambda r: (r["repo"], r["case"], r["condition"])))
    agreement_report(base)
    print(f"${spent_so_far():.2f} spent in total.")


def agreement_report(base: str) -> None:
    dirs = run_dirs(base)
    rows = []
    for d in dirs:
        second = {(r["repo"], r["case"], r["condition"]): r for r in read_jsonl(d / "crossjudgments.jsonl")}
        for first in read_jsonl(d / "judgments.jsonl"):
            rows.append((d.name, first, second[(first["repo"], first["case"], first["condition"])]))

    caught = lambda j: bool(j["matched_finding_indices"])
    n = len(rows)
    both = sum(caught(a) and caught(b) for _, a, b in rows)
    neither = sum(not caught(a) and not caught(b) for _, a, b in rows)
    only_first = sum(caught(a) and not caught(b) for _, a, b in rows)
    only_second = n - both - neither - only_first
    observed = (both + neither) / n
    p_first, p_second = (both + only_first) / n, (both + only_second) / n
    chance = p_first * p_second + (1 - p_first) * (1 - p_second)
    kappa = (observed - chance) / (1 - chance) if chance < 1 else 1.0
    second_model = rows[0][2]["judge_model"]

    def angular_ab(pick) -> str:
        counts = {}
        for d in dirs:
            reviews = [r for r in read_jsonl(d / "reviews.jsonl") if r["repo"] == "angular" and r["kind"] == "bug"]
            verdicts = {(name, a["case"], a["condition"]): pick(a, b) for name, a, b in rows if name == d.name}
            for r in reviews:
                if r["condition"] in ("A", "B"):
                    hit, total = counts.get(r["condition"], (0, 0))
                    counts[r["condition"]] = (hit + bool(verdicts.get((d.name, r["case"], r["condition"]))), total + 1)
        return " vs ".join(f"{c} {counts[c][0]}/{counts[c][1]}" for c in ("A", "B"))

    md = [f"# Judge agreement: {base} and its repeats", "",
          f"The first judge ({rows[0][1]['judge_model']}) and an independent second judge ({second_model}) graded the "
          f"same {n} judgments. The second judge also saw the diff of the commit that fixed the bug and never saw the "
          "first verdict. \"Caught\" means the judge matched at least one finding to the known bug.", "",
          "| | second: caught | second: missed |", "|---|---|---|",
          f"| **first: caught** | {both} | {only_first} |", f"| **first: missed** | {only_second} | {neither} |", "",
          f"Agreement: **{both + neither}/{n} = {observed:.0%}**, Cohen's kappa {kappa:.2f}.", "",
          f"Angular A vs B over all samples: first judge {angular_ab(lambda a, b: caught(a))}; "
          f"second judge {angular_ab(lambda a, b: caught(b))}.", "", "## Disagreements", ""]
    for name, a, b in rows:
        if caught(a) == caught(b):
            continue
        md += [f"### {a['repo']}/{a['case']} condition {a['condition']} ({name})", "",
               f"**Known bug:** {a['ground_truth']}", "", "**Findings:**", ""]
        md += [f"{i}. `{f['file']}:{f['line']}` ({f['severity']}, conf {f['confidence']}): {f['description']}"
               for i, f in enumerate(a["findings"])]
        md += ["", f"**First judge:** matched {a['matched_finding_indices'] or 'none'}: {a['justification']}", "",
               f"**Second judge:** matched {b['matched_finding_indices'] or 'none'}: {b['justification']}", ""]
    out = ROOT / "results" / base / "judge_agreement.md"
    out.write_text("\n".join(md))
    print(f"Agreement {observed:.0%} (kappa {kappa:.2f}), {n - both - neither} disagreement(s). Wrote {out.relative_to(ROOT)}")
