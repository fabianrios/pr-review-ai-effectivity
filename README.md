# pr-review-bench

**Interactive write-up with charts:** https://fabianrios.github.io/pr-review-ai-effectivity/ (source: `notebook/`)

**Question.** When Claude reviews a pull request that later turned out to introduce a bug, how often does it
catch the bug, how does that change with the amount of context it gets, and how well calibrated is its confidence?

Status: **results in (2026-11-05).** 47 bug cases and 19 controls from `angular/angular` and `django/django`,
reviewed by `claude-sonnet-5-5` (effort high) and graded by `claude-opus-5-5`. 404 reviews in total.

| repository | language | how a bug is attributed | reviewed unit | cases |
|---|---|---|---|---|
| `angular/angular` | TypeScript | phrases such as "regression introduced by #N" in commits, PRs and issue comments | the PR (`refs/pull/N/head` vs merge-base) | 14 bugs + 9 controls |
| `django/django` | Python | the convention `Regression in <commit sha>.` in fix commits | the landed commit (`sha^..sha`) | 33 bugs + 10 controls |

(One more angular bug case, bug-56852, started as a control: see finding 5.)

## Results

Conditions: **A** = diff only; **B** = A + the PR title and description; **C** = B + the full post-change files.
"Detected" means an independent judge matched at least one of the reviewer's findings to the known bug.

### In one paragraph

Claude catches a bit over half of the bugs that real maintainers merged (54–65% depending on the set) with very few
false alarms on clean changes (5% from the diff alone). Its confidence is informative: findings at ≥ 0.8 never
raised a false alarm, but they cover only 7–25% of the bugs. Giving it the full files does not help. Giving it the PR
description does not help either, on average, although a confident description can make it drop a concern it
would otherwise raise. An early result that the description *lowers* detection (60% → 40% on 10 angular cases) did
not replicate on 27 new cases (54% vs 52%), and the write-up below reports both.

### Main run: 20 bug cases + 19 controls, one sample per cell

| | A: diff | B: + description | C: + full files |
|---|---|---|---|
| detection, any confidence | 65% (13/20) | 65% (13/20) | 65% (13/20) |
| detection, confidence ≥ 0.5 | 45% | 45% | 60% |
| detection, confidence ≥ 0.8 | 25% | 10% | 20% |
| false alarms, any confidence | 5% (1/19) | 11% (2/19) | 21% (4/19) |
| false alarms, confidence ≥ 0.5 | 5% | 0% | 5% |
| false alarms, confidence ≥ 0.8 | 0% | 0% | 0% |
| Brier score (lower is better) | 0.189 | 0.190 | 0.168 |

95% Wilson intervals are wide at this size (e.g. 65% detection is 43–82%); every table with intervals is in
`results/claude-sonnet-5-5_effort-high/summary.md`.

### The description question, with 4 independent samples per cell

| set | cases | A: diff | B: + description | cases A > B / B > A | sign test p |
|---|---|---|---|---|---|
| original angular | 10 | 24/40 = 60% | 16/40 = 40% | 3 / 0 | 0.25 |
| **new cases (scale-up)** | **27** | **58/108 = 54%** | **56/108 = 52%** | **4 / 4** | **1.00** |
| of which angular | 4 | 8/16 | 8/16 | 0 / 0 | 1.00 |
| of which django | 23 | 50/92 | 48/92 | 4 / 4 | 1.00 |
| everything with 4 samples | 37 | 82/148 = 55% | 72/148 = 49% | 7 / 4 | 0.55 |

Per-case grids: `results/claude-sonnet-5-5_effort-high/angular_context_analysis.md` (original) and
`results/claude-sonnet-5-5_effort-high_scaleup/scaleup_analysis.md` (scale-up).

### Findings

1. **The PR description does not change detection on average.** The first 10 angular cases showed a large drop
   (60% → 40%, lower in every sample). On 27 new cases, picked the same way, the difference is 2 hits out of 108,
   and the cases that move split 4–4. The original effect rested on 3 cases.
2. **But a confident description can anchor the reviewer.** The clearest cases:
   - *angular bug-63485:* the PR swaps `.toPromise()` for a helper built on rxjs `first()`, which throws
     `EmptyError` when an observable completes without a value. From the diff alone the reviewer raises exactly
     that in 4/4 samples. The description argues for the change ("some observables don't complete", so take the
     first value), and with it the reviewer reports nothing in 4/4.
   - *angular bug-53695:* the PR adds default-import support to `@defer` but never sets the per-block
     `isDefaultImport` flag. Diff only: found in 3/4. With the description ("handle default imports") the reviewer
     only probes an edge case (mixed default and named imports) in 4/4 and never the main path.
   - *django bug-626d77e52a:* the description presents the change as a clean delegation to `ColPairs`/`TupleIn`;
     with it, no findings at all in 4/4 samples, while the diff-only reviewer flags the wrong table alias in 3/4
     (at low confidence, 0.2–0.35).

   Cases in the other direction exist too: on django bug-c09bceef68 (a public keyword argument removed from
   `log_actions()`) only the reviewer with the description noticed the API break (2/4 vs 0/4).
3. **Full files add noise, not detections.** In the main run C matched B on every bug case. It raised the
   reviewer's confidence (detection at ≥ 0.5: 45% → 60%) but also the false alarms (11% → 21%), and it was about
   three quarters of the cost.
4. **Confidence is meaningful but conservative.** In the main run, findings at ≥ 0.8 never raised a false alarm on
   the 19 controls and every scored one matched its bug, yet they cover only 10–25% of bugs (7–10% in the
   scale-up). Most
   correct findings sit at 0.3–0.6.
5. **Some "false alarms" are real bugs nobody had reported yet.** Control ctl-56852 (zone.js `Timeout.refresh`
   support) was flagged in every condition: `handleOrId.refresh` throws when the native timer returns `null`. It
   counted as a false alarm until a free check of later commits (`bench-eval controlcheck`) found that Angular fixed
   exactly that in August 2026 (issue #70044). It is now a bug case, caught in 8/8 reviews. Measured precision is a
   lower bound.
6. **Repeated reviews catch more.** On the 27 new cases (diff only): one review catches 54%, the union of 2 reviews
   59%, of 4 reviews 63%. Many bugs are caught in some samples and not others. (The false-alarm cost of merging was
   not measured: the new set has no controls.)
7. **About 30% of the bugs are never caught.** 8 of the 27 new cases were missed in all 8 reviews. They are
   mostly effects that need knowledge outside the diff: PostgreSQL cast semantics, multi-table inheritance,
   CSS-selector parsing across lines.

### What this suggests for automated PR review

- Review the diff **before** (or without) the author's description, or instruct the reviewer to verify the
  description's claims rather than accept them. It costs nothing on average and removes the anchoring risk.
- Don't paste whole files into the prompt. If more context is needed, retrieve it in a targeted way (callers,
  overridden methods, related queries); that is untested here and the obvious next experiment.
- Treat confidence as tiers: surface ≥ 0.8 prominently, show the rest as "worth a look" rather than dropping it.
- If recall matters more than noise, run the review twice and merge the findings.

**In practice.** These results are now used to shape the AI-assisted and human code-review policy of the author's
engineering team: where an automated bug pass sits in the workflow (before the PR, separate from convention checks),
what it reads first, and how its findings are tiered. The same harness runs on the team's private repositories, with
all private data kept out of this repository (`internal/`, git-ignored).

### How the results were checked

- **Labels:** every bug label was checked against the commit that fixed it by a different model
  (`claude-fable-5-1`, `bench-eval gtcheck`): did the change introduce the bug, and is the description accurate?
  All 47 labels in use hold, 3 with minor wording notes (`data/GROUND_TRUTH_CHECK.md`). The 27 scale-up labels were drafted by
  `claude-opus-5-5` (`data/DRAFTS.md`), and the author reviewed the judgment calls on the inclusion rule.
- **Controls:** for each control, later commits that deleted its lines were listed and read
  (`data/CONTROLS_CHECK.md`); this is what exposed ctl-56852.
- **Judge:** an independent second judge (`claude-fable-5-1`, also given the fix commit's diff, never shown the
  first verdict) re-graded all 87 judgments of the original set and matched exactly the same findings in 87/87
  (`results/claude-sonnet-5-5_effort-high/judge_agreement.md`).
- **One label was clarified after results were seen** (angular bug-60875: a finding that says one clause is inverted
  no longer counts, because its fix would remove subscriptions the code needs). The clarification works *against*
  the original description effect (it removed 3 A hits and 2 B hits); every reading of that case gives a gap of 8–9
  hits on the original set.

### Limitations

- **Small numbers.** 10–33 cases per repository; most intervals are ±20 points. The description effect could still
  exist at a few points' size.
- **Labels are model-checked, not expert-checked.** Two different models agree on each label and verdict, but no
  Angular or Django maintainer reviewed them, and both judges read the same ground-truth text.
- **Controls are "no known bug", not bug-free** (see finding 5). The new cases have no controls, so false alarms
  come from the main run only.
- **New verdicts were not cross-judged** (budget); the second judge covered the original 87.
- **One reviewer model and effort level.** Results may differ for other models, prompts or agentic reviewers that
  can open files.
- **Public code may be in the training data.** Changes merged after the reviewer's training cutoff would be the
  cleaner test; `report --cutoff` supports that split once the cutoff is known.

Cost: about $34 in API calls ($8.53 for the main run, $25.20 for repeats, validation and the scale-up).

## Repository layout

```
src/review_bench/
  common.py       BENCH_REPO selection, paths, cached + throttled `gh` search, git helpers
  mine.py         angular: discover candidate bug-introducing PRs     -> data/angular/candidates.jsonl
  controls.py     angular: matched control PRs                         -> data/angular/controls.yaml
  mine_django.py  django:  discover (Regression in <sha>) + controls   -> data/django/...
  cases.py        both:    self-contained cases                        -> data/<repo>/cases/<id>/
  checkpoint.py   both:    review table                                -> data/<repo>/CHECKPOINT.md
  prompts.py      reviewer + judge prompts, JSON schemas, the three context conditions
  llm.py          Anthropic SDK wrapper: disk cache, cost ledger, hard budget cap
  evaluate.py     bench-eval estimate | run | rejudge | report | audit (+ the commands below)
  metrics.py      detection, false alarms, calibration (Wilson intervals, Brier), A/B grid with sign test
  cross_judge.py  bench-eval crossjudge: independent second judge, given the fix diff
  ground_truth.py bench-eval fetchfixes | controlcheck | gtcheck: evidence checks on labels and controls
  drafting.py     bench-eval draft: apply the inclusion rule to new candidates, draft ground truths
data/<repo>/
  candidates.jsonl, mining_funnel.json   raw mining output (public data)
  curation.yaml                          bug cases + ground truth; exclusions and decisions with reasons
  controls.yaml                          selected controls (status: exclude drops one)
  drafts.jsonl                           scale-up drafts (bench-eval draft)
  ground_truth_check.jsonl               label checks (bench-eval gtcheck)
  cases/<id>/pr.json diff.patch files/   what the reviewer may see
  cases/<id>/answer.json                 hidden answer, never shown to the reviewer
  cases/bug-*/fix.patch fix_message.txt  the fixing commit (judges and checks only)
data/DRAFTS.md, GROUND_TRUTH_CHECK.md, CONTROLS_CHECK.md   readable reports of the checks
results/<run>/                           reviews, judgments, summary.md, metrics.json, charts, analyses
  LICENSE.txt                            the source repository's license (angular: MIT, django: BSD-3-Clause)
cache/   (git-ignored) API response cache
work/    (git-ignored) local clones
```

## Dataset construction

**Bug label.** A change is a *bug case* only when a later fix explicitly attributes a bug to it, the faulty code is
visibly present in the change's diff, and the bug is a behavioral defect. Docs, CI, build and purely visual CSS
regressions are excluded. Ground truth is one paragraph written from the fix commit and its diff: what goes wrong,
under which conditions, and where. Diffs are at most 400 changed lines. Excluded candidates stay in `curation.yaml`
with a reason.

**Angular evidence.**
1. **Commit messages** (`git log --grep`): "regression caused by #N", "introduced in #N", "accidentally broken in
   #N", and reverts naming the reverted PR.
2. **Merged PR descriptions**, found with GitHub search, for the same phrases.
3. **Issue comments**, found with GitHub search (`in:comments`), e.g. "this was caused by #N".

**Django evidence.** Fix commits on `main` contain `Regression in <sha>.`, which names the exact culprit commit.
- The reviewer-visible description is the matching GitHub PR's body. A PR is accepted only if its title names one
  of the commit's tickets or matches its subject.
- Trac ticket text is not used: `code.djangoproject.com` was not reachable from the mining environment.

**Scale-up batch (`scaleup-2026-11`).** 27 further bug cases, chosen from candidates with the strongest evidence
(django: the fix rewrites lines the culprit added; angular: a fixing commit could be found on `main`). Opus applied
the inclusion rule to 43 candidates and drafted ground truths (31 qualified); 4 were then dropped (an Oracle-only
fix, a markup-only bug, a plain revert whose mechanism had to be guessed, a build-config change). Fable checked
every remaining label against its fix commit, and the author reviewed the judgment calls.

**Selection preference.** Culprits merged in 2024 or later come first. Older candidates stay in `candidates.jsonl`
for the scale-up and for a date-split analysis.

**Controls.** Each bug case gets one control:
- same area (angular: `area:` label plus directory; django: module, e.g. `django/db`, `django/contrib/auth`);
- merged within about a year of the bug and at least 180 days before collection;
- diff 0.5–2× the bug's size.

A control is rejected if:
- a later fix or revert references it;
- *(django)* a later commit whose message mentions fix/bug/crash/regression/incorrect deletes or rewrites lines it
  added;
- it is itself a revert.

Controls are "no known bug", not "bug-free".

**Leakage guards.** The reviewer sees only the change's own title, description, diff and post-change file contents.
Fix links live in `answer.json`. A description that mentions the later fix, its ticket or its commit is flagged;
none currently are. `fix_tickets` lists only the fix's own tickets, not the culprit's ticket, which fix messages
often cite and which is public anyway.

### Mining funnels (collected 2026-11-03)

| angular/angular (PRs since 2021) | count | | django/django (fixes since 2024) | count |
|---|---|---|---|---|
| evidence snippets | 384 | | (fix, culprit) pairs | 142 |
| distinct culprit PRs | 260 | | distinct culprit commits | 116 |
| landed and fetchable | 250 | | diff ≤ 400 lines | 103 |
| diff ≤ 400 lines | 165 | | touch shipped code | 100 |
| touch shipped code | 135 | | culprit merged 2024+ | 68 |
| **verified, included** | **10** | | **verified, included** | **10** |

### What mining taught us (methodological findings)

- **"Merged" is ambiguous on angular/angular.** Until about 2025, Angular's merge tool landed PRs, so GitHub shows
  them as *closed*, and `main` carries a `PR Close #N` trailer. A naive `is:merged` filter dropped 306 of 324
  culprits. Fix: merged = GitHub-merged **or** closed by a commit on `main`.
- **Phrase-based attribution is noisy; convention-based attribution is not.** Angular needed 384 evidence snippets to
  yield 10 verifiable cases. Django's `Regression in <sha>` convention gives 100 usable candidates, and 63 of them
  pass an automatic check: the fix deletes or rewrites lines the culprit added.
- **Even explicit attributions can be wrong.** An Angular fix blames #66891 for a highlighting regression, but the
  faulty rule came from another commit (`e850643b1b`). Every case is verified against the culprit's diff.
- **The automatic line-overlap check supports, but cannot replace, manual review.** On the 10 Angular cases it
  fires for 6. The other 4 are fixes that *add* missing handling, or that live in another file than the faulty
  change (e.g. a consumer of a changed wire format).
- **"No known bug" needs more than "never blamed".** The first Django control picked for an http case had a real
  bug that was fixed without a `Regression in` line, because it was a new feature, not a regression. The stricter
  rewrite check above now catches this; the README limitations note that controls may still hide bugs.
- **"Never blamed" is time-dependent.** A control can turn out to have a bug years later: ctl-56852 was fixed in
  August 2026, after the dataset was built. Re-checking controls against later commits (`controlcheck`) is cheap.
- **Model-drafted labels need policy filters.** The drafting model accepted an Oracle-only fix, a markup-only bug
  and a build-config change; the written policy caught them, a second model's check did not (it checks accuracy,
  not scope).
- **Reverts are a poor label source.** Most Angular reverts follow internal Google breakages with no public
  reason. They are excluded as bug cases, and excluded as controls.

## Evaluation harness

**Reviewer.**
- Default model `claude-sonnet-5-5` at effort `high`; configurable with `--model` / `--effort`.
- One system prompt for every condition: it asks for concrete defects only (not style), says that reporting nothing
  is fine, and asks for structured JSON findings `{file, line, description, severity, confidence}`.
- JSON is enforced with structured outputs (`output_config.format`).
- Context conditions, each extending the previous one:
  - **A:** diff only.
  - **B:** A + title and description (PR-template HTML comments stripped; for Django the commit message is appended).
  - **C:** B + full post-change contents of every changed file.

**Judge.**
- Default `claude-opus-5-5`; configurable with `--judge-model`.
- Sees the diff, the ground truth and the numbered findings, and returns which findings (if any) match the known bug,
  with a justification.
- Only reviews of bug cases that have at least one finding are judged. No findings means not detected, with no call.
- `bench-eval audit` writes a seeded random sample of verdicts to `results/<run>/judge_audit.md` for checking by hand.
- `bench-eval crossjudge` re-grades every verdict with a second model that also sees the fix commit's diff, and
  writes the agreement with every disagreement to `results/<run>/judge_agreement.md`.

**Metrics** (`results/<run>/summary.md`, `metrics.json`). All rates come with 95% Wilson intervals.
- **Detection rate:** share of bug cases with at least one matching finding, overall and at confidence ≥ 0.5 / 0.8.
- **False-alarm rate:** share of controls with at least one finding at confidence ≥ 0 / 0.5 / 0.8.
- **By merge date:** detection and false alarms for changes merged before 2024 vs 2024+, and before/after the
  reviewer's training cutoff when `bench-eval report --cutoff YYYY-MM-DD` is given (a contamination check).
- **Calibration:** five reliability bins (width 0.2) and Brier score over findings with a known label. A finding that matches the bug
  counts as 1; any finding on a control counts as 0. Unmatched findings on bug cases are excluded, because they may be
  real, different bugs.
- **Failed reviews** (refusal, truncation, unparseable output) are excluded from rates and listed separately.
- **Charts** (`results/<run>/*.png`, drawn by `report`): detection and false-alarm rates per condition and repo with
  their intervals, and a reliability diagram per condition. `summary.md` holds the same numbers as tables.

**Cost control.**
- Every request is cached on disk by a hash of its full parameters, so reruns are free.
- Every paid call is appended to a ledger with its token usage and cost.
- A run refuses to start if the estimate exceeds the remaining budget (`--budget`, default $10, over all runs), never
  starts without `--yes`, and stops issuing calls once the ledger reaches the cap.
- `bench-eval estimate` prints the expected cost first. It's offline by default; `--count` uses the free
  `count_tokens` endpoint. A `--pilot` run (1 bug + 1 control per repo, all conditions) measures real output-token
  usage, and later estimates use it.
- `cache/` is git-ignored. Results files hold findings, verdicts and token usage, never credentials.

**Design choices worth stating.**
- The API base URL is pinned to `https://api.anthropic.com`, because the build environment sets `ANTHROPIC_BASE_URL`
  to an internal endpoint. Override it with `BENCH_API_BASE_URL`.
- Server-side refusal fallbacks are deliberately **off**. A fallback would answer with a different model and
  contaminate the measurement. Refusals are recorded and reported instead.
- No sampling parameters are sent, so the model defaults apply.

```bash
uv run bench-eval estimate                 # offline cost estimate
uv run bench-eval run --pilot --yes        # ~$1-2: measures real usage
uv run bench-eval estimate                 # re-estimate with measured output tokens
uv run bench-eval run --yes [--budget N]   # full run (ask the author first if > $10)
uv run bench-eval report && uv run bench-eval audit

# repeats and the scale-up (A and B only, 4 samples)
uv run bench-eval run --repos angular --conditions A B --kinds bug --sample 1 --yes
uv run bench-eval run --batch scaleup-2026-11 --conditions A B --name claude-sonnet-5-5_effort-high_scaleup --sample 1 --yes

# checks
uv run bench-eval fetchfixes                       # free: fix commit per bug case
uv run bench-eval controlcheck                     # free: later commits that touched each control
uv run bench-eval gtcheck --yes                    # ~$0.11/case: labels against their fix commits
uv run bench-eval crossjudge --yes                 # ~$0.08/verdict: independent second judge
uv run bench-eval rejudge --cases bug-60875 --yes  # re-judge stored reviews after a label change
```

`--sample K` (K ≥ 1) repeats the same requests as an independent draw into `results/<run>_sK/`.
`status: exclude` on a case in `curation.yaml` / `controls.yaml` drops its stored reviews from `report` for free.

## Reproduce the dataset

```bash
uv sync
gh auth login                                   # GitHub search API only

# angular/angular
git clone --filter=blob:none https://github.com/angular/angular work/angular
uv run bench-mine --since 2021-01-01
# edit data/angular/curation.yaml
uv run bench-controls --today 2026-11-03
uv run bench-cases && uv run bench-checkpoint

# django/django
git clone --filter=blob:none https://github.com/django/django work/django
uv run bench-mine-django discover --since 2024-01-01
# edit data/django/curation.yaml
uv run bench-mine-django controls --today 2026-11-03
BENCH_REPO=django/django uv run bench-cases && BENCH_REPO=django/django uv run bench-checkpoint

# scale-up batch: draft, then build only the tagged cases (a full bench-cases rebuilds every case)
uv run bench-eval draft --yes                      # -> data/DRAFTS.md; copy accepted drafts into curation.yaml
uv run bench-cases --batch scaleup-2026-11
BENCH_REPO=django/django uv run bench-cases --batch scaleup-2026-11
```
