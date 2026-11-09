# Evaluation: headline_all

- Corpus: `corpus.jsonl` (200 entries)
- L2 variant: `ensemble` · render-diff: True · mode: in-process
- Run at: 2026-11-01 04:51:03

## Detection rate by layer combination

Injection subsets show TPR, the benign subset shows FPR. A combination flags an entry if any of its layers scores ≥ 0.5.

| combo | explicit (TPR) | implicit (TPR) | structural (TPR) | benign (FPR) |
|---|---|---|---|---|
| L1 | 0.50 (n=40) | 0.04 (n=110) | 0.00 (n=20) | 0.00 (n=30) |
| L2 | 1.00 (n=40) | 0.98 (n=110) | 0.30 (n=20) | 0.03 (n=30) |
| L3 | 0.00 (n=40) | 0.00 (n=110) | 0.00 (n=20) | 0.00 (n=30) |
| L4 | 0.50 (n=40) | 0.04 (n=110) | 0.00 (n=20) | 0.00 (n=30) |
| L5 | 0.00 (n=40) | 0.00 (n=110) | 0.80 (n=20) | 0.00 (n=30) |
| L1+L2 | 1.00 (n=40) | 0.98 (n=110) | 0.30 (n=20) | 0.03 (n=30) |
| L1-L3 | 1.00 (n=40) | 0.98 (n=110) | 0.30 (n=20) | 0.03 (n=30) |
| L1-L4 | 1.00 (n=40) | 0.98 (n=110) | 0.30 (n=20) | 0.03 (n=30) |
| L1-L5 | 1.00 (n=40) | 0.98 (n=110) | 0.80 (n=20) | 0.03 (n=30) |
| no-L2 | 0.75 (n=40) | 0.06 (n=110) | 0.80 (n=20) | 0.00 (n=30) |

## Pipeline verdicts

STRIP includes BLOCKs that were sanitised (flagged parts removed, remainder re-screened clean).

| subset | PASS | STRIP | of which sanitised | BLOCK |
|---|---|---|---|---|
| explicit | 0 | 8 | 1 | 32 |
| implicit | 2 | 16 | 0 | 92 |
| structural | 4 | 10 | 5 | 6 |
| benign | 29 | 1 | 0 | 0 |

## Latency (ms per tool response)

| stage | mean | p95 |
|---|---|---|
| L1 | 0.1 | 0.1 |
| L2 | 382.0 | 424.1 |
| L3 | 0.0 | 0.0 |
| L4 | 39.5 | 32.4 |
| L5 | 0.3 | 0.3 |
| total | 421.9 | 454.4 |
| sync (L1+L2+L4+L5) | 421.9 | 454.4 |
| rescreen | 47.2 | 213.0 |
