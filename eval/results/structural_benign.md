# Evaluation: structural_benign

- Corpus: `structural_benign.jsonl` (20 entries)
- L2 variant: `ensemble` · render-diff: True · mode: in-process
- Run at: 2026-11-01 04:56:38

## Detection rate by layer combination

Injection subsets show TPR, the benign subset shows FPR. A combination flags an entry if any of its layers scores ≥ 0.5.

| combo | benign (FPR) |
|---|---|
| L1 | 0.00 (n=20) |
| L2 | 0.05 (n=20) |
| L3 | 0.00 (n=20) |
| L4 | 0.00 (n=20) |
| L5 | 0.00 (n=20) |
| L1+L2 | 0.05 (n=20) |
| L1-L3 | 0.05 (n=20) |
| L1-L4 | 0.05 (n=20) |
| L1-L5 | 0.05 (n=20) |
| no-L2 | 0.00 (n=20) |

## Pipeline verdicts

STRIP includes BLOCKs that were sanitised (flagged parts removed, remainder re-screened clean).

| subset | PASS | STRIP | of which sanitised | BLOCK |
|---|---|---|---|---|
| benign | 19 | 1 | 0 | 0 |

## Latency (ms per tool response)

| stage | mean | p95 |
|---|---|---|
| L1 | 0.0 | 0.0 |
| L2 | 79.6 | 442.9 |
| L3 | 0.0 | 0.0 |
| L4 | 144.4 | 154.4 |
| L5 | 0.3 | 1.6 |
| total | 224.4 | 1276.3 |
| sync (L1+L2+L4+L5) | 224.4 | 1276.3 |
| rescreen | 27.7 | 27.7 |
