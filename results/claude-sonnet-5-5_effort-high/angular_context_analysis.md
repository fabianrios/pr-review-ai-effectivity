# Angular: why detection drops from A (60%) to B/C (40%)

> **Superseded 2026-11-04:** on 28 new cases (5 angular, 23 django, 4 samples each) the description effect does
> not replicate: A 55% vs B 54%, new angular cases 12/20 vs 12/20. See
> `../claude-sonnet-5-5_effort-high_scaleup/scaleup_analysis.md`. The analysis below stays as the record of the
> first 10 angular cases.

Conditions: A = diff only; B = A + title and description; C = B + full post-change files.

**Update 2026-11-04:** bug-60875 was re-judged with the clarified ground truth (a finding that only says the
default-handling clause is inverted does not count). All 9 of its judgments are now misses. The numbers below
reflect that; the earlier figures (A 70% in sample 0, 27/40 vs 18/40 over 4 samples) are kept in the sensitivity
table at the end.

## Per-case grid (bug cases)

| case | A | B | C | C input tokens |
|---|---|---|---|---|
| bug-46096 | miss | miss | miss | 27k |
| bug-48063 | miss | miss | miss | 17k |
| bug-48558 | hit | hit | hit | 22k |
| bug-50063 | hit | hit | hit | 12k |
| bug-53695 | **hit (0.85)** | miss | miss | 122k |
| bug-55796 | miss | miss | miss | 64k |
| bug-60875 | miss (was hit 0.5, see below) | miss | miss | 37k |
| bug-63485 | **hit (0.25)** | miss | miss | 51k |
| bug-67032 | hit | hit | hit | 168k |
| bug-69309 | hit | hit | hit | 3k |

- C matches B on every bug case. Full files neither added nor removed a single detection.
  The whole drop happens between A and B, where the only change is the PR title and description.
- Thinking tokens stay flat (about 450–1,500) whatever the input size, even at 168k input tokens. At
  effort high, the reviewer does not spend more reasoning on more context.

## The three flips

1. **bug-63485: likely anchored by the description.** The description argues for the change ("some
   observables don't complete", so take the first value). That heads off the exact concern A raised: `first()`
   throws EmptyError on an empty observable. B and C report nothing. Caveat: A's hit had only 0.25 confidence.
2. **bug-53695: B and C find a side issue instead.** A found the real bug (`deferBlockDep.isDefaultImport` never
   set, conf 0.85) plus a side issue: mixed default+named imports. B and C report only the side issue. The
   description ("handle default imports") is neutral, so this looks like run-to-run variance more than anchoring.
3. **bug-60875: the judge is inconsistent, not the reviewer.** The description is just "See individual commits",
   so B adds nothing. A's credited finding and C's finding 0 make the same claim: the `defaultQueryParamsHandling`
   clause is inverted. The judge accepted it in A and rejected it in C. C's verdict is the defensible one,
   because that claim implies the opposite of the real fix. So A's hit is probably a judge false positive.
   **Resolved:** the ground truth now excludes that claim explicitly, and the re-judge marks A as a miss. This is
   no longer a flip; only bug-63485 and bug-53695 remain.

## False alarms

Angular controls flagged: A 1, B 2, C 3 (of 9). The extra ones (ctl-58199 in B, ctl-44001 in C) are low confidence
(0.20–0.35). At confidence ≥ 0.5 the counts are A 1, B 0, C 1, with no trend.

**ctl-56852 was dropped as a control (2026-11-04).** It used to count as a false alarm in A, B and C. The reviewer
said `handleOrId.refresh` throws when the native timer returns null, and Angular later fixed exactly that
(`36c2197539`, issue #70044, August 2026). So the "false alarm" was a real bug that nobody had reported yet when the
dataset was built. That is a limitation of "no known bug" controls: some of them hide bugs, which inflates the
false-alarm rate.

## Repeat experiment: A vs B, 4 independent samples per cell

Angular bug cases only. Sample 0 is the original run; samples 1–3 come from `bench-eval run --repos angular
--conditions A B --kinds bug --sample K` (results in `../claude-sonnet-5-5_effort-high_s{1,2,3}/`). That cost
$2.29 in total. `x` = judge matched a finding to the known bug.

| case | A | B |
|---|---|---|
| bug-46096 | `....` 0/4 | `....` 0/4 |
| bug-48063 | `....` 0/4 | `....` 0/4 |
| bug-48558 | `xxxx` 4/4 | `xxxx` 4/4 |
| bug-50063 | `xxxx` 4/4 | `xxxx` 4/4 |
| bug-53695 | `xxx.` 3/4 | `....` 0/4 |
| bug-55796 | `..x.` 1/4 | `....` 0/4 |
| bug-60875 | `....` 0/4 | `....` 0/4 |
| bug-63485 | `xxxx` 4/4 | `....` 0/4 |
| bug-67032 | `xxxx` 4/4 | `xxxx` 4/4 |
| bug-69309 | `xxxx` 4/4 | `xxxx` 4/4 |
| **total** | **24/40 = 60%** | **16/40 = 40%** |

- The drop reproduces in every sample (A/B hits per sample: 6/4, 6/4, 7/4, 5/4). In no case does B do better than A.
- **bug-63485** (4/4 → 0/4): with the description, the reviewer reports nothing in all four samples. The
  description argues for the change, and that heads off the EmptyError concern.
- **bug-53695** (3/4 → 0/4): this is **not** variance, which corrects the guess above. In all four B samples the
  reviewer reports the same side issue (mixed default+named imports, conf 0.3) and never the main bug. The
  description states what the PR fixes ("handle default imports"). The reviewer seems to take that claim at face
  value for the main path and only probes edge cases.
- bug-60875 is never caught under the clarified ground truth (0/4 in both conditions). Before the re-judge it was
  noisy (A 3/4, B 2/4) because the judge credited the excluded claim in some rows and not in others.
- Statistics: the per-sample effect is consistent, but only 3 of 10 cases differ (bug-53695, bug-55796,
  bug-63485; sign test over cases p = 0.25).
  The effect is driven by a few cases where the description makes a confident claim. Whether that generalizes
  needs more cases, not more repeats.

## Conclusion

1. The "lost in the large files" hypothesis is not supported. Full files (C) never change a detection versus B.
2. The PR description lowers detection on angular, reproducibly: 60% → 40% over 40 reviews per condition. The
   mechanism in the clear cases is **anchoring on the author's framing**. When the description asserts what the
   change does or why it is correct, the reviewer stops questioning that part.
3. Django shows the opposite (B ≥ A). Django culprits are landed commits whose PR descriptions are often short
   ticket references, so they give less framing to anchor on. That is a hypothesis, not yet tested.
4. The judge was inconsistent on bug-60875 until its ground truth was clarified. After that, an independent
   second judge (Fable 5.1, also given the fix commit's diff, never shown the first verdict) matched exactly the same
   findings on all 87 judgments (`judge_agreement.md`), including A 24/40 vs B 16/40 on angular. Both judges read the
   same ground-truth text, so this validates the grading, not the ground truth itself.

## Sensitivity: how bug-60875 is judged

Angular A vs B over 4 samples. The verdicts under each rule were checked by hand; the "strict" row is what the
re-judge produced.

| rule for bug-60875 | A | B | gap |
|---|---|---|---|
| original judge (inconsistent) | 27/40 | 18/40 | 9 |
| **strict: "clause is inverted" alone does not count (decision taken)** | **24/40** | **16/40** | **8** |
| lenient, applied consistently (8 of 9 rows match) | 28/40 | 19/40 | 9 |

The gap is 8–9 hits under every rule, so the main finding does not depend on this case.

**Limitation:** the bug-60875 ground truth was clarified after the results were seen. The clarification works
*against* the main hypothesis: it removes more A hits (3) than B hits (2), but it narrows the gap by only one hit.
