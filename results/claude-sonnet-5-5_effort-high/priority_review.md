# Priority review: the verdicts and labels most likely to be wrong

**Status (2026-11-04): all 5 recommendations accepted by the author.** bug-60875 was re-judged on 2026-11-04 (see the README).

Built from **all 87 judge verdicts** (the full run plus angular repeats s1–s3) and the run data, not from a random
sample. `judge_audit.md` stays as it is: it is the unbiased random sample the write-up cites.

Checks used to find these items: mixed verdicts for the same case and condition across samples; matches on a file
outside the ground truth's bug files; non-matches whose finding overlaps strongly with the ground truth; controls
flagged in every condition; bug cases never caught. Everything else passed these checks.

**About 15 minutes.** Items 1 and 2 decide whether the main finding holds; read those carefully.

---

## 1. bug-60875 (angular): the judge is inconsistent. **Your decision needed**

- **What:** the reviewer keeps reporting that the `defaultQueryParamsHandling` clause in
  `subscribeToNavigationEventsIfNecessary` is inverted. The judge matched that finding 5 times and rejected it
  5 times (A: 3 of 4 matched; B: 2 of 4; C: 0 of 1).
- **Why it's unclear:** the ground truth says the real bug is that the whole premise is wrong (relative links
  always need the subscription), "plus a muddled clause about the default handling". It doesn't say whether the
  clause alone counts.
- **My recommendation: does NOT count.** The finding's suggested fix (subscribe only when the default depends on
  router state) would remove subscriptions that relative links need. That's the opposite of the real fix. I'll
  write this into the ground truth and re-judge only this case (about $0.50).
- **Effect:** angular A goes from 27/40 to 24/40 and B from 18/40 to 16/40. The gap barely moves (9 → 8 points).

☑ agree (does not count) ☐ disagree (it counts) — note: accepted by the author 2026-11-04; ground truth updated, re-judge pending

## 2. bug-63485 (angular, condition A): a match on a file outside the bug files. **Confirm**

- **What:** all 4 A matches point at `utils/first_value_from.ts`. The ground truth's bug file is `recognize.ts`,
  where the fix landed.
- **Why it's probably fine:** the finding states the exact mechanism. The new helper uses `first()`, which raises
  EmptyError where `toPromise()` resolved to `undefined`. The helper is new code in this PR, and the ground truth
  describes the same mechanism. The fix went into the caller, but the faulty code is the helper.
- **My recommendation: agree with the judge (match).**
- **Why it matters:** this case is 4 of the 9-point A–B gap. If you reject it, the main finding gets much weaker
  (A 23/40 vs B 18/40).

☑ agree (match) ☐ disagree — note: accepted by the author 2026-11-04

## 3. ctl-56852 (angular control, zone.js timers): flagged in A, B and C. **Confirm**

- **What:** the reviewer says the new code reads `handleOrId.refresh`, which throws a TypeError if the native
  `setTimeout` returns `undefined` or `null`. The old code tolerated a falsy handle (`else if (handle)`).
- **Check done:** the code is unchanged on angular `main` today (2026-11-04), 2+ years after the merge, so nobody
  found it a real bug. Real browsers and Node always return a number or a Timeout object.
- **My recommendation: keep it as a control.** The finding is a speculative edge case, so it rightly counts as a
  false alarm.

☑ agree (keep) ☐ disagree (swap) — note: accepted by the author 2026-11-04

## 4. ctl-67948 (angular control, `instanceof Element` in bootstrap): flagged in A, B and C. **Confirm**

- **What:** the reviewer says `hostElementOrOptions instanceof Element` throws a ReferenceError on the server,
  where there is no `Element` global, and mishandles `null` and elements from another realm.
- **Check done:** the line is unchanged on angular `main` today, 7 months after the merge. The common server path
  passes `undefined` or a string, which never reaches `instanceof`.
- **My recommendation: keep it as a control.** It's an edge case with no known failure report.

☑ agree (keep) ☐ disagree (swap) — note: accepted by the author 2026-11-04

## 5. bug-46096 (angular): never caught in any condition. **Decide: keep or drop**

- **What:** the faulty call `requiresInlineTypeCheckBlock(ref, shimData.file, pipes, …)` is in the diff, but
  `pipes` was passed before this PR too. You can only see that `pipes` is *every pipe in scope* from its
  declaration (`context.ts:211`), which appears only in condition C's full files.
- **My recommendation: keep it, tagged "needs file context".** It meets the rule (the changed call and the
  stricter check are in the diff), and it's a fair test of whether C helps. C didn't help here either.

☑ keep ☐ drop — note: accepted by the author 2026-11-04; decision recorded in curation.yaml

---

## Checked, nothing to do

- **bug-53695 A, sample 3 (no match):** that sample reported only the mixed-import side issue. The judge is
  consistent with every B and C verdict on the same finding. Correct.
- **bug-55796 A (1 of 4 matched):** the matched finding names the `{...options}` spread dropping getter and
  prototype properties, which is exactly the bug. The other samples didn't find it. The judge is fine.
- **bug-67032, bug-48558:** extra findings close to the ground truth were left unmatched, but another finding
  already matched. No effect.
- **bug-48063, bug-9b8e4c6d7d:** never caught, but the faulty code is clearly in the diff. They're just subtle.
  A quick ☑ in the checkpoint is enough.
