"""Step 3: pick one matched control PR per verified bug case.

A control is a merged angular/angular PR with no known follow-up bug. For each bug case we look for a PR that
  * has the same `area: ...` label (falls back to the same top-level directory),
  * was merged within roughly a year of the bug PR, and at least 180 days before today (time for bugs to surface),
  * has a similar diff size (0.5x to 2x, never above MAX_DIFF_LINES),
  * is not itself a known culprit (data/candidates.jsonl),
  * is not referenced later by a fix/revert commit or by any issue or fix PR on GitHub.
Absence of evidence is not proof of correctness: controls are "no known bug", and the writeup says so.

Usage:  uv run bench-controls [--today 2026-11-03]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re

import yaml

from .common import (DATA, MAX_DIFF_LINES, REPO, diff_stats, gh_search_all, git, landed_on_main, pr_diff_range,
                     pr_info, read_jsonl, references_to)
from .mine import area_of

TYPE_RE = re.compile(r"^(fix|feat|refactor|perf)\(")
BAD_REF_RE = re.compile(r"^(fix|revert)|regress|broke|bug", re.IGNORECASE)


def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def later_bad_commits(number: int) -> list[str]:
    """Fix/revert commits on main that mention #N, excluding the PR's own landing commit(s)."""
    log = git("log", "-E", f"--grep=#{number}([^0-9]|$)", "--format=%h %s%x00%b%x01", "origin/main")
    bad = []
    for entry in log.split("\x01"):
        if "\x00" not in entry:
            continue
        head, body = entry.strip().split("\x00", 1)
        sha, subject = head.split(" ", 1)
        own = subject.rstrip().endswith(f"(#{number})") or re.search(rf"^PR Close #{number}\s*$", body, re.M)
        if not own and BAD_REF_RE.search(subject):
            bad.append(f"{sha} {subject}")
    return bad


def vet(number: int, merged_at: str) -> str | None:
    """Return a rejection reason, or None if the PR looks clean."""
    bad = later_bad_commits(number)
    if bad:
        return f"later commit mentions it: {bad[0]}"
    for ref in references_to(number):
        if day(ref["created_at"]) < day(merged_at):
            continue
        if "pull_request" not in ref:
            return f"referenced by issue #{ref['number']}"
        if BAD_REF_RE.search(ref["title"]):
            return f"referenced by PR #{ref['number']} {ref['title'][:50]}"
    return None


def find_control(bug: dict, culprits: set[int], taken: set[int], today: dt.date,
                 relaxed: bool = False) -> tuple[dict | None, list[str]]:
    """relaxed=True matches area on the top-level directory only (e.g. any packages/*)."""
    merged = day(bug["merged_at"])
    lo = merged - dt.timedelta(days=365)
    hi = min(merged + dt.timedelta(days=180), today - dt.timedelta(days=180))
    if hi < lo:
        hi = lo + dt.timedelta(days=30)
    areas = [lab for lab in bug["labels"] if lab.startswith("area: ")]
    label_q = f' label:"{areas[0]}"' if areas else ""
    items = gh_search_all(f"repo:{REPO} is:pr is:closed closed:{lo}..{hi}{label_q}", max_pages=2)
    if label_q:  # fallback pool: same window, any label (area is still matched by directory below)
        items += gh_search_all(f"repo:{REPO} is:pr is:closed closed:{lo}..{hi}", max_pages=2)
    seed = f"control-for-{bug['culprit_pr']}"
    items.sort(key=lambda i: hashlib.sha256(f"{seed}-{i['number']}".encode()).hexdigest())

    size = bug["changed_lines"]
    size_lo, size_hi = max(5, size // 2), min(MAX_DIFF_LINES, size * 2)
    log = []
    for item in items:
        n = item["number"]
        if n in culprits or n in taken or not TYPE_RE.match(item["title"]):
            continue
        if not (item.get("pull_request") or {}).get("merged_at") and not landed_on_main(n):
            continue  # closed without landing; checked before the (slow) fetch
        rng = pr_diff_range(n)
        if rng is None:
            continue
        stats = diff_stats(*rng)
        paths = [f["path"] for f in stats["files"]]
        if not size_lo <= stats["changed_lines"] <= size_hi:
            continue
        same = (area_of(paths).split("/")[0] == bug["area"].split("/")[0]) if relaxed else area_of(paths) == bug["area"]
        if not same:
            log.append(f"#{n}: area {area_of(paths)} != {bug['area']}")
            continue
        info = pr_info(n)
        if not info or not info["merged_at"]:
            continue  # closed without landing
        reason = vet(n, info["merged_at"])
        if reason:
            log.append(f"#{n}: rejected, {reason}")
            continue
        return {
            "control_pr": n, "url": info["url"], "title": info["title"], "merged_at": info["merged_at"],
            "matched_to": bug["culprit_pr"], "area": bug["area"], "changed_lines": stats["changed_lines"],
            "labels": info["labels"], "area_match": "top-level dir only" if relaxed else "exact",
        }, log
    return None, log


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--today", default=dt.date.today().isoformat())
    args = ap.parse_args()
    today = dt.date.fromisoformat(args.today)

    candidates = {c["culprit_pr"]: c for c in read_jsonl(DATA / "candidates.jsonl")}
    curation = yaml.safe_load((DATA / "curation.yaml").read_text())
    bugs = [b for b in curation["bugs"] if b.get("status") == "include"]
    culprits = set(candidates)

    out, taken = [], set()
    for b in bugs:
        bug = candidates[b["culprit_pr"]]
        control, log = find_control(bug, culprits, taken, today)
        if control is None:
            control, log2 = find_control(bug, culprits, taken, today, relaxed=True)
            log += log2
        for line in log:
            print("   ", line)
        if control is None:
            print(f"!! no control found for #{bug['culprit_pr']}")
            continue
        taken.add(control["control_pr"])
        out.append(control)
        print(f"#{bug['culprit_pr']} -> control #{control['control_pr']} ({control['changed_lines']} lines) {control['title'][:60]}")

    header = "# Generated by `uv run bench-controls`. Edit by hand only to drop a control (status: exclude).\n"
    (DATA / "controls.yaml").write_text(header + yaml.safe_dump({"controls": out}, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
