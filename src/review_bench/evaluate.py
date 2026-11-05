"""Run the benchmark: review every case under conditions A/B/C, then judge reviews of bug cases.

  uv run bench-eval estimate [--count]          print the expected cost (no paid calls; --count uses the free
                                                 count_tokens endpoint for exact input tokens, needs the API key)
  uv run bench-eval run --pilot --yes           1 bug + 1 control per repo, all conditions: measures real usage
  uv run bench-eval run --yes                   everything
  uv run bench-eval report [--cutoff YYYY-MM-DD] metrics + charts -> results/<run>/summary.md, metrics.json, *.png
  uv run bench-eval audit [--n 12]              random sample of judge verdicts -> results/<run>/judge_audit.md
  uv run bench-eval crossjudge [--yes]          second judge with the fix diff over a run and its repeats
                                                 -> crossjudgments.jsonl, results/<run>/judge_agreement.md
  uv run bench-eval fetchfixes                  (free) fix commit diff + message per bug case -> data/*/cases/bug-*/
  uv run bench-eval controlcheck                (free) do later commits delete lines the controls added?
                                                 -> data/CONTROLS_CHECK.md
  uv run bench-eval draft [--yes]               scale-up: apply the inclusion rule to new candidates and draft
                                                 ground truths -> data/<repo>/drafts.jsonl, data/DRAFTS.md
  uv run bench-eval gtcheck [--yes]             model check of every ground truth against its fix commit
                                                 -> data/GROUND_TRUTH_CHECK.md

Repeats: --sample K (K >= 1) re-runs the same requests as an independent sample, cached separately and written to
results/<run>_sK/; --kinds bug restricts a run to bug cases.

Common options: --model (default claude-sonnet-5-5), --effort (default high), --judge-model (default
claude-opus-5-5), --budget (hard cap in USD over all paid calls ever made, default 10), --repos, --conditions.
A run never starts without --yes, and never spends past the budget cap.
Results (findings, verdicts, usage) go to results/<run>/; raw API responses stay in the git-ignored cache/.
"""

from __future__ import annotations

import argparse
import json
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .common import ROOT
from .llm import LEDGER, PRICES, BudgetExceeded, Client, cost_usd, is_cached, response_text, rough_tokens, spent_so_far
from .prompts import ALL_CONDITIONS, CONDITIONS, judge_request, load_case, review_request

REPOS = ("angular", "django")


def case_root(internal: bool) -> Path:
    """Public cases live in data/<repo>/cases; private ones in the git-ignored internal/<repo>/cases."""
    return ROOT / ("internal" if internal else "data")


def results_root(internal: bool) -> Path:
    """Results of private cases never go to results/ (which is committed): they go to internal/results/."""
    return ROOT / "internal" / "results" if internal else ROOT / "results"


def internal_repos() -> list[str]:
    import yaml

    return list(yaml.safe_load((ROOT / "internal" / "config.yaml").read_text())["repos"])
REVIEW_MAX_TOKENS = 16000  # non-streaming default; a truncated review is recorded as a failure, not dropped
DEFAULT_REVIEW_OUTPUT = 4000  # assumed output tokens per review until the ledger has measurements
DEFAULT_JUDGE_OUTPUT = 1500


def batch_case_ids(batch: str) -> set[str]:
    """Case ids of the bugs tagged `batch: <name>` and included in data/<repo>/curation.yaml."""
    import yaml

    ids = set()
    for repo in REPOS:
        for b in yaml.safe_load((ROOT / "data" / repo / "curation.yaml").read_text())["bugs"]:
            if b.get("batch") == batch and b.get("status") == "include":
                ids.add(f"bug-{b['culprit_pr']}" if repo == "angular" else f"bug-{b['culprit'][:10]}")
    return ids


def all_cases(repos: list[str], pilot: bool, kinds: list[str] | None = None,
              batch: str | None = None, internal: bool = False) -> list[tuple[str, dict]]:
    only = batch_case_ids(batch) if batch else None
    out = []
    for repo in repos:
        cases = [load_case(d) for d in sorted((case_root(internal) / repo / "cases").iterdir())]
        if pilot:  # first bug case and its matched control
            bug = next(c for c in cases if c["answer"]["kind"] == "bug")
            ctl = next(c for c in cases if c["answer"]["kind"] == "control"
                       and str(c["answer"]["matched_to"]) in bug["id"])
            cases = [bug, ctl]
        out += [(repo, c) for c in cases if (not kinds or c["answer"]["kind"] in kinds) and (not only or c["id"] in only)]
    return out


def run_name(args) -> str:
    base = args.name or f"{args.model}_effort-{args.effort}"
    return f"{base}_s{args.sample}" if args.sample else base


def measured_output(kind: str, model: str) -> float | None:
    if not LEDGER.exists():
        return None
    rows = [json.loads(line) for line in LEDGER.read_text().splitlines() if line.strip()]
    vals = [r["output_tokens"] for r in rows if r["tag"].startswith(kind + ":") and r["model"] == model]
    return statistics.mean(vals) if vals else None


# --------------------------------------------------------------------------------------------- estimate


def estimate(args, client: Client | None = None) -> float:
    cases = all_cases(args.repos, args.pilot, args.kinds, args.batch, args.internal)
    review_out = measured_output("review", args.model) or DEFAULT_REVIEW_OUTPUT
    judge_out = measured_output("judge", args.judge_model) or DEFAULT_JUDGE_OUTPUT
    rows, total = [], 0.0
    for repo in args.repos:
        for cond in args.conditions:
            n = new = tokens_in = 0
            for r, case in cases:
                if r != repo:
                    continue
                params = review_request(case, cond, args.model, args.effort, REVIEW_MAX_TOKENS)
                n += 1
                if is_cached(params, args.sample):
                    continue
                new += 1
                if client:
                    tokens_in += client.count_tokens(args.model, params["system"], params["messages"])
                else:
                    text = params["system"] + "".join(b["text"] for b in params["messages"][0]["content"])
                    tokens_in += rough_tokens(text)
            cost = cost_usd(args.model, tokens_in, int(new * review_out))
            total += cost
            rows.append((repo, cond, n, new, tokens_in, cost))
    n_bug_reviews = sum(1 for _, c in cases if c["answer"]["kind"] == "bug") * len(args.conditions)
    judge_cost = cost_usd(args.judge_model, n_bug_reviews * 9000, int(n_bug_reviews * judge_out))  # upper bound
    total += judge_cost

    method = "count_tokens (exact input)" if client else "offline estimate (~3.2 chars/token)"
    print(f"\nReviewer {args.model}, effort {args.effort}; judge {args.judge_model}. Input tokens: {method}.")
    print(f"Output tokens assumed per review: {review_out:,.0f} "
          f"({'measured' if measured_output('review', args.model) else 'default guess'}); "
          f"per judgment: {judge_out:,.0f}.\n")
    print(f"{'repo':8} {'cond':4} {'calls':>5} {'new':>4} {'input tok':>10} {'est. $':>8}")
    for repo, cond, n, new, tok, cost in rows:
        print(f"{repo:8} {cond:4} {n:5} {new:4} {tok:10,} {cost:8.2f}")
    print(f"{'judge':8} {'':4} {n_bug_reviews:5} {'':4} {'':10} {judge_cost:8.2f}  (upper bound: all bug reviews)")
    spent = spent_so_far()
    print(f"\nEstimated cost of this run: ${total:.2f}   already spent: ${spent:.2f}   budget cap: ${args.budget:.2f}")
    return total


# -------------------------------------------------------------------------------------------------- run


def parse_findings(response: dict) -> tuple[list[dict] | None, str | None]:
    if response.get("stop_reason") == "refusal":
        return None, f"refusal: {response.get('stop_details')}"
    if response.get("stop_reason") == "max_tokens":
        return None, "max_tokens"
    try:
        return json.loads(response_text(response))["findings"], None
    except (json.JSONDecodeError, KeyError) as e:
        return None, f"unparseable output: {e}"


def run(args) -> None:
    client = Client(args.budget)
    est = estimate(args, client)
    if spent_so_far() + est > args.budget:
        raise SystemExit(f"\nEstimate exceeds the remaining budget. Raise --budget only with the author's approval.")
    if not args.yes:
        raise SystemExit("\nNot started. Re-run with --yes to spend up to the estimate above.")

    out_dir = results_root(args.internal) / run_name(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    cases = all_cases(args.repos, args.pilot, args.kinds, args.batch, args.internal)
    jobs = [(repo, case, cond) for repo, case in cases for cond in args.conditions]

    def do_review(repo, case, cond):
        params = review_request(case, cond, args.model, args.effort, REVIEW_MAX_TOKENS)
        tag = f"review:{repo}/{case['id']}/{cond}" + (f"#s{args.sample}" if args.sample else "")
        res = client.create(params, tag=tag, sample=args.sample)
        findings, error = parse_findings(res.response)
        return {
            "repo": repo, "case": case["id"], "kind": case["answer"]["kind"], "condition": cond,
            "model": args.model, "effort": args.effort, "stop_reason": res.response.get("stop_reason"),
            "findings": findings, "error": error, "usage": res.response["usage"], "cost_usd": res.cost_usd,
            "cached": res.cached, "merged_at": case["pr"].get("merged_at"), "sample": args.sample,
        }

    reviews = run_pool(jobs, do_review, args.workers, "review")
    by_id = {(repo, c["id"]): c for repo, c in cases}

    def do_judge(rev):
        return judge_review(client, by_id[(rev["repo"], rev["case"])], rev, args.judge_model, args.judge_effort)

    to_judge = [r for r in reviews if r["kind"] == "bug" and r["findings"]]
    judgments = run_pool([(r,) for r in to_judge], do_judge, args.workers, "judge")

    write_jsonl(out_dir / "reviews.jsonl", sorted(reviews, key=lambda r: (r["repo"], r["case"], r["condition"])))
    write_jsonl(out_dir / "judgments.jsonl", sorted(judgments, key=lambda r: (r["repo"], r["case"], r["condition"])))
    (out_dir / "config.json").write_text(json.dumps({
        "model": args.model, "effort": args.effort, "judge_model": args.judge_model, "judge_effort": args.judge_effort,
        "conditions": args.conditions, "repos": args.repos, "pilot": args.pilot, "review_max_tokens": REVIEW_MAX_TOKENS,
        "sample": args.sample, "kinds": args.kinds,
    }, indent=2) + "\n")
    paid = sum(r["cost_usd"] for r in reviews) + sum(j["cost_usd"] for j in judgments)
    print(f"\nDone: {len(reviews)} reviews, {len(judgments)} judgments, ${paid:.2f} spent in this run "
          f"(${spent_so_far():.2f} in total). Results in {out_dir.relative_to(ROOT)}/")


def judge_review(client: Client, case: dict, rev: dict, judge_model: str, judge_effort: str) -> dict:
    params = judge_request(case, rev["findings"], judge_model, judge_effort)
    res = client.create(params, tag=f"judge:{rev['repo']}/{rev['case']}/{rev['condition']}")
    try:
        verdict = json.loads(response_text(res.response))
        matched = sorted({i for i in verdict["matched_finding_indices"] if 0 <= i < len(rev["findings"])})
        error = None
    except (json.JSONDecodeError, KeyError) as e:
        verdict, matched, error = {}, [], f"unparseable judge output: {e}"
    return {
        "repo": rev["repo"], "case": rev["case"], "condition": rev["condition"], "judge_model": judge_model,
        "matched_finding_indices": matched, "justification": verdict.get("justification"), "error": error,
        "stop_reason": res.response.get("stop_reason"), "cost_usd": res.cost_usd, "cached": res.cached,
        "ground_truth": case["answer"]["ground_truth"], "findings": rev["findings"],
    }


def rejudge(args) -> None:
    """Re-judge only the given cases from the stored reviews of an existing run; no review is re-run.

    Used after a ground-truth correction when the API cache is gone: the reviews in reviews.jsonl stay as they were,
    and only the matching rows of judgments.jsonl are replaced.
    """
    run_dir = results_root(args.internal) / run_name(args)
    config = json.loads((run_dir / "config.json").read_text())
    reviews = [json.loads(line) for line in (run_dir / "reviews.jsonl").read_text().splitlines() if line.strip()]
    judgments_path = run_dir / "judgments.jsonl"
    judgments = [json.loads(line) for line in judgments_path.read_text().splitlines() if line.strip()]

    to_judge = [r for r in reviews if r["case"] in args.cases and r["kind"] == "bug" and r["findings"]]
    if not to_judge:
        raise SystemExit(f"No judgeable reviews for {args.cases} in {run_dir.relative_to(ROOT)}.")
    print(f"{run_dir.relative_to(ROOT)}: {len(to_judge)} review(s) to re-judge with {config['judge_model']}")
    if not args.yes:
        raise SystemExit("Not started. Re-run with --yes.")

    client = Client(args.budget)
    cases = {(r["repo"], r["case"]): load_case(case_root(args.internal) / r["repo"] / "cases" / r["case"]) for r in to_judge}
    fresh = run_pool([(r,) for r in to_judge],
                     lambda rev: judge_review(client, cases[(rev["repo"], rev["case"])], rev,
                                              config["judge_model"], config["judge_effort"]),
                     args.workers, "rejudge")
    if len(fresh) < len(to_judge):
        raise SystemExit("Stopped before every re-judge finished; judgments.jsonl left unchanged.")

    kept = [j for j in judgments if j["case"] not in args.cases]
    write_jsonl(judgments_path, sorted(kept + fresh, key=lambda r: (r["repo"], r["case"], r["condition"])))
    for j in sorted(fresh, key=lambda r: r["condition"]):
        print(f"  {j['repo']}/{j['case']}/{j['condition']}: matched {j['matched_finding_indices'] or 'none'}")
    print(f"Replaced {len(fresh)} judgment(s); ${spent_so_far():.2f} spent in total. Re-run `report` for this run.")


def run_pool(jobs, fn, workers, label):
    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, *job): job for job in jobs}
        for i, fut in enumerate(as_completed(futures), 1):
            try:
                results.append(fut.result())
            except BudgetExceeded as e:
                print(f"STOP: {e}")
                pool.shutdown(cancel_futures=True)
                break
            r = results[-1]
            status = "cached" if r["cached"] else f"${r['cost_usd']:.3f}"
            print(f"[{label} {i}/{len(jobs)}] {r['repo']}/{r['case']}/{r['condition']} {status}", flush=True)
    return results


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def audit(run_dir: Path, n: int) -> None:
    """Write a fixed random sample of judge verdicts for manual checking (seeded, so the sample is reproducible)."""
    import random

    rows = [json.loads(line) for line in (run_dir / "judgments.jsonl").read_text().splitlines() if line.strip()]
    sample = random.Random(20261103).sample(rows, min(n, len(rows)))
    md = [f"# Judge audit: {run_dir.name} ({len(sample)} of {len(rows)} judgments, seed 20261103)", "",
          "For each item, decide yourself whether any finding matches the known bug, then compare with the judge.", ""]
    for j in sample:
        md += [f"## {j['repo']}/{j['case']} condition {j['condition']}", "", f"**Known bug:** {j['ground_truth']}", "",
               "**Findings:**", ""]
        md += [f"{i}. `{f['file']}:{f['line']}` ({f['severity']}, conf {f['confidence']}): {f['description']}"
               for i, f in enumerate(j["findings"])]
        md += ["", f"**Judge:** matched {j['matched_finding_indices'] or 'none'}: {j['justification']}", "",
               "**Your verdict:** ☐ agree ☐ disagree (note: ...)", ""]
    (run_dir / "judge_audit.md").write_text("\n".join(md))
    print(f"wrote {run_dir / 'judge_audit.md'}")


# ----------------------------------------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["estimate", "run", "rejudge", "report", "audit", "crossjudge", "fetchfixes", "controlcheck", "gtcheck", "draft"])
    ap.add_argument("--cases", nargs="+", help="rejudge: case ids whose judgments to replace, e.g. bug-60875")
    ap.add_argument("--n", type=int, default=12, help="audit: number of judgments to sample")
    ap.add_argument("--model", default="claude-sonnet-5-5", choices=sorted(PRICES))
    ap.add_argument("--effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--judge-model", default="claude-opus-5-5", choices=sorted(PRICES))
    ap.add_argument("--cross-judge-model", default="claude-fable-5-1", choices=sorted(PRICES),
                    help="crossjudge, gtcheck: the independent checking model")
    ap.add_argument("--judge-effort", default="high", choices=["low", "medium", "high", "xhigh", "max"])
    ap.add_argument("--repos", nargs="+", help=f"default: {' '.join(REPOS)} (with --internal: the repos in internal/config.yaml)")
    ap.add_argument("--conditions", nargs="+", default=list(CONDITIONS), choices=ALL_CONDITIONS)
    ap.add_argument("--budget", type=float, default=10.0, help="hard cap in USD over all paid calls (ledger total)")
    ap.add_argument("--pilot", action="store_true", help="1 bug + 1 matched control per repo")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sample", type=int, default=0, help="independent repeat index (0 = the original run)")
    ap.add_argument("--batch", help="run/estimate: only the bug cases tagged with this batch in curation.yaml")
    ap.add_argument("--kinds", nargs="+", choices=["bug", "control"], help="restrict to these case kinds")
    ap.add_argument("--count", action="store_true", help="estimate: exact input tokens via count_tokens (needs key)")
    ap.add_argument("--cutoff", help="report: reviewer training cutoff (YYYY-MM-DD) for the contamination split")
    ap.add_argument("--name", help="results/<name>/ (default: <model>_effort-<effort>)")
    ap.add_argument("--internal", action="store_true",
                    help="draft, gtcheck: the private repositories configured in internal/config.yaml (git-ignored)")
    ap.add_argument("--yes", action="store_true", help="actually spend money")
    args = ap.parse_args()
    valid = internal_repos() if args.internal else list(REPOS)
    args.repos = args.repos or valid
    if unknown := set(args.repos) - set(valid):
        ap.error(f"unknown repos {sorted(unknown)}; choose from {valid}")

    if args.command == "estimate":
        estimate(args, Client(args.budget) if args.count else None)
    elif args.command == "run":
        run(args)
    elif args.command == "rejudge":
        if not args.cases:
            raise SystemExit("rejudge needs --cases, e.g. --cases bug-60875")
        rejudge(args)
    elif args.command == "report":
        from .metrics import report
        report(results_root(args.internal) / run_name(args), args.cutoff)
    elif args.command == "crossjudge":
        from .cross_judge import cross_judge
        cross_judge(run_name(args), args.cross_judge_model, args.judge_effort, args.budget, args.workers, args.yes)
    elif args.command == "fetchfixes":
        from .ground_truth import fetch_fixes
        fetch_fixes()
    elif args.command == "controlcheck":
        from .ground_truth import control_check
        control_check()
    elif args.command == "draft" and args.internal:
        from .drafting import draft_internal
        draft_internal(args.judge_model, args.cross_judge_model, args.judge_effort, args.budget, args.workers, args.yes)
    elif args.command == "draft":
        from .drafting import draft
        draft(args.judge_model, args.judge_effort, args.budget, args.workers, args.yes)
    elif args.command == "gtcheck":
        from .ground_truth import check
        check(args.cross_judge_model, args.judge_effort, args.budget, args.workers, args.yes, args.internal)
    else:
        audit(results_root(args.internal) / run_name(args), args.n)


if __name__ == "__main__":
    main()
