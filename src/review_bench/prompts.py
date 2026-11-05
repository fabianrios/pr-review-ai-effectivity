"""Reviewer and judge prompts, output schemas, and the three context conditions.

The reviewer prompt is identical across conditions; only the attached context changes:
  A  diff only
  B  diff + title and description
  C  diff + title and description + full post-change contents of every changed file
Content is ordered so that each condition extends the previous one (diff first, then description, then files).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CONDITIONS = ("A", "B", "C")  # the default set for a run
# T: A + targeted context (enclosing functions and call sites, written to context.txt by
# `bench-mine-internal --context`); only private cases have it so far.
ALL_CONDITIONS = CONDITIONS + ("T",)

REVIEWER_SYSTEM = """\
You are an expert code reviewer for the {repo} open-source project. You are reviewing a change before it is merged.

Report defects: problems that would make the code behave incorrectly once merged, such as wrong results, crashes or
exceptions, broken edge cases, regressions of existing behavior, security issues, or broken compatibility for
existing users. Do not report style, naming, formatting, documentation or test-coverage suggestions, and do not
report speculative concerns you cannot tie to a concrete failure.

It is fine, and often correct, to report no defects. For each defect you do report, give:
- file: the path as it appears in the diff
- line: a line number in the new version of the file (use the closest relevant line; 0 if not applicable)
- description: what goes wrong, under which conditions, and why
- severity: low, medium, high or critical
- confidence: your probability (0 to 1) that this is a real defect that the maintainers would confirm and fix
"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "confidence": {"type": "number"},
                },
                "required": ["file", "line", "description", "severity", "confidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["findings"],
    "additionalProperties": False,
}

JUDGE_SYSTEM = """\
You grade a code review against a known bug. You are given the change that was reviewed, a ground-truth description
of a bug this change is known to have introduced (written from the later fix), and the reviewer's numbered findings.

A finding MATCHES the known bug if it identifies the same defect: the same faulty code and essentially the same
failure mechanism, even if it is worded differently, describes a different symptom of that same mechanism, or is
less precise about consequences. A finding does NOT match if it only points at the same file or line for a different
reason, raises a generic concern ("this may break something"), or describes a different real or imagined bug.

Judge each finding independently. Be strict but fair: credit a finding that would have led a maintainer to the
actual bug. Explain your decision briefly, quoting the relevant part of the finding.
"""

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "matched_finding_indices": {"type": "array", "items": {"type": "integer"}},
        "justification": {"type": "string"},
    },
    "required": ["matched_finding_indices", "justification"],
    "additionalProperties": False,
}

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)


def clean_description(text: str) -> str:
    """Remove PR-template HTML comments and collapse blank lines; keep what the author actually wrote."""
    text = _HTML_COMMENT.sub("", text or "").replace("\r\n", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def load_case(case_dir: Path) -> dict:
    return {
        "id": case_dir.name,
        "dir": case_dir,
        "pr": json.loads((case_dir / "pr.json").read_text()),
        "answer": json.loads((case_dir / "answer.json").read_text()),
        "diff": (case_dir / "diff.patch").read_text(),
    }


def description_block(pr: dict) -> str:
    parts = [f"Title: {pr['title']}", "", "Description:", clean_description(pr["description"]) or "(empty)"]
    commit_message = pr.get("commit_message", "").strip()
    if commit_message and commit_message not in pr["description"]:
        parts += ["", "Commit message:", commit_message]
    return "\n".join(parts)


def files_block(case_dir: Path, pr: dict) -> str:
    out = []
    for f in pr["files"]:
        path = case_dir / "files" / f["path"]
        if path.exists():
            out.append(f'<file path="{f["path"]}">\n{path.read_text()}\n</file>')
    return "\n\n".join(out)


def review_request(case: dict, condition: str, model: str, effort: str, max_tokens: int) -> dict:
    """Full messages.create params for one (case, condition). Deterministic, so it doubles as the cache key."""
    pr = case["pr"]
    blocks = [{"type": "text", "text": f"<diff>\n{case['diff']}\n</diff>"}]
    if condition in ("B", "C"):
        blocks.append({"type": "text", "text": f"<change_description>\n{description_block(pr)}\n</change_description>"})
    if condition == "T":
        blocks.append({"type": "text", "text": "Surrounding code after the change (the complete functions the diff "
                       "touches, and call sites in other files):\n\n" + (case["dir"] / "context.txt").read_text()})
    if condition == "C":
        blocks.append({"type": "text",
                       "text": "Full contents of every changed file after the change:\n\n" + files_block(case["dir"], pr)})
    blocks.append({"type": "text", "text": "Review this change and report any defects it introduces."})
    return {
        "model": model,
        "max_tokens": max_tokens,
        # private repositories: same prompt without "open-source" (public requests, and their cache keys, unchanged)
        "system": (REVIEWER_SYSTEM.replace(" open-source project", " project") if pr.get("private")
                   else REVIEWER_SYSTEM).format(repo=pr["repo"]),
        "messages": [{"role": "user", "content": blocks}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": REVIEW_SCHEMA}},
    }


CROSS_JUDGE_SYSTEM = JUDGE_SYSTEM + """
You are also given the diff of the commit that later fixed the bug (test files left out). It is the strongest
evidence of what the bug actually is. A finding matches only if acting on it would have led a maintainer to the
change the fix makes, or to an equivalent change. A finding whose own suggested fix would leave the bug in place
does not match, even if it describes a similar symptom.
"""


def judge_text(case: dict, findings: list[dict], fix_diff: str | None = None) -> str:
    ans = case["answer"]
    numbered = "\n\n".join(
        f"[{i}] {f['file']}:{f['line']} (severity {f['severity']}, confidence {f['confidence']})\n{f['description']}"
        for i, f in enumerate(findings))
    fix_block = f"<fix>\n{fix_diff}\n</fix>\n\n" if fix_diff is not None else ""
    return (f"<change>\n{case['diff']}\n</change>\n\n"
            f"<known_bug>\n{ans['ground_truth']}\nFiles involved: {', '.join(ans.get('bug_files') or []) or 'n/a'}\n"
            f"</known_bug>\n\n{fix_block}<review_findings>\n{numbered}\n</review_findings>\n\n"
            "Which findings, if any, match the known bug?")


def verdict_request(system: str, text: str, model: str, effort: str) -> dict:
    return {
        "model": model,
        "max_tokens": 8000,
        "system": system,
        "messages": [{"role": "user", "content": text}],
        "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": JUDGE_SCHEMA}},
    }


def judge_request(case: dict, findings: list[dict], model: str, effort: str) -> dict:
    return verdict_request(JUDGE_SYSTEM, judge_text(case, findings), model, effort)


def cross_judge_request(case: dict, findings: list[dict], model: str, effort: str) -> dict:
    """Independent second judge: same task, plus the fix commit's diff as evidence. Never sees the first verdict."""
    fix_diff = (case["dir"] / "fix.patch").read_text()
    return verdict_request(CROSS_JUDGE_SYSTEM, judge_text(case, findings, fix_diff), model, effort)
