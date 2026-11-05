# Results: claude-sonnet-5-5_effort-high_s3

## Detection rate (bug cases)

| repo/condition | conf ≥ 0.0 | conf ≥ 0.5 | conf ≥ 0.8 |
|---|---|---|---|
| all/A | 50% (5/10, CI 24%–76%) | 30% (3/10, CI 11%–60%) | 0% (0/10, CI 0%–28%) |
| all/B | 40% (4/10, CI 17%–69%) | 30% (3/10, CI 11%–60%) | 0% (0/10, CI 0%–28%) |
| angular/A | 50% (5/10, CI 24%–76%) | 30% (3/10, CI 11%–60%) | 0% (0/10, CI 0%–28%) |
| angular/B | 40% (4/10, CI 17%–69%) | 30% (3/10, CI 11%–60%) | 0% (0/10, CI 0%–28%) |

## False-alarm rate (controls)

| repo/condition | conf ≥ 0.0 | conf ≥ 0.5 | conf ≥ 0.8 |
|---|---|---|---|
| all/A | n/a | n/a | n/a |
| all/B | n/a | n/a | n/a |
| angular/A | n/a | n/a | n/a |
| angular/B | n/a | n/a | n/a |

## By merge date (all repos, any confidence)

| era/condition | detection | false alarms |
|---|---|---|
| merged 2024+/A | 50% (3/6, CI 19%–81%) | n/a |
| merged 2024+/B | 33% (2/6, CI 10%–70%) | n/a |
| merged before 2024/A | 50% (2/4, CI 15%–85%) | n/a |
| merged before 2024/B | 50% (2/4, CI 15%–85%) | n/a |

## Calibration (all repos)

| condition | findings | Brier | bins (mean conf → accuracy, n) |
|---|---|---|---|
| A | 5 | 0.287 | 0.25→1.00 (1); 0.47→1.00 (2); 0.60→1.00 (2) |
| B | 4 | 0.281 | 0.35→1.00 (1); 0.52→1.00 (3) |

Cases excluded after the run: none

Failed reviews (excluded): 0

Spend recorded in this run: $0.73

## Charts

![detection_false_alarms](detection_false_alarms.png)
![calibration](calibration.png)
