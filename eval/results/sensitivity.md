# Sensitivity to the assumed attack mix

Per-subset rates from the held-out test split (40 entries; structural from all 20 structural entries, with L2 counted on test entries only), reweighted to each mix. TPR = detection rate over the attacks in the mix; FPR doesn't depend on the mix; precision = share of flagged items that are attacks.

## Per-subset rates used

| detector | implicit (22) | explicit (8) | structural (20) | benign FPR (6) | hard-benign FPR (28 adversarial look-alikes) |
|---|---|---|---|---|---|
| pipeline (all layers) | 0.91 | 1.00 | 0.80 | 0.00 | 0.11 |
| L1 heuristic only | 0.14 | 0.50 | 0.00 | 0.00 | 0.00 |
| L2 classifier only | 0.91 | 1.00 | 0.00 | 0.00 | 0.11 |
| pipeline without L2 | 0.14 | 0.62 | 0.80 | 0.00 | 0.00 |

## Aggregate TPR by mix

| detector | SRS real-world-calibrated (55/20/10/15) | resume-study injected split (77/8/0/15) | balanced (35/35/15/15) | structural-heavy (30/20/35/15) | benchmark-like explicit-heavy (5/70/10/15) |
|---|---|---|---|---|---|
| pipeline (all layers) | 0.92 | 0.92 | 0.93 | 0.89 | 0.97 |
| L1 heuristic only | 0.21 | 0.17 | 0.26 | 0.17 | 0.42 |
| L2 classifier only | 0.82 | 0.92 | 0.79 | 0.56 | 0.88 |
| pipeline without L2 | 0.33 | 0.18 | 0.45 | 0.52 | 0.62 |

## Precision by mix

| detector | SRS real-world-calibrated (55/20/10/15) | resume-study injected split (77/8/0/15) | balanced (35/35/15/15) | structural-heavy (30/20/35/15) | benchmark-like explicit-heavy (5/70/10/15) |
|---|---|---|---|---|---|
| pipeline (all layers) | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| L1 heuristic only | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| L2 classifier only | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| pipeline without L2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Precision by mix, with the hard-benign FPR

The test split's 6 benign entries are all PASSed, which makes precision 1.00 by construction. With the FPR measured on benign text written in the attacks' style:

| detector | SRS real-world-calibrated (55/20/10/15) | resume-study injected split (77/8/0/15) | balanced (35/35/15/15) | structural-heavy (30/20/35/15) | benchmark-like explicit-heavy (5/70/10/15) |
|---|---|---|---|---|---|
| pipeline (all layers) | 0.98 | 0.98 | 0.98 | 0.98 | 0.98 |
| L1 heuristic only | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| L2 classifier only | 0.98 | 0.98 | 0.98 | 0.97 | 0.98 |
| pipeline without L2 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |

## Precision of the full pipeline at realistic prevalence

TPR 0.92 (SRS mix). Precision = p x TPR / (p x TPR + (1 - p) x FPR) for attack prevalence p. Flags here are mostly STRIPs, which keep the rest of the response.

| benign FPR source | FPR | p = 0.15 | p = 0.05 | p = 0.01 | p = 0.001 |
|---|---|---|---|---|---|
| hard-benign look-alikes | 0.11 | 0.60 | 0.31 | 0.08 | 0.01 |
| benign HTML with hidden elements | 0.55 | 0.23 | 0.08 | 0.02 | 0.00 |

The L1 heuristic's aggregate TPR is +0.21 higher on the benchmark-like mix than on the real-world-calibrated one: the same detector looks much better when evaluated on the style most benchmarks use. The test split is small (8 explicit, 22 implicit, 6 benign), so per-subset rates carry wide error bars.
