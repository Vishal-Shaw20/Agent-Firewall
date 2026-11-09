# Evaluation: headline_test

- Corpus: `corpus.jsonl` (40 entries, held-out test split)
- L2 variant: `ensemble` · render-diff: True · mode: in-process
- Run at: 2026-11-01 04:47:01

## Detection rate by layer combination

Injection subsets show TPR, the benign subset shows FPR. A combination flags an entry if any of its layers scores ≥ 0.5.

| combo | explicit (TPR) | implicit (TPR) | structural (TPR) | benign (FPR) |
|---|---|---|---|---|
| L1 | 0.50 (n=8) | 0.14 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L2 | 1.00 (n=8) | 0.91 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L3 | 0.00 (n=8) | 0.00 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L4 | 0.38 (n=8) | 0.05 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L5 | 0.00 (n=8) | 0.00 (n=22) | 0.25 (n=4) | 0.00 (n=6) |
| L1+L2 | 1.00 (n=8) | 0.91 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L1-L3 | 1.00 (n=8) | 0.91 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L1-L4 | 1.00 (n=8) | 0.91 (n=22) | 0.00 (n=4) | 0.00 (n=6) |
| L1-L5 | 1.00 (n=8) | 0.91 (n=22) | 0.25 (n=4) | 0.00 (n=6) |
| no-L2 | 0.62 (n=8) | 0.14 (n=22) | 0.25 (n=4) | 0.00 (n=6) |

## Pipeline verdicts

STRIP includes BLOCKs that were sanitised (flagged parts removed, remainder re-screened clean).

| subset | PASS | STRIP | of which sanitised | BLOCK |
|---|---|---|---|---|
| explicit | 0 | 5 | 0 | 3 |
| implicit | 2 | 7 | 0 | 13 |
| structural | 3 | 1 | 1 | 0 |
| benign | 6 | 0 | 0 | 0 |

## Latency (ms per tool response)

| stage | mean | p95 |
|---|---|---|
| L1 | 0.1 | 0.1 |
| L2 | 402.9 | 439.1 |
| L3 | 0.0 | 0.0 |
| L4 | 91.6 | 35.6 |
| L5 | 0.3 | 0.5 |
| total | 495.0 | 469.1 |
| sync (L1+L2+L4+L5) | 495.0 | 469.1 |
| rescreen | 0.0 | 0.0 |
