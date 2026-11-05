"""Evidence for each bug case's label, without needing a human expert in the codebase.

  fetchfixes  (free) store each bug case's fix commit as fix.patch (test files left out, bug_files always kept)
              and fix_message.txt, from the GitHub API via `gh`.
  controlcheck (free) do later commits delete lines the controls added? -> data/CONTROLS_CHECK.md
  gtcheck     a model reads the culprit diff, the fix diff and message, and the written ground truth, and says
              whether the culprit introduced the bug and whether the ground truth describes it accurately.
              -> data/<repo>/ground_truth_check.jsonl and data/GROUND_TRUTH_CHECK.md
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from .common import ROOT
from .llm import PRICES, Client, response_text, spent_so_far
from .prompts import load_case

REPOS = ("angular", "django")
TEST_PATH = re.compile(r"(^|/)(tests?|docs)/|_spec\.ts$|\.spec\.ts$|(^|/)test_[^/]*\.py$|releases/")
EXPECTED_OUTPUT_TOKENS = 900

GT_SYSTEM = """\
You check one label in a benchmark of code reviews. Each label says that a change (a pull request or commit)
introduced a bug that a later commit fixed, and describes that bug in a short ground-truth text. Reviewers are later
graded against that text, so it must be right.

You get the change, the fix commit's message and diff (test files left out), and the ground-truth text. Decide:
1. introduced_by_change: is the defect present in the change itself (the change adds or alters the faulty code),
   rather than pre-existing or introduced by some other commit?
2. description_accurate: does the ground truth correctly describe the faulty code, the failure mechanism and what the
   fix does, without claims the evidence contradicts? Small imprecision is fine; a wrong mechanism is not.
3. visible_in_change: could a careful reviewer see the defect from the change alone ("yes"), only with knowledge of
   code outside the diff ("partly"), or not at all ("no")?
Then give a verdict: "ok" (all good), "minor" (usable, but something should be reworded or noted), or "problem"
(the label is wrong or misleading). Explain in plain language for a reader who does not know this codebase; quote the
code that decides it.
"""

GT_SCHEMA = {
    "type": "object",
    "properties": {
        "introduced_by_change": {"type": "boolean"},
        "description_accurate": {"type": "boolean"},
        "visible_in_change": {"type": "string", "enum": ["yes", "partly", "no"]},
        "verdict": {"type": "string", "enum": ["ok", "minor", "problem"]},
        "explanation": {"type": "string"},
    },
    "required": ["introduced_by_change", "description_accurate", "visible_in_change", "verdict", "explanation"],
    "additionalProperties": False,
}


def bug_case_dirs(internal: bool = False) -> list[tuple[str, Path]]:
    """(repo, case dir) of every bug case; with internal=True the private cases under internal/<repo>/cases/."""
    if internal:
        return [(d.parent.parent.name, d) for d in sorted((ROOT / "internal").glob("*/cases/bug-*"))]
    return [(repo, d) for repo in REPOS for d in sorted((ROOT / "data" / repo / "cases").glob("bug-*"))]


def gh_api(path: str, accept: str | None = None) -> str:
    cmd = ["gh", "api", path] + (["-H", f"Accept: {accept}"] if accept else [])
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout


def fetch_fixes() -> None:
    for repo, case_dir in bug_case_dirs():
        answer = json.loads((case_dir / "answer.json").read_text())
        commit_path = f"repos/{repo}/{repo}/commits/{answer['fix_commit']}"
        chunks = [c for c in re.split(r"(?m)^(?=diff --git )", gh_api(commit_path, "application/vnd.github.diff"))
                  if c.startswith("diff --git")]
        path_of = lambda chunk: chunk.split()[2][2:]
        kept = [c for c in chunks if path_of(c) in answer["bug_files"] or not TEST_PATH.search(path_of(c))]
        (case_dir / "fix.patch").write_text("".join(kept))
        (case_dir / "fix_message.txt").write_text(json.loads(gh_api(commit_path))["commit"]["message"])
        print(f"{repo}/{case_dir.name}: kept {[path_of(c) for c in kept]}")


def gt_request(case: dict, model: str, effort: str) -> dict:
    d = case["dir"]
    text = (f"<change>\n{case['diff']}\n</change>\n\n"
            f"<fix_message>\n{(d / 'fix_message.txt').read_text()}\n</fix_message>\n\n"
            f"<fix_diff>\n{(d / 'fix.patch').read_text()}\n</fix_diff>\n\n"
            f"<ground_truth>\n{case['answer']['ground_truth']}\n</ground_truth>")
    return {"model": model, "max_tokens": 8000, "system": GT_SYSTEM, "messages": [{"role": "user", "content": text}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": GT_SCHEMA}}}


def check(model: str, effort: str, budget: float, workers: int, yes: bool, internal: bool = False) -> None:
    from .evaluate import run_pool, write_jsonl

    base = ROOT / ("internal" if internal else "data")
    cases = [(repo, load_case(d)) for repo, d in bug_case_dirs(internal)]
    client = Client(budget)
    requests = [gt_request(case, model, effort) for _, case in cases]
    input_tokens = sum(client.count_tokens(model, r["system"], r["messages"]) for r in requests)
    price_in, price_out = PRICES[model]
    expected = input_tokens / 1e6 * price_in + len(cases) * EXPECTED_OUTPUT_TOKENS / 1e6 * price_out
    worst = input_tokens / 1e6 * price_in + len(cases) * 3000 / 1e6 * price_out
    print(f"{len(cases)} bug cases to check with {model} at effort {effort}: {input_tokens:,} input tokens, "
          f"about ${expected:.2f} (${worst:.2f} if every answer is long).")
    if not yes:
        raise SystemExit("Not started. Re-run with --yes.")

    def check_one(i: int) -> dict:
        repo, case = cases[i]
        res = client.create(requests[i], tag=f"gtcheck:{repo}/{case['id']}")
        if res.response.get("stop_reason") == "max_tokens":  # thinking used the whole budget: retry once, larger
            res = client.create({**requests[i], "max_tokens": 32000}, tag=f"gtcheck:{repo}/{case['id']}#retry")
        try:
            verdict = json.loads(response_text(res.response))
        except json.JSONDecodeError:
            verdict = {"introduced_by_change": False, "description_accurate": False, "visible_in_change": "no",
                       "verdict": "problem", "explanation": f"no parseable answer (stop: {res.response.get('stop_reason')})"}
        return {"repo": repo, "case": case["id"], "condition": "-", "model": model, **verdict,
                "cost_usd": res.cost_usd, "cached": res.cached}

    rows = run_pool([(i,) for i in range(len(cases))], check_one, workers, "gtcheck")
    if len(rows) < len(cases):
        raise SystemExit("Stopped before every check finished; nothing written.")
    rows.sort(key=lambda r: (r["repo"], r["case"]))
    for repo in sorted({r["repo"] for r in rows}):
        write_jsonl(base / repo / "ground_truth_check.jsonl", [r for r in rows if r["repo"] == repo])
    write_report(rows, model, base / "GROUND_TRUTH_CHECK.md")
    print(f"${spent_so_far():.2f} spent in total.")


def write_report(rows: list[dict], model: str, out: Path) -> None:
    counts = {v: sum(r["verdict"] == v for r in rows) for v in ("ok", "minor", "problem")}
    md = ["# Ground-truth check", "",
          f"{model} read each bug case's change, the fix commit (message and diff, test files left out) and the "
          "written ground truth, and judged whether the change introduced the bug and whether the text describes it "
          f"accurately. Verdicts: {counts['ok']} ok, {counts['minor']} minor, {counts['problem']} problem.", "",
          "| case | introduced by change | description accurate | visible in change | verdict |", "|---|---|---|---|---|"]
    yes_no = lambda b: "yes" if b else "**no**"
    md += [f"| {r['repo']}/{r['case']} | {yes_no(r['introduced_by_change'])} | {yes_no(r['description_accurate'])} | "
           f"{r['visible_in_change']} | {r['verdict'] if r['verdict'] == 'ok' else '**' + r['verdict'] + '**'} |"
           for r in rows]
    md += ["", "## Explanations", ""]
    md += [f"### {r['repo']}/{r['case']}: {r['verdict']}\n\n{r['explanation']}\n" for r in rows]
    out.write_text("\n".join(md))
    print(f"{counts}. Wrote {out.relative_to(ROOT)}")


CONTROL_SKIP_PATH = re.compile(TEST_PATH.pattern + r"|(^|/)testing/|goldens/|yarn\.lock$|\.bazel$")


def added_source_lines(diff: str) -> dict[str, list[str]]:
    """Non-trivial lines a diff adds to non-test files, by path."""
    added, path = {}, None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
        elif line.startswith("+") and not line.startswith("+++") and path and not CONTROL_SKIP_PATH.search(path):
            if len(line[1:].strip()) > 12:
                added.setdefault(path, []).append(line[1:].strip())
    return added


def control_check() -> None:
    """(free) For each control: how many of its added source lines are still on main, and which later commits
    deleted any of them. A later bug fix that deletes a control's lines would mean the control had a bug."""
    import base64

    md = ["# Control check", "",
          "For each control: the share of its added source lines still present on `main`, and every later commit "
          "that deleted at least one of them. Deletions by refactors are expected; a bug fix deleting a control's "
          "own lines would mean the control is not \"no known bug\". Generated by `bench-eval controlcheck`.", ""]
    for repo in REPOS:
        for case_dir in sorted((ROOT / "data" / repo / "cases").glob("ctl-*")):
            added = added_source_lines((case_dir / "diff.patch").read_text())
            all_added = {line for lines in added.values() for line in lines}
            on_main = 0
            for path, lines in added.items():
                try:
                    content = json.loads(gh_api(f"repos/{repo}/{repo}/contents/{path}?ref=main"))["content"]
                    present = {l.strip() for l in base64.b64decode(content).decode(errors="replace").splitlines()}
                except subprocess.CalledProcessError:
                    present = set()
                on_main += sum(line in present for line in lines)
            total = sum(len(lines) for lines in added.values())
            md += [f"## {repo}/{case_dir.name}: {on_main}/{total} added lines still on main", ""]
            if on_main == total:
                continue
            pr = json.loads((case_dir / "pr.json").read_text())
            since = pr.get("merged_at") or pr.get("date")
            later = {}
            for path in added:
                for commit in json.loads(gh_api(f"repos/{repo}/{repo}/commits?path={path}&since={since}&per_page=100")):
                    later.setdefault(commit["sha"], commit["commit"]["message"].split("\n")[0])
            for sha, title in later.items():
                diff = gh_api(f"repos/{repo}/{repo}/commits/{sha}", "application/vnd.github.diff")
                removed = {l[1:].strip() for l in diff.splitlines() if l.startswith("-") and not l.startswith("---")}
                if hits := len(all_added & removed):
                    md.append(f"- `{sha[:10]}` deletes {hits}: {title}")
            md.append("")
    out = ROOT / "data" / "CONTROLS_CHECK.md"
    out.write_text("\n".join(md))
    print(f"Wrote {out.relative_to(ROOT)}")
