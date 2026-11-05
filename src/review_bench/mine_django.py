"""Mine bug cases and controls from django/django.

Django's fixers follow a strict convention: a fix for a regression says which commit caused it,
e.g. "Fixed #37403 -- Fixed JSONField __in crash ... \n\nRegression in 9b8e4c6d7d47f7b2e96817ba334e9fd53c10a0df."
So the culprit is an exact commit, not a phrase to interpret. Django lands each change as one commit on main,
so the reviewed diff is that commit (sha^..sha).

  discover  -> data/django/candidates.jsonl, data/django/mining_funnel.json
  controls  -> data/django/controls.yaml          (needs data/django/curation.yaml)

Usage:
  uv run bench-mine-django discover [--since 2024-01-01]
  uv run bench-mine-django controls [--today 2026-11-03]
Then `BENCH_REPO=django/django uv run bench-cases` and `... bench-checkpoint`.
"""

from __future__ import annotations

import os

os.environ.setdefault("BENCH_REPO", "django/django")

import argparse  # noqa: E402
import datetime as dt  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
from collections import defaultdict  # noqa: E402

import yaml  # noqa: E402

from .common import DATA, MAX_DIFF_LINES, REPO, diff_stats, gh_search, git, read_jsonl, write_json  # noqa: E402

SHA = r"[0-9a-f]{7,40}"
REGRESSION_RE = re.compile(rf"Regression in ((?:{SHA})(?:\s*(?:,|and|&)\s*{SHA})*)", re.IGNORECASE)
TICKET_RE = re.compile(r"(?:Fixed|Refs) #(\d+)")
CODE_PREFIX = "django/"  # shipped code; tests/ and docs/ are not
BUGFIX_RE = re.compile(r"\b(fix|fixes|fixed|bug|crash|regression|incorrect|wrong)\b", re.IGNORECASE)


def is_code(path: str) -> bool:
    return path.startswith(CODE_PREFIX) and "/locale/" not in path


def area_of(paths: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for p in paths:
        if is_code(p):
            parts = p.split("/")
            counts["/".join(parts[:3]) if parts[1] == "contrib" else "/".join(parts[:2])] += 1
    return max(counts, key=counts.get) if counts else "non-code"


def commit_info(sha: str) -> dict:
    raw = git("show", "-s", "--format=%H%x00%aI%x00%an%x00%P%x00%B", sha)
    full, date, author, parents, message = raw.split("\x00", 4)
    return {"sha": full, "date": date, "author": author, "n_parents": len(parents.split()),
            "subject": message.strip().splitlines()[0], "message": message.strip(),
            "tickets": sorted({int(t) for t in TICKET_RE.findall(message)})}


def changed_lines(sha: str, sign: str, code_only: bool = True) -> set[str]:
    """Stripped non-trivial lines added ('+') or removed ('-') by a commit."""
    out, path = set(), ""
    for line in git("show", "--format=", "-U0", sha).splitlines():
        if line.startswith("+++ ") or line.startswith("--- "):
            if line.startswith("+++ "):
                path = line[6:] if line.startswith("+++ b/") else ""
            continue
        if line.startswith(sign) and (not code_only or is_code(path)):
            text = line[1:].strip()
            if len(text) >= 12 and not text.startswith(("#", "import ", "from ")):
                out.add(text)
    return out


def find_pr(sha: str, tickets: list[int], subject: str = "") -> dict | None:
    """GitHub PR for a Django commit: search by sha, then by 'Fixed #N' in the title.

    A hit is accepted only if its title names one of the commit's tickets or starts like the commit subject;
    a sha search also returns PRs that merely mention the commit.
    """
    def plausible(title: str) -> bool:
        return any(re.search(rf"#{t}\b", title) for t in tickets) or (
            bool(subject) and title[:30].lower() == subject[:30].lower())

    queries = [f"repo:{REPO} is:pr {sha}"] + [f'repo:{REPO} is:pr "#{t}" in:title' for t in tickets[:1]]
    for q in queries:
        for item in gh_search(q, per_page=10)["items"]:
            if not plausible(item["title"]):
                continue
            if (item.get("pull_request") or {}).get("merged_at") or item["state"] == "closed":
                return {"number": item["number"], "url": item["html_url"], "title": item["title"],
                        "body": item.get("body") or "", "labels": [lab["name"] for lab in item.get("labels", [])]}
    return None


def resolve(short: str) -> str | None:
    return git("rev-parse", "--verify", "-q", f"{short}^{{commit}}", check=False).strip() or None


# ----------------------------------------------------------------------------------------- discover


def discover(since: str) -> None:
    log = git("log", "origin/main", f"--since={since}", "-E", "-i", f"--grep=Regression in {SHA}",
              "--format=%H%x00%B%x01")
    fixes = []
    for entry in log.split("\x01"):
        if "\x00" in entry:
            sha, msg = entry.strip().split("\x00", 1)
            for m in REGRESSION_RE.finditer(msg):
                for short in re.findall(SHA, m.group(1)):
                    fixes.append((sha, msg, short))
    print(f"{len(fixes)} (fix, culprit) pairs", flush=True)

    funnel: dict[str, int] = defaultdict(int)
    by_culprit: dict[str, list] = defaultdict(list)
    for fix_sha, fix_msg, short in fixes:
        funnel["pairs"] += 1
        full = resolve(short)
        if full is None:
            funnel["unresolvable_sha"] += 1
            continue
        by_culprit[full].append((fix_sha, fix_msg))

    candidates = []
    for i, (sha, fixes_for) in enumerate(sorted(by_culprit.items())):
        funnel["culprit_commits"] += 1
        info = commit_info(sha)
        if info["n_parents"] != 1:
            funnel["merge_commit"] += 1
            continue
        stats = diff_stats(f"{sha}^", sha)
        paths = [f["path"] for f in stats["files"]]
        code_paths = [p for p in paths if is_code(p)]
        size_ok = 0 < stats["changed_lines"] <= MAX_DIFF_LINES
        funnel["size_ok" if size_ok else "too_large"] += 1
        if not code_paths:
            funnel["no_shipped_code"] += 1
            continue
        added = changed_lines(sha, "+")
        evidence = []
        for fix_sha, fix_msg in fixes_for:
            fix_info = commit_info(fix_sha)
            fix_paths = [f["path"] for f in diff_stats(f"{fix_sha}^", fix_sha)["files"]]
            evidence.append({
                "fix_commit": fix_sha, "fix_subject": fix_info["subject"], "fix_date": fix_info["date"],
                "fix_tickets": fix_info["tickets"], "fix_message": fix_info["message"],
                "file_overlap": sorted(set(code_paths) & {p for p in fix_paths if is_code(p)}),
                # lines the fix deletes/rewrites that the culprit had added: strong evidence the bug is in this diff
                "line_overlap": len(added & changed_lines(fix_sha, "-")),
            })
        if size_ok:
            funnel["size_ok_code"] += 1
        candidates.append({
            "culprit": sha, "short": sha[:10], "merged_at": info["date"], "author": info["author"],
            "title": info["subject"], "commit_message": info["message"], "tickets": info["tickets"],
            "base": f"{sha}^", "head": sha, "changed_lines": stats["changed_lines"], "n_files": len(paths),
            "area": area_of(paths), "size_ok": size_ok, "evidence": evidence,
            "url": f"https://github.com/{REPO}/commit/{sha}",
        })
        print(f"[{i + 1}/{len(by_culprit)}] {sha[:10]} {stats['changed_lines']:>5}L {info['subject'][:70]}", flush=True)

    # GitHub PR (for the reviewer-visible description) only for usable candidates, to save search quota
    for c in candidates:
        if c["size_ok"]:
            c["pr"] = find_pr(c["culprit"], c["tickets"], c["title"])
            funnel["pr_found" if c["pr"] else "pr_not_found"] += 1

    candidates.sort(key=lambda c: (not c["size_ok"], -max(e["line_overlap"] for e in c["evidence"]), c["merged_at"]))
    DATA.mkdir(parents=True, exist_ok=True)
    with open(DATA / "candidates.jsonl", "w") as fh:
        for c in candidates:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    write_json(DATA / "mining_funnel.json", {"since": since, **funnel})
    print(dict(funnel))


# ----------------------------------------------------------------------------------------- controls


def day(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def later_mentions(sha: str, tickets: list[int]) -> str | None:
    """Reason to reject a control: a later commit names its sha, or a later regression fix names its ticket."""
    hit = git("log", "-i", f"--grep={sha[:7]}", "--format=%h %s", f"{sha}..origin/main").strip()
    if hit:
        return f"sha mentioned by {hit.splitlines()[0]}"
    for t in tickets:
        log = git("log", "-E", f"--grep=#{t}([^0-9]|$)", "--format=%h %s%x00%b%x01",
                  f"{sha}..origin/main")
        for entry in log.split("\x01"):
            if "\x00" in entry and re.search(r"regression|revert", entry, re.IGNORECASE):
                return f"ticket #{t} mentioned by a later fix/revert: {entry.split(chr(0))[0].strip()}"
    # Bugs in new code are often fixed without a "Regression in" line (e.g. a feature fixed before release).
    # Conservative check: a later bug-fix-like commit that deletes or rewrites lines this commit added.
    added = changed_lines(sha, "+")
    code_files = [f["path"] for f in diff_stats(f"{sha}^", sha)["files"] if is_code(f["path"])]
    if added and code_files:
        log = git("log", "--format=%H%x00%s%x00%b%x01", f"{sha}..origin/main", "--", *code_files)
        for entry in log.split("\x01"):
            if "\x00" not in entry:
                continue
            later, subject, body = entry.strip().split("\x00", 2)
            if BUGFIX_RE.search(subject + " " + body) and added & changed_lines(later, "-"):
                return f"later bug fix rewrites its lines: {later[:10]} {subject[:60]}"
    return None


def controls(today: dt.date) -> None:
    candidates = {c["culprit"]: c for c in read_jsonl(DATA / "candidates.jsonl")}
    curation = yaml.safe_load((DATA / "curation.yaml").read_text())
    culprits = set(candidates)
    out, taken = [], set()
    for b in (b for b in curation["bugs"] if b.get("status") == "include"):
        bug = candidates[resolve(b["culprit"])]
        merged = day(bug["merged_at"])
        lo, hi = merged - dt.timedelta(days=365), min(merged + dt.timedelta(days=180), today - dt.timedelta(days=180))
        if hi < lo:
            hi = lo + dt.timedelta(days=30)
        pool = git("log", "origin/main", "--no-merges", f"--since={lo}", f"--until={hi}", "--grep=^Fixed #",
                   "--format=%H").split()
        pool.sort(key=lambda s: hashlib.sha256(f"control-for-{bug['culprit']}-{s}".encode()).hexdigest())
        size_lo, size_hi = max(5, bug["changed_lines"] // 2), min(MAX_DIFF_LINES, bug["changed_lines"] * 2)
        chosen = None
        for sha in pool:
            if sha in culprits or sha in taken:
                continue
            stats = diff_stats(f"{sha}^", sha)
            if not size_lo <= stats["changed_lines"] <= size_hi:
                continue
            if area_of([f["path"] for f in stats["files"]]) != bug["area"]:
                continue
            info = commit_info(sha)
            if re.search(r"\brevert", info["subject"], re.IGNORECASE):
                continue  # a revert's diff undoes earlier code; not a normal change to review
            reason = later_mentions(sha, info["tickets"])
            if reason:
                print(f"    {sha[:10]} rejected: {reason}")
                continue
            chosen = {"control": sha, "short": sha[:10], "title": info["subject"], "merged_at": info["date"],
                      "matched_to": bug["short"], "area": bug["area"], "changed_lines": stats["changed_lines"],
                      "tickets": info["tickets"], "pr": find_pr(sha, info["tickets"], info["subject"])}
            break
        if chosen is None:
            print(f"!! no control for {bug['short']}")
            continue
        taken.add(chosen["control"])
        out.append(chosen)
        print(f"{bug['short']} -> control {chosen['short']} ({chosen['changed_lines']}L) {chosen['title'][:60]}")
    header = "# Generated by `uv run bench-mine-django controls`. Set status: exclude to drop one.\n"
    (DATA / "controls.yaml").write_text(header + yaml.safe_dump({"controls": out}, sort_keys=False, allow_unicode=True))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=["discover", "controls"])
    ap.add_argument("--since", default="2024-01-01")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    args = ap.parse_args()
    if REPO != "django/django":
        raise SystemExit("bench-mine-django only works with BENCH_REPO=django/django")
    if args.step == "discover":
        discover(args.since)
    else:
        controls(dt.date.fromisoformat(args.today))


if __name__ == "__main__":
    main()
