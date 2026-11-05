"""Render data/CHECKPOINT.md: one row per materialized case, for manual confirmation of ground truth.

Usage:  uv run bench-checkpoint
"""

from __future__ import annotations

import json

from .common import CASES, DATA, REPO


def link(kind: str, n: int | None) -> str:
    return f"[#{n}](https://github.com/{REPO}/{kind}/{n})" if n else ""


def main() -> None:
    rows_bug, rows_ctl = [], []
    for d in sorted(CASES.iterdir()):
        pr = json.loads((d / "pr.json").read_text())
        ans = json.loads((d / "answer.json").read_text())
        merged = (pr["merged_at"] or "")[:10]
        title = pr["title"].replace("|", "\\|")
        label = f"#{pr['number']}" if pr.get("number") else pr["head_commit"][:10]
        pr_link = f"[{label}]({pr['url']})"
        if ans["kind"] == "bug":
            fix = " ".join(filter(None, [
                link("pull", ans.get("fix_pr")),
                f"[{ans['fix_commit'][:10]}](https://github.com/{REPO}/commit/{ans['fix_commit']})" if ans.get("fix_commit") else "",
                ("issue " + link("issues", ans.get("issue"))) if ans.get("issue") else "",
                " ".join(f"[ticket #{t}](https://code.djangoproject.com/ticket/{t})" for t in ans.get("fix_tickets", [])),
            ]))
            gt = ans["ground_truth"].replace("|", "\\|")
            warn = f" ⚠ {ans['warning']}" if ans.get("warning") else ""
            rows_bug.append(f"| {d.name} | {pr_link} {title} | {merged} | {pr['changed_lines']} | {fix} | {gt}{warn} | ☐ |")
        else:
            rows_ctl.append(f"| {d.name} | {pr_link} {title} | {merged} | {pr['changed_lines']} | bug-{ans['matched_to']} | ☐ |")

    md = [
        f"# Checkpoint ({REPO}): {len(rows_bug)} bug cases + {len(rows_ctl)} controls (manual confirmation)",
        "",
        "Tick ☐ → ☑ for each row you confirm, or note a correction. Ground truth is written from the fix "
        "commit/PR and its diff, not from the buggy PR alone.",
        "",
        f"## Bug cases ({len(rows_bug)})",
        "",
        "| case | buggy PR | merged | lines | fixed by | ground truth | ok? |",
        "|---|---|---|---|---|---|---|",
        *rows_bug,
        "",
        f"## Controls ({len(rows_ctl)})",
        "",
        "| case | PR | merged | lines | matched to | ok? |",
        "|---|---|---|---|---|---|",
        *rows_ctl,
        "",
    ]
    (DATA / "CHECKPOINT.md").write_text("\n".join(md))
    print(f"wrote {DATA / 'CHECKPOINT.md'}: {len(rows_bug)} bugs, {len(rows_ctl)} controls")


if __name__ == "__main__":
    main()
