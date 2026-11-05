"""Step 1: discover candidate bug-introducing PRs in angular/angular.

Evidence sources (each yields: culprit PR number + where the claim was made + a text snippet):
  1. git    – commit messages in the local clone ("regression introduced by #123", "broken in #123", reverts)
  2. pr     – bodies of merged PRs found with GitHub search for the same phrases
  3. issue  – issue comments found with GitHub search (text-match fragments)

Every culprit PR is then fetched (refs/pull/N/head), measured, and written to data/candidates.jsonl.
Nothing here decides whether a candidate is a real bug: that is done by hand in data/curation.yaml.

Usage:  uv run bench-mine [--since 2021-01-01]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict

from .common import CLONE, DATA, MAX_DIFF_LINES, REPO, diff_stats, gh_search_all, git, pr_diff_range, pr_info, write_json

# "caused by #123", "regression introduced in #123", "accidentally broken in #123", ".../angular/angular/pull/123"
REF_RE = re.compile(
    r"\b(caused|introduced|regress\w*|broke\w*)\b[^#\n]{0,40}?(?:#|github\.com/angular/angular/pull/)(\d{4,6})\b",
    re.IGNORECASE,
)
STRONG_RE = re.compile(r"regress|broke|broken|bug|caused|accidental", re.IGNORECASE)

GIT_GREP = r"(caused|introduced|regress\w*|broke\w*)[^#]{0,40}(#|angular/angular/pull/)[0-9]{4,6}"
PR_QUERIES = ['"introduced in #"', '"introduced by #"', '"caused by #"', '"regression from #"',
              '"broke in #"', '"broken in #"', '"broken by #"', '"regression introduced"', '"regressed in #"']
ISSUE_QUERIES = ['"caused by #"', '"introduced in #"', '"introduced by #"', '"regression from #"', '"broken by #"']


def refs_in(text: str) -> list[tuple[int, str]]:
    """(culprit number, snippet) for every bug-origin reference in a piece of text."""
    out = []
    for m in REF_RE.finditer(text):
        start, end = max(0, m.start() - 120), min(len(text), m.end() + 120)
        out.append((int(m.group(2)), " ".join(text[start:end].split())))
    return out


def from_git(since: str) -> list[dict]:
    log = git("log", f"--since={since}", "-E", "-i", f"--grep={GIT_GREP}", "--format=%H%x00%B%x01", "origin/main")
    ev = []
    for entry in log.split("\x01"):
        if "\x00" not in entry:
            continue
        sha, msg = entry.strip().split("\x00", 1)
        subject = msg.strip().splitlines()[0]
        own = {int(n) for n in re.findall(r"\(#(\d+)\)|PR Close #(\d+)", msg) for n in n if n}
        for num, snip in refs_in(msg):
            if num in own:
                continue  # e.g. "docs: fix broken link (#123)" refers to itself
            ev.append({"source": "git", "fix_commit": sha, "fix_subject": subject, "culprit": num, "snippet": snip})
    # Reverts that name the reverted PR in the subject: Revert "fix(core): foo (#123)"
    reverts = git("log", f"--since={since}", "--grep=^This reverts commit", "--format=%H%x00%s", "origin/main")
    for line in reverts.splitlines():
        sha, subject = line.split("\x00", 1)
        m = re.match(r'Revert ".*\(#(\d{4,6})\)"', subject)
        if m:
            ev.append({"source": "revert", "fix_commit": sha, "fix_subject": subject,
                       "culprit": int(m.group(1)), "snippet": subject})
    return ev


def from_pr_search(since: str) -> list[dict]:
    ev = []
    for q in PR_QUERIES:
        for item in gh_search_all(f"repo:{REPO} is:pr is:merged {q} created:>={since}"):
            for num, snip in refs_in(item.get("body") or ""):
                ev.append({"source": "pr", "fix_pr": item["number"], "fix_subject": item["title"],
                           "culprit": num, "snippet": snip})
    return ev


def from_issue_search(since: str) -> list[dict]:
    ev = []
    for q in ISSUE_QUERIES:
        for item in gh_search_all(f"repo:{REPO} is:issue {q} in:comments created:>={since}", text_match=True):
            for tm in item.get("text_matches", []):
                for num, snip in refs_in(tm.get("fragment", "")):
                    ev.append({"source": "issue", "issue": item["number"], "fix_subject": item["title"],
                               "culprit": num, "snippet": snip})
    return ev


def area_of(paths: list[str]) -> str:
    """Coarse area: packages/<name>, adev, devtools, ... (most common top-level component)."""
    counts: dict[str, int] = defaultdict(int)
    for p in paths:
        parts = p.split("/")
        counts["/".join(parts[:2]) if parts[0] in ("packages", "devtools") else parts[0]] += 1
    return max(counts, key=counts.get) if counts else "?"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", default="2021-01-01")
    args = ap.parse_args()
    if not (CLONE / ".git").exists() and not (CLONE / "HEAD").exists():
        raise SystemExit(f"No clone at {CLONE}. Run: git clone --filter=blob:none https://github.com/{REPO} {CLONE}")

    evidence = from_git(args.since) + from_pr_search(args.since) + from_issue_search(args.since)
    by_culprit: dict[int, list[dict]] = defaultdict(list)
    for e in evidence:
        if e["culprit"] not in (e.get("fix_pr"), e.get("issue")):  # drop self-references
            by_culprit[e["culprit"]].append(e)
    print(f"{len(evidence)} evidence snippets -> {len(by_culprit)} distinct culprit numbers", flush=True)

    funnel = defaultdict(int)
    candidates = []
    for i, (num, evs) in enumerate(sorted(by_culprit.items(), reverse=True)):
        funnel["culprit_numbers"] += 1
        info = pr_info(num)
        if info is None:
            funnel["not_a_pr"] += 1  # e.g. the number is an issue
            continue
        if not info["merged_at"]:
            funnel["not_merged"] += 1
            continue
        rng = pr_diff_range(num)
        if rng is None:
            funnel["no_head_ref"] += 1
            continue
        stats = diff_stats(*rng)
        paths = [f["path"] for f in stats["files"]]
        size_ok = 0 < stats["changed_lines"] <= MAX_DIFF_LINES
        funnel["merged_pr_fetched"] += 1
        funnel["size_ok" if size_ok else "too_large_or_empty"] += 1
        candidates.append({
            "culprit_pr": num, "url": info["url"], "title": info["title"], "merged_at": info["merged_at"],
            "labels": info["labels"], "base": rng[0], "head": rng[1],
            "changed_lines": stats["changed_lines"], "n_files": len(paths), "area": area_of(paths),
            "size_ok": size_ok,
            "strong_signal": any(STRONG_RE.search(e["snippet"]) for e in evs),
            "sources": sorted({e["source"] for e in evs}),
            "evidence": evs,
        })
        print(f"[{i + 1}/{len(by_culprit)}] #{num} {stats['changed_lines']:>5} lines  {info['title'][:70]}", flush=True)

    candidates.sort(key=lambda c: (not c["size_ok"], not c["strong_signal"], c["merged_at"]), reverse=False)
    DATA.mkdir(exist_ok=True)
    with open(DATA / "candidates.jsonl", "w") as fh:
        for c in candidates:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    write_json(DATA / "mining_funnel.json", {"since": args.since, "evidence_snippets": len(evidence), **funnel})
    print(dict(funnel))


if __name__ == "__main__":
    main()
