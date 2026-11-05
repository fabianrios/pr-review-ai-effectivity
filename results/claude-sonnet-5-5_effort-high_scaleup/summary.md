# Results: claude-sonnet-5-5_effort-high_scaleup

## Detection rate (bug cases)

| repo/condition | conf ≥ 0.0 | conf ≥ 0.5 | conf ≥ 0.8 |
|---|---|---|---|
| all/A | 59% (16/27, CI 41%–75%) | 37% (10/27, CI 22%–56%) | 11% (3/27, CI 4%–28%) |
| all/B | 56% (15/27, CI 37%–72%) | 33% (9/27, CI 19%–52%) | 7% (2/27, CI 2%–23%) |
| angular/A | 50% (2/4, CI 15%–85%) | 50% (2/4, CI 15%–85%) | 0% (0/4, CI 0%–49%) |
| angular/B | 50% (2/4, CI 15%–85%) | 50% (2/4, CI 15%–85%) | 0% (0/4, CI 0%–49%) |
| django/A | 61% (14/23, CI 41%–78%) | 35% (8/23, CI 19%–55%) | 13% (3/23, CI 5%–32%) |
| django/B | 57% (13/23, CI 37%–74%) | 30% (7/23, CI 16%–51%) | 9% (2/23, CI 2%–27%) |

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
| merged 2024+/A | 59% (16/27, CI 41%–75%) | n/a |
| merged 2024+/B | 56% (15/27, CI 37%–72%) | n/a |

## Calibration (all repos)

| condition | findings | Brier | bins (mean conf → accuracy, n) |
|---|---|---|---|
| A | 18 | 0.234 | 0.32→1.00 (3); 0.45→1.00 (6); 0.62→1.00 (6); 0.83→1.00 (3) |
| B | 17 | 0.253 | 0.25→1.00 (2); 0.44→1.00 (7); 0.62→1.00 (6); 0.85→1.00 (2) |

Cases excluded after the run: angular/bug-62083

Failed reviews (excluded): 0

Spend recorded in this run: $2.50

## Charts

![detection_false_alarms](detection_false_alarms.png)
![calibration](calibration.png)
