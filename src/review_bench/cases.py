"""Step 4: materialize self-contained benchmark cases under data/cases/<id>/.

Each case directory holds exactly what the reviewer may see, plus the hidden answer:
  pr.json        title, description, labels, links (visible to the reviewer in conditions B and C)
  diff.patch     `git diff base head` of the PR as it was reviewed (all conditions)
  files/...      full post-PR contents of every changed, non-deleted text file (condition C)
  answer.json    kind (bug|control), ground truth, links to the fix (NEVER shown to the reviewer)

Inputs: data/<repo>/curation.yaml (hand-verified bugs) and data/<repo>/controls.yaml.
Usage:  uv run bench-cases                              (angular/angular)
        BENCH_REPO=django/django uv run bench-cases     (django/django)
        uv run bench-cases --batch scaleup-2026-11      only the bugs tagged with that batch; existing cases and
                                                        controls are left untouched

angular: the reviewed unit is a PR (refs/pull/N/head vs merge-base); description = PR body.
django:  the reviewed unit is the landed commit (sha^..sha); description = the GitHub PR body when one is found,
         otherwise the commit message. The commit message is always stored too (`commit_message`).
"""

from __future__ import annotations

import json
import shutil

import yaml

from .common import CASES, DATA, REPO, SLUG, diff_stats, git, pr_diff_range, pr_info, read_jsonl, write_json

MAX_FILE_BYTES = 200_000


def leaks(body: str, numbers: list[int]) -> list[int]:
    """PR numbers of the later fix/issue that appear in the (possibly later-edited) PR description."""
    return [n for n in numbers if n and (f"#{n}" in body or f"/pull/{n}" in body or f"/issues/{n}" in body)]


def angular_visible(pr: int) -> dict:
    info = pr_info(pr)
    return {"number": pr, "url": info["url"], "title": info["title"], "description": info["body"],
            "labels": info["labels"], "author": info["author"], "merged_at": info["merged_at"]}


def django_visible(c: dict) -> dict:
    pr = c.get("pr") or {}
    return {"number": pr.get("number"), "url": pr.get("url") or f"https://github.com/{REPO}/commit/{c['head']}",
            "commit_url": f"https://github.com/{REPO}/commit/{c['head']}",
            "title": pr.get("title") or c["title"], "description": pr.get("body") or c["commit_message"],
            "commit_message": c["commit_message"], "labels": pr.get("labels", []), "author": c["author"],
            "merged_at": c["merged_at"], "tickets": c["tickets"]}


def build(case_id: str, info: dict, base: str, head: str, answer: dict) -> None:
    out = CASES / case_id
    if out.exists():
        shutil.rmtree(out)
    stats = diff_stats(base, head)
    write_json(out / "pr.json", {
        "repo": REPO, **info,
        "base_commit": git("rev-parse", base).strip(), "head_commit": git("rev-parse", head).strip(),
        "changed_lines": stats["changed_lines"], "files": stats["files"],
        "license": f"see data/{SLUG}/LICENSE.txt",
    })
    (out / "diff.patch").write_text(git("diff", base, head))
    for f in stats["files"]:
        if f["binary"]:
            continue
        content = git("show", f"{head}:{f['path']}", check=False)
        if content and len(content.encode()) <= MAX_FILE_BYTES:
            dest = out / "files" / f["path"]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
    answer = {"case_id": case_id, "pr_url": info["url"], **answer}
    text = info["description"] + info.get("commit_message", "")
    leaked = leaks(text, [answer.get("fix_pr"), answer.get("issue"), *answer.get("fix_tickets", [])])
    if answer.get("fix_commit") and answer["fix_commit"][:7] in text:
        leaked.append(answer["fix_commit"][:10])
    if leaked:
        answer["warning"] = f"PR description mentions later item(s) {leaked}; check for leakage"
        print(f"   WARNING {case_id}: {answer['warning']}")
    write_json(out / "answer.json", answer)
    print(f"{case_id}: {stats['changed_lines']} lines, {len(stats['files'])} files")


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", help="build only the bug cases tagged `batch: <name>` in curation.yaml")
    batch = ap.parse_args().batch
    key = "culprit_pr" if SLUG == "angular" else "culprit"
    candidates = {str(c[key]): c for c in read_jsonl(DATA / "candidates.jsonl")}
    curation = yaml.safe_load((DATA / "curation.yaml").read_text())
    for b in curation["bugs"]:
        if b.get("status") != "include" or (batch and b.get("batch") != batch):
            continue
        answer = {
            "kind": "bug",
            "ground_truth": " ".join(b["ground_truth"].split()),
            "bug_files": b.get("bug_files", []),
            "fix_pr": b.get("fix_pr"), "fix_commit": b.get("fix_commit"), "issue": b.get("issue"),
            "fix_tickets": b.get("fix_tickets", []), "evidence_url": b.get("evidence_url"),
        }
        if SLUG == "angular":
            if b.get("diff_range_from_case"):  # e.g. a former control: reuse the diff range it was reviewed with
                pr = json.loads((CASES / b["diff_range_from_case"] / "pr.json").read_text())
                c = {"base": pr["base_commit"], "head": pr["head_commit"]}
            else:
                c = candidates[str(b["culprit_pr"])]
            build(f"bug-{b['culprit_pr']}", angular_visible(b["culprit_pr"]), c["base"], c["head"], answer)
        else:
            c = next(c for k, c in candidates.items() if k.startswith(str(b["culprit"])))
            build(f"bug-{c['short']}", django_visible(c), c["base"], c["head"], answer)
    controls_path = DATA / "controls.yaml"
    if controls_path.exists() and not batch:
        for c in yaml.safe_load(controls_path.read_text())["controls"]:
            if c.get("status") == "exclude":
                continue
            answer = {"kind": "control", "ground_truth": None, "matched_to": c["matched_to"]}
            if SLUG == "angular":
                base, head = pr_diff_range(c["control_pr"])
                build(f"ctl-{c['control_pr']}", angular_visible(c["control_pr"]), base, head, answer)
            else:
                rec = {"head": c["control"], "title": c["title"], "commit_message": git("show", "-s", "--format=%B", c["control"]).strip(),
                       "author": git("show", "-s", "--format=%an", c["control"]).strip(), "merged_at": c["merged_at"],
                       "tickets": c["tickets"], "pr": c.get("pr")}
                build(f"ctl-{c['short']}", django_visible(rec), f"{c['control']}^", c["control"], answer)
    license_path = DATA / "LICENSE.txt"
    if not license_path.exists():
        license_path.write_text(f"Source: https://github.com/{REPO}/blob/main/LICENSE\n\n" + git("show", "origin/main:LICENSE"))


if __name__ == "__main__":
    main()
