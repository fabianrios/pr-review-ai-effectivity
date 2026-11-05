"""Shared paths and small helpers for talking to GitHub (via `gh`) and to a local git clone."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import time
from pathlib import Path

# Which repository a command works on: BENCH_REPO=angular/angular (default) or django/django.
REPO = os.environ.get("BENCH_REPO", "angular/angular")
SLUG = REPO.split("/")[1]
ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / SLUG
CASES = DATA / "cases"
CACHE = ROOT / "cache"
# Local clone of the repository. A blobless clone is enough: `git clone --filter=blob:none`.
CLONE = Path(os.environ.get("BENCH_CLONE", ROOT / "work" / SLUG))

MAX_DIFF_LINES = 400  # insertions + deletions

# ---------------------------------------------------------------- GitHub search


_last_search = 0.0


def gh_search(query: str, page: int = 1, per_page: int = 100, text_match: bool = False) -> dict:
    """GitHub issue/PR search via the `gh` CLI, cached on disk, throttled to stay under 30 req/min."""
    global _last_search
    key = hashlib.sha256(json.dumps([query, page, per_page, text_match]).encode()).hexdigest()[:24]
    path = CACHE / "gh" / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    wait = 2.2 - (time.time() - _last_search)
    if wait > 0:
        time.sleep(wait)
    cmd = ["gh", "api", "-X", "GET", "search/issues", "-f", f"q={query}",
           "-f", f"per_page={per_page}", "-f", f"page={page}"]
    if text_match:
        cmd += ["-H", "Accept: application/vnd.github.text-match+json"]
    for attempt in range(4):
        _last_search = time.time()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0:
            break
        if "rate limit" in proc.stderr.lower() or "403" in proc.stderr:
            print(f"   (search rate-limited, backing off {30 * (attempt + 1)}s)", flush=True)
            time.sleep(30 * (attempt + 1))
            continue
        raise RuntimeError(f"gh search failed for {query!r}: {proc.stderr.strip()}")
    else:
        raise RuntimeError(f"gh search kept failing for {query!r}")
    result = json.loads(proc.stdout)
    result["_query"] = query
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    return result


def gh_search_all(query: str, text_match: bool = False, max_pages: int = 3) -> list[dict]:
    items: list[dict] = []
    for page in range(1, max_pages + 1):
        res = gh_search(query, page=page, text_match=text_match)
        items += res["items"]
        if len(items) >= res["total_count"] or not res["items"]:
            break
    return items


def pr_info(number: int) -> dict | None:
    """Title, body, labels, dates of an angular/angular PR (via search; the REST pulls API is not needed)."""
    res = gh_search(f"repo:{REPO} is:pr {number}", per_page=30)
    for item in res["items"]:
        if item["number"] == number and "pull_request" in item:
            return {
                "number": number,
                "url": item["html_url"],
                "title": item["title"],
                "body": item.get("body") or "",
                "labels": [lab["name"] for lab in item.get("labels", [])],
                "created_at": item["created_at"],
                # Angular historically landed PRs with its own merge tool: GitHub shows them as closed, and
                # the commit on main carries a "PR Close #N" trailer. Treat either as "merged".
                "merged_at": (item.get("pull_request") or {}).get("merged_at")
                or (item.get("closed_at") if landed_on_main(number) else None),
                "author": (item.get("user") or {}).get("login"),
            }
    return None


def references_to(number: int) -> list[dict]:
    """Issues/PRs that mention this number anywhere (used to vet control PRs)."""
    items = []
    for kind in ("is:issue", "is:pr"):  # the search API requires one of the two
        items += gh_search_all(f"repo:{REPO} {kind} {number}", max_pages=1)
    return [i for i in items if i["number"] != number]


# ------------------------------------------------------------------------ git

_landed: set[int] | None = None


def landed_on_main(number: int) -> bool:
    """True if a commit on main closes this PR ("PR Close #N" trailer or "(#N)" at the end of the subject)."""
    global _landed
    if _landed is None:
        log = git("log", "origin/main", "--format=%s%n%b")
        _landed = {int(n) for n in re.findall(r"^PR Close #(\d+)\s*$", log, re.MULTILINE)}
        _landed |= {int(n) for n in re.findall(r"\(#(\d+)\)\s*$", log, re.MULTILINE)}
    return number in _landed


def git(*args: str, check: bool = True) -> str:
    proc = subprocess.run(["git", "-C", str(CLONE), *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def fetch_pr_head(number: int) -> str | None:
    """Fetch refs/pull/N/head into the local clone and return its sha (None if unavailable)."""
    ref = f"refs/bench/pr/{number}"
    if git("rev-parse", "--verify", "-q", ref, check=False).strip() == "":
        proc = subprocess.run(["git", "-C", str(CLONE), "fetch", "-q", "origin", f"pull/{number}/head:{ref}"],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return None
    return git("rev-parse", ref).strip()


def pr_diff_range(number: int) -> tuple[str, str] | None:
    """(base, head) for a PR: head of the PR and its merge-base with main, i.e. the diff reviewers saw."""
    head = fetch_pr_head(number)
    if head is None:
        return None
    base = git("merge-base", head, "origin/main", check=False).strip()
    return (base, head) if base else None


def diff_stats(base: str, head: str) -> dict:
    files, added, deleted = [], 0, 0
    for line in git("diff", "--numstat", base, head).splitlines():
        a, d, path = line.split("\t", 2)
        a_n = int(a) if a != "-" else 0
        d_n = int(d) if d != "-" else 0
        files.append({"path": path, "added": a_n, "deleted": d_n, "binary": a == "-"})
        added += a_n
        deleted += d_n
    return {"files": files, "added": added, "deleted": deleted, "changed_lines": added + deleted}


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
