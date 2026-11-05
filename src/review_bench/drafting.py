"""Draft new bug cases for the scale-up: find each candidate's fix, then let a model apply the inclusion rule and
draft a ground truth. Every accepted draft is later checked by a different model (`bench-eval gtcheck`) and signed
off by the author before it is evaluated.

  bench-eval draft            collect inputs (free) and print the cost of drafting
  bench-eval draft --yes      draft -> data/<repo>/drafts.jsonl and data/DRAFTS.md

Candidates: django, merged 2024+, diff <= 400 lines, and the fix deletes or rewrites lines the culprit added
(`line_overlap` > 0); angular, strong-signal candidates outside the docs sites (aio, adev) whose fix commit can be
found on main. Cases already in curation.yaml are skipped.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import yaml

from .common import ROOT
from .ground_truth import TEST_PATH
from .llm import PRICES, Client, response_text, spent_so_far

EXPECTED_OUTPUT_TOKENS = 1200

DRAFT_SYSTEM = """\
You curate a benchmark that tests whether code reviewers catch bugs. A candidate is a change (a pull request or
commit) that a later fix blames for a bug. You get the change's diff, the fix commit's message and diff (test files
left out), and the evidence that links them. Decide whether the candidate qualifies, and if so write its ground truth.

A candidate qualifies only if ALL of these hold:
1. The later fix (or its linked discussion) attributes the bug to this change, and the evidence agrees.
2. The faulty code is visibly present in this change's diff: the change adds or alters it. A bug that only shows up
   through code the change did not touch, or that pre-existed, does not qualify.
3. It is a behavioral defect: wrong result, crash, exception, broken API contract, security hole, data loss.
   Not: visual/CSS-only, docs, typing-only, test infrastructure, build tooling, performance-only, or a deliberate
   behavior change the project later reverted for policy reasons.
4. The bug can be described precisely from public information in these inputs.

Ground-truth style (it is what reviewers' findings are graded against): 3-6 sentences, plain technical English.
Name the faulty code in the change (function, condition, line), the mechanism, a concrete failing input or scenario,
and what the fix changed. Do not mention the fix commit id or ticket numbers. Example:

"The new `Query.orderby_issubset_groupby` property resolves every string in `order_by` with `F(order_by)`. Order-by
strings may carry a "-" prefix for descending order or be "?" for random order, which are not field names. So e.g.
`.values("is_staff").annotate(latest=Max(...)).order_by("-latest").count()` crashes with `FieldError: Cannot resolve
keyword '-latest' into field`. Fixed by stripping the "-" prefix and returning False for "?"."

bug_files: the files of the change that contain the faulty code. If the candidate does not qualify, give the reason
in one sentence and leave ground_truth empty.
"""

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "qualifies": {"type": "boolean"},
        "reason": {"type": "string"},
        "ground_truth": {"type": "string"},
        "bug_files": {"type": "array", "items": {"type": "string"}},
        "visible_in_change": {"type": "string", "enum": ["yes", "partly", "no"]},
    },
    "required": ["qualifies", "reason", "ground_truth", "bug_files", "visible_in_change"],
    "additionalProperties": False,
}


def git(repo: str, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(ROOT / "work" / repo), *args], capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else ""


def without_tests(diff: str, keep: set[str] = frozenset()) -> str:
    chunks = [c for c in re.split(r"(?m)^(?=diff --git )", diff) if c.startswith("diff --git")]
    path = lambda c: c.split()[2][2:]
    return "".join(c for c in chunks if path(c) in keep or not TEST_PATH.search(path(c)))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def django_inputs() -> list[dict]:
    used = {b["culprit"][:10] for b in yaml.safe_load((ROOT / "data/django/curation.yaml").read_text())["bugs"]}
    out = []
    for c in read_jsonl(ROOT / "data/django/candidates.jsonl"):
        if c["short"] in used or not c["size_ok"] or c["merged_at"] < "2024":
            continue
        fix = max(c["evidence"], key=lambda e: e["line_overlap"])
        if fix["line_overlap"] == 0:
            continue
        out.append({"repo": "django", "id": c["short"], "culprit": c["culprit"], "title": c["title"],
                    "merged_at": c["merged_at"], "fix_commit": fix["fix_commit"], "fix_message": fix["fix_message"],
                    "fix_tickets": fix["fix_tickets"], "evidence": f"Fix message says: {fix['fix_message']}",
                    "change_diff": git("django", "diff", c["base"], c["head"]),
                    "fix_diff": without_tests(git("django", "show", "--format=", fix["fix_commit"]))})
    return out


def angular_fix_commit(evidence: dict) -> str | None:
    if evidence["source"] == "git" and evidence.get("fix_subject"):
        sha = git("angular", "log", "origin/main", "-1", "--format=%H", "--fixed-strings",
                  f"--grep={evidence['fix_subject']}").strip()
        return sha or None
    if evidence["source"] == "issue" and evidence.get("issue"):
        n = evidence["issue"]
        log = git("angular", "log", "origin/main", "--format=%H %s", "-E",
                  f"--grep=(Fixes|Closes|Resolves|fixes|closes|resolves|fix|close) .*#{n}([^0-9]|$)")
        fixes = [line.split()[0] for line in log.splitlines() if re.match(r"\S+ fix", line)]
        return fixes[-1] if fixes else None  # the earliest fix that references the issue
    return None


def angular_inputs() -> list[dict]:
    used = {b["culprit_pr"] for b in yaml.safe_load((ROOT / "data/angular/curation.yaml").read_text())["bugs"]}
    out = []
    for c in read_jsonl(ROOT / "data/angular/candidates.jsonl"):
        if c["culprit_pr"] in used or not c["size_ok"] or not c["strong_signal"] or c["area"] in ("aio", "adev"):
            continue
        evidence = next(((e, sha) for e in c["evidence"] if (sha := angular_fix_commit(e))), None)
        if evidence is None:
            print(f"angular/{c['culprit_pr']}: no fix commit found on main, skipped")
            continue
        e, sha = evidence
        out.append(angular_record(c["culprit_pr"], c["title"], c["merged_at"], c["base"], c["head"], sha,
                                  f"{e['source']} {e.get('issue') or ''}: {e.get('snippet', '')}", e.get("issue")))
    return out


def angular_record(pr: int, title: str, merged_at: str, base: str, head: str, fix_sha: str, evidence: str,
                   issue: int | None) -> dict:
    return {"repo": "angular", "id": str(pr), "culprit_pr": pr, "title": title, "merged_at": merged_at,
            "fix_commit": fix_sha, "fix_message": git("angular", "show", "-s", "--format=%B", fix_sha),
            "issue": issue, "evidence": evidence, "change_diff": git("angular", "diff", base, head),
            "fix_diff": without_tests(git("angular", "show", "--format=", fix_sha))}


def ctl_56852_input() -> dict:
    """The former control whose real bug was found later (see data/CONTROLS_CHECK.md)."""
    case = ROOT / "data/angular/cases/ctl-56852/pr.json"
    pr = json.loads(case.read_text())
    return angular_record(56852, pr["title"], pr["merged_at"], pr["base_commit"], pr["head_commit"],
                          "36c2197539f7275a8688a073161435f56d880b9a",
                          "Found by bench-eval controlcheck: the fix deletes a line this change added.", 70044)


def draft_request(rec: dict, model: str, effort: str, system: str = DRAFT_SYSTEM) -> dict:
    text = (f"<change title=\"{rec['title']}\">\n{rec['change_diff']}\n</change>\n\n"
            f"<evidence>\n{rec['evidence']}\n</evidence>\n\n"
            f"<fix_message>\n{rec['fix_message']}\n</fix_message>\n\n<fix_diff>\n{rec['fix_diff']}\n</fix_diff>")
    return {"model": model, "max_tokens": 8000, "system": system, "messages": [{"role": "user", "content": text}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": DRAFT_SCHEMA}}}


def draft(model: str, effort: str, budget: float, workers: int, yes: bool) -> None:
    from .evaluate import run_pool, write_jsonl

    records = django_inputs() + angular_inputs() + [ctl_56852_input()]
    records = [r for r in records if r["change_diff"] and r["fix_diff"]]
    print(f"{sum(r['repo'] == 'django' for r in records)} django + {sum(r['repo'] == 'angular' for r in records)} "
          "angular candidates with a change diff and a fix diff.")
    client = Client(budget)
    requests = [draft_request(r, model, effort) for r in records]
    input_tokens = sum(client.count_tokens(model, q["system"], q["messages"]) for q in requests)
    price_in, price_out = PRICES[model]
    expected = input_tokens / 1e6 * price_in + len(records) * EXPECTED_OUTPUT_TOKENS / 1e6 * price_out
    worst = input_tokens / 1e6 * price_in + len(records) * 3000 / 1e6 * price_out
    print(f"Drafting with {model} at effort {effort}: {input_tokens:,} input tokens, about ${expected:.2f} "
          f"(${worst:.2f} if every answer is long).")
    if not yes:
        raise SystemExit("Not started. Re-run with --yes.")

    def draft_one(i: int) -> dict:
        rec = records[i]
        res = client.create(requests[i], tag=f"draft:{rec['repo']}/{rec['id']}")
        verdict = json.loads(response_text(res.response))
        meta = {k: v for k, v in rec.items() if k not in ("change_diff", "fix_diff", "fix_message")}
        return {**meta, "case": rec["id"], "condition": "-", "model": model, **verdict,
                "cost_usd": res.cost_usd, "cached": res.cached}

    rows = run_pool([(i,) for i in range(len(records))], draft_one, workers, "draft")
    if len(rows) < len(records):
        raise SystemExit("Stopped before every draft finished; nothing written.")
    for repo in ("django", "angular"):
        write_jsonl(ROOT / "data" / repo / "drafts.jsonl",
                    sorted((r for r in rows if r["repo"] == repo), key=lambda r: r["merged_at"]))
    accepted = [r for r in rows if r["qualifies"]]
    md = ["# Drafted bug cases for the scale-up", "",
          f"{model} applied the inclusion rule to {len(rows)} candidates and drafted ground truths: "
          f"{len(accepted)} qualify. Next: add them to curation.yaml, build the cases, run `bench-eval gtcheck`.", "",
          "| case | merged | qualifies | visible | reason |", "|---|---|---|---|---|"]
    md += [f"| {r['repo']}/{r['id']} | {r['merged_at'][:10]} | {'yes' if r['qualifies'] else 'no'} | "
           f"{r['visible_in_change']} | {r['reason']} |" for r in sorted(rows, key=lambda r: (r["repo"], r["merged_at"]))]
    (ROOT / "data" / "DRAFTS.md").write_text("\n".join(md) + "\n")
    print(f"{len(accepted)} of {len(rows)} qualify. Wrote data/DRAFTS.md. ${spent_so_far():.2f} spent in total.")


# ------------------------------------------------------------------------------------------- private repositories

INTERNAL_DRAFT_SYSTEM = DRAFT_SYSTEM.replace(
    "1. The later fix (or its linked discussion) attributes the bug to this change, and the evidence agrees.",
    "1. The fix was filed as a bug and rewrites code this change added (found by blame, not stated by anyone), and\n"
    "   the defect it fixes was actually introduced by this change - not merely code it touched, and not a later\n"
    "   change of requirements.",
).replace("4. The bug can be described precisely from public information in these inputs.",
          "4. The bug can be described precisely from these inputs.")


def internal_records() -> list[dict]:
    """One record per shortlisted culprit whose fix ticket is a Jira Bug, using its best-ranked fix."""
    from .mine_internal import INTERNAL, git as repo_git, is_code, shortlist

    cfg = yaml.safe_load((INTERNAL / "config.yaml").read_text())
    records = []
    for name, repo in cfg["repos"].items():
        path = Path(repo["path"])
        best = {}
        for c in read_jsonl(INTERNAL / name / "candidates.jsonl"):  # already ranked best-first
            if shortlist(c) and c["fix_strength"] == 3:
                best.setdefault(c["culprit_pr"], c)
        for c in best.values():
            fix_diff = repo_git(path, "diff", f"{c['fix_merge']}^1", c["fix_merge"])
            chunks = [x for x in re.split(r"(?m)^(?=diff --git )", fix_diff) if x.startswith("diff --git")]
            records.append({
                "repo": name, "id": str(c["culprit_pr"]), "culprit_pr": c["culprit_pr"], "merged_at": c["culprit_merged_at"],
                "title": c["culprit_title"] or "(no title in the merge message)", "fix_pr": c["fix_pr"],
                "fix_commit": c["fix_merge"], "fix_tickets": c["fix_tickets"],
                "fix_message": repo_git(path, "log", "-1", "--format=%B", c["fix_merge"]),
                "evidence": f"Blame: the fix rewrites {c['overlap']} non-trivial lines that this change added "
                            f"({c['overlap_share']:.0%} of the lines the fix rewrites). The fix's ticket is a Bug.",
                "change_diff": repo_git(path, "diff", f"{c['culprit_base']}...{c['culprit_head']}"),
                # only the fix's changes to code files the culprit also changed: that is where blame found it
                "fix_diff": "".join(x for x in chunks
                                    if is_code(x.split()[2][2:], repo) and x.split()[2][2:] in c["culprit_code_files"]),
            })
    return [r for r in records if r["change_diff"] and r["fix_diff"]]


def estimate_internal(records: list[dict], draft_model: str, check_model: str) -> None:
    """Offline estimate (~3.2 characters per token): nothing is sent anywhere."""
    from .llm import rough_tokens

    tokens = [rough_tokens(INTERNAL_DRAFT_SYSTEM) + rough_tokens(
        rec["change_diff"] + rec["fix_diff"] + rec["fix_message"] + rec["evidence"] + rec["title"]) for rec in records]
    total = sum(tokens)
    d_in, d_out = PRICES[draft_model]
    c_in, c_out = PRICES[check_model]
    draft_cost = total / 1e6 * d_in + len(records) * EXPECTED_OUTPUT_TOKENS / 1e6 * d_out
    draft_worst = total / 1e6 * d_in + len(records) * 3000 / 1e6 * d_out
    check_cost = total / 1e6 * c_in + len(records) * 1200 / 1e6 * c_out  # upper bound: every draft qualifies
    for repo in sorted({r["repo"] for r in records}):
        sel = [t for t, r in zip(tokens, records) if r["repo"] == repo]
        print(f"{repo:9} {len(sel):4} candidates, ~{sum(sel):,} input tokens (median {sorted(sel)[len(sel) // 2]:,})")
    print(f"Drafting ({draft_model}): about ${draft_cost:.2f} (${draft_worst:.2f} if every answer is long)")
    print(f"Checking ({check_model}, if all qualify): about ${check_cost:.2f}")


def draft_internal(model: str, check_model: str, effort: str, budget: float, workers: int, yes: bool) -> None:
    """Draft the private shortlist; qualifying drafts become case directories under internal/<repo>/cases/."""
    from .evaluate import run_pool, write_jsonl
    from .mine_internal import INTERNAL

    records = internal_records()
    estimate_internal(records, model, check_model)
    if not yes:
        raise SystemExit("Not started. Re-run with --yes.")
    client = Client(budget)
    requests = [draft_request(r, model, effort, INTERNAL_DRAFT_SYSTEM) for r in records]

    def draft_one(i: int) -> dict:
        rec = records[i]
        res = client.create(requests[i], tag=f"draft:internal/{rec['repo']}/{rec['id']}")
        if res.response.get("stop_reason") == "max_tokens":
            res = client.create({**requests[i], "max_tokens": 32000}, tag=f"draft:internal/{rec['repo']}/{rec['id']}#retry")
        try:
            verdict = json.loads(response_text(res.response))
        except json.JSONDecodeError:
            verdict = {"qualifies": False, "reason": f"no parseable answer (stop: {res.response.get('stop_reason')})",
                       "ground_truth": "", "bug_files": [], "visible_in_change": "no"}
        meta = {k: v for k, v in rec.items() if k not in ("change_diff", "fix_diff", "fix_message")}
        return {**meta, "case": rec["id"], "condition": "-", "model": model, **verdict,
                "cost_usd": res.cost_usd, "cached": res.cached}

    rows = run_pool([(i,) for i in range(len(records))], draft_one, workers, "draft")
    if len(rows) < len(records):
        raise SystemExit("Stopped before every draft finished; nothing written.")
    by_id = {(r["repo"], r["id"]): r for r in records}
    for repo in sorted({r["repo"] for r in rows}):
        write_jsonl(INTERNAL / repo / "drafts.jsonl", sorted((r for r in rows if r["repo"] == repo), key=lambda r: r["merged_at"]))
    for row in rows:
        case_dir = INTERNAL / row["repo"] / "cases" / f"bug-{row['id']}"
        if not row["qualifies"]:
            continue
        rec = by_id[(row["repo"], row["id"])]
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "diff.patch").write_text(rec["change_diff"])
        (case_dir / "fix.patch").write_text(rec["fix_diff"])
        (case_dir / "fix_message.txt").write_text(rec["fix_message"])
        (case_dir / "pr.json").write_text(json.dumps({"number": rec["culprit_pr"], "title": rec["title"],
                                                      "merged_at": rec["merged_at"], "description": None}, indent=2))
        (case_dir / "answer.json").write_text(json.dumps({
            "case_id": f"bug-{row['id']}", "kind": "bug", "ground_truth": row["ground_truth"], "bug_files": row["bug_files"],
            "fix_pr": rec["fix_pr"], "fix_commit": rec["fix_commit"], "fix_tickets": rec["fix_tickets"],
            "visible_in_change": row["visible_in_change"], "drafted_by": model}, indent=2))
    accepted = [r for r in rows if r["qualifies"]]
    md = ["# Internal drafts (git-ignored)", "", f"{model} applied the inclusion rule to {len(rows)} candidates: "
          f"{len(accepted)} qualify and became case directories (PR descriptions still to fetch).", "",
          "| case | merged | qualifies | visible | reason |", "|---|---|---|---|---|"]
    md += [f"| {r['repo']}/{r['id']} | {r['merged_at'][:10]} | {'yes' if r['qualifies'] else 'no'} | "
           f"{r['visible_in_change']} | {r['reason']} |" for r in sorted(rows, key=lambda r: (r["repo"], r["merged_at"]))]
    (INTERNAL / "DRAFTS.md").write_text("\n".join(md) + "\n")
    print(f"{len(accepted)} of {len(rows)} qualify. Wrote internal/DRAFTS.md. ${spent_so_far():.2f} spent in total.")
