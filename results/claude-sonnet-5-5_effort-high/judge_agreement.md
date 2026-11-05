# Judge agreement: claude-sonnet-5-5_effort-high and its repeats

The first judge (claude-opus-5-5) and an independent second judge (claude-fable-5-1) graded the same 87 judgments. The second judge also saw the diff of the commit that fixed the bug and never saw the first verdict. "Caught" means the judge matched at least one finding to the known bug.

| | second: caught | second: missed |
|---|---|---|
| **first: caught** | 69 | 0 |
| **first: missed** | 0 | 18 |

Agreement: **87/87 = 100%**, Cohen's kappa 1.00.

Angular A vs B over all samples: first judge A 24/40 vs B 16/40; second judge A 24/40 vs B 16/40.

## Disagreements
