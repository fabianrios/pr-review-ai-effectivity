# Scale-up: does the PR description lower detection on new cases?

Run 2026-11-04, unattended (the author allowed an overnight run with the work-account ledger capped at $30).
Reviewer `claude-sonnet-5-5` at effort high, judge `claude-opus-5-5` at effort high, conditions A (diff only) and B
(diff + title and description), 4 independent samples per cell. Results: this folder and `_s1`–`_s3`.

## Answer: no, not on the new cases

| set | cases | A | B | A>B / B>A cases | sign test p |
|---|---|---|---|---|---|
| original angular (before) | 10 | 24/40 = 60% | 16/40 = 40% | 3 / 0 | 0.25 |
| **new angular** | 4 | 8/16 = 50% | 8/16 = 50% | 0 / 0 | 1.00 |
| **new django** | 23 | 50/92 = 54% | 48/92 = 52% | 4 / 4 | 1.00 |
| **all new** | 27 | 58/108 = 54% | 56/108 = 52% | 4 / 4 | 1.00 |
| pooled angular (old + new) | 14 | 32/56 = 57% | 24/56 = 43% | 3 / 0 | 0.25 |
| pooled, every case with 4 samples | 37 | 82/148 = 55% | 72/148 = 49% | 7 / 4 | 0.55 |

- The large angular effect from the first 10 cases does not carry over. On 27 new cases the description changes
  detection by 2 hits out of 108, and the cases that move split evenly in both directions.
- The original effect rested on 3 cases (bug-63485, bug-53695, bug-55796). Those cases look like genuine anchoring,
  but they are the exception, not the rule. The honest headline is now: **a confident PR description can make the
  reviewer drop a concern it raises without it, but on average the description neither helps nor hurts detection.**
- The anchoring pattern does recur at the margin. On django/bug-626d77e52a the description presents the change as
  a clean delegation to `ColPairs`/`TupleIn`; with it the reviewer reports nothing in all 4 B samples, while A flags
  the wrong table alias (though only at confidence 0.2–0.35). Cases going the other way (B finds it, A doesn't) are
  just as common: bug-c09bceef68, bug-aba0e541ca, bug-4cecf30395, bug-9e9792228a.
- Detection on the new set (54%) is close to the original set's (A 65%, any confidence), so the new cases are not
  systematically easier or harder.

## Caveats

- The new cases were drafted by Opus and checked by Fable (`data/DRAFTS.md`, `data/GROUND_TRUTH_CHECK.md`). The
  author reviewed the judgment calls on 2026-11-05 and dropped angular/bug-62083 (a Bazel build-config change, build
  tooling under the inclusion rule; it was 4/4 in both A and B, so the A/B result is unaffected). The run had 28
  cases; the numbers here use the remaining 27. The labels are model-checked, not expert-checked.
- The new verdicts were not cross-judged (that would have cost about $13, over the $30 cap). On the original set the
  two judges agreed 87/87, so judge error is an unlikely explanation for the null result, but it is not ruled out.
- Only 4 new angular cases: the angular-specific question is still underpowered (14 cases pooled, p = 0.25).
- Spend: $9.72 for the 4 samples ($5.52 reviews, $4.20 judgments), $1.78 drafting, $4.58 ground-truth checks of
  the new cases (incl. one retry and a re-check after a rewording). Ledger total $25.20 of the $30 cap.

## Grid: 27 new cases (bug-62083 excluded)

27 bug cases × 4 samples. `x` = the judge matched a finding to the known bug.

| case | A | B |
|---|---|---|
| angular/bug-56852 | `xxxx` 4/4 | `xxxx` 4/4 |
| angular/bug-57796 | `....` 0/4 | `....` 0/4 |
| angular/bug-60206 | `....` 0/4 | `....` 0/4 |
| angular/bug-61241 | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-1a8fd5cf75 | `....` 0/4 | `....` 0/4 |
| django/bug-4b2b4bf0ac | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-4cecf30395 *(B>A)* | `x.x.` 2/4 | `x.xx` 3/4 |
| django/bug-55d89e25f4 | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-5d911f2d2f | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-626d77e52a **(A>B)** | `x.xx` 3/4 | `....` 0/4 |
| django/bug-65ab92f6a8 | `x.xx` 3/4 | `xxx.` 3/4 |
| django/bug-73df8b54a2 | `....` 0/4 | `....` 0/4 |
| django/bug-857b1048d5 | `..x.` 1/4 | `.x..` 1/4 |
| django/bug-8638d8bf74 **(A>B)** | `xxxx` 4/4 | `xxx.` 3/4 |
| django/bug-91bebf1adb | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-94680437a4 | `....` 0/4 | `....` 0/4 |
| django/bug-9e9792228a *(B>A)* | `xxx.` 3/4 | `xxxx` 4/4 |
| django/bug-a16eedcf9c | `....` 0/4 | `....` 0/4 |
| django/bug-aba0e541ca *(B>A)* | `....` 0/4 | `...x` 1/4 |
| django/bug-bf7b17d16d | `....` 0/4 | `....` 0/4 |
| django/bug-c09bceef68 *(B>A)* | `....` 0/4 | `x..x` 2/4 |
| django/bug-ca2be7724e | `....` 0/4 | `....` 0/4 |
| django/bug-cd0479ff76 | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-ec7d69035a | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-f02b49d2f3 **(A>B)** | `xxxx` 4/4 | `xxx.` 3/4 |
| django/bug-faeb92ea13 | `xxxx` 4/4 | `xxxx` 4/4 |
| django/bug-fd569dd45b **(A>B)** | `x.x.` 2/4 | `....` 0/4 |
| **total** | **58/108 = 54%** | **56/108 = 52%** |

A/B hits per sample: 16/15, 12/14, 17/14, 13/13. Cases where A > B: 4; B > A: 4; two-sided sign test p = 1.000.
