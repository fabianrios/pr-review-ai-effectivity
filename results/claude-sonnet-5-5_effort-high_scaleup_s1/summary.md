# Results: claude-sonnet-5-5_effort-high_scaleup_s1

## Detection rate (bug cases)

| repo/condition | conf ≥ 0.0 | conf ≥ 0.5 | conf ≥ 0.8 |
|---|---|---|---|
| all/A | 44% (12/27, CI 28%–63%) | 30% (8/27, CI 16%–48%) | 11% (3/27, CI 4%–28%) |
| all/B | 52% (14/27, CI 34%–69%) | 33% (9/27, CI 19%–52%) | 7% (2/27, CI 2%–23%) |
| angular/A | 50% (2/4, CI 15%–85%) | 50% (2/4, CI 15%–85%) | 0% (0/4, CI 0%–49%) |
| angular/B | 50% (2/4, CI 15%–85%) | 50% (2/4, CI 15%–85%) | 0% (0/4, CI 0%–49%) |
| django/A | 43% (10/23, CI 26%–63%) | 26% (6/23, CI 13%–46%) | 13% (3/23, CI 5%–32%) |
| django/B | 52% (12/23, CI 33%–71%) | 30% (7/23, CI 16%–51%) | 9% (2/23, CI 2%–27%) |

## False-alarm rate (controls)

| repo/condition | conf ≥ 0.0 | conf ≥ 0.5 | conf ≥ 0.8 |
|---|---|---|---|
| all/A | n/a | n/a | n/a |
| all/B | n/a | n/a | n/a |
| angular/A | n/a | n/a | n/a |
| angular/B | n/a | n/a | n/a |
| django/A | n/a | n/a | n/a |
| django/B | n/a | n/a | n/a |

## By merge date (all repos, any confidence)

| era/condition | detection | false alarms |
|---|---|---|
| merged 2024+/A | 44% (12/27, CI 28%–63%) | n/a |
| merged 2024+/B | 52% (14/27, CI 34%–69%) | n/a |

## Calibration (all repos)

| condition | findings | Brier | bins (mean conf → accuracy, n) |
|---|---|---|---|
| A | 13 | 0.236 | 0.25→1.00 (1); 0.46→1.00 (7); 0.60→1.00 (2); 0.82→1.00 (3) |
| B | 15 | 0.249 | 0.15→1.00 (1); 0.47→1.00 (9); 0.63→1.00 (3); 0.82→1.00 (2) |

Cases excluded after the run: angular/bug-62083

Failed reviews (excluded): 0

Spend recorded in this run: $2.42

## Charts

![detection_false_alarms](detection_false_alarms.png)
![calibration](calibration.png)
