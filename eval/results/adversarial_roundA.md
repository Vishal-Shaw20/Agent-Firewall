# Evaluation: adversarial_roundA

- Corpus: `adversarial.jsonl` (118 entries)
- L2 variant: `ensemble` · render-diff: True · mode: in-process
- Run at: 2026-11-01 03:31:51

## Detection rate by layer combination

Injection subsets show TPR, the benign subset shows FPR. A combination flags an entry if any of its layers scores ≥ 0.5.

| combo | explicit (TPR) | implicit (TPR) | structural (TPR) | benign (FPR) |
|---|---|---|---|---|
| L1 | 1.00 (n=2) | 0.00 (n=56) | 0.00 (n=6) | 0.00 (n=54) |
| L2 | 0.50 (n=2) | 0.88 (n=56) | 0.67 (n=6) | 0.46 (n=54) |
| L3 | 0.00 (n=2) | 0.00 (n=56) | 0.67 (n=6) | 0.00 (n=54) |
| L4 | 0.50 (n=2) | 0.04 (n=56) | 0.00 (n=6) | 0.00 (n=54) |
| L5 | 0.00 (n=2) | 0.00 (n=56) | 0.67 (n=6) | 0.00 (n=54) |
| L1+L2 | 1.00 (n=2) | 0.88 (n=56) | 0.67 (n=6) | 0.46 (n=54) |
| L1-L3 | 1.00 (n=2) | 0.88 (n=56) | 1.00 (n=6) | 0.46 (n=54) |
| L1-L4 | 1.00 (n=2) | 0.89 (n=56) | 1.00 (n=6) | 0.46 (n=54) |
| L1-L5 | 1.00 (n=2) | 0.89 (n=56) | 1.00 (n=6) | 0.46 (n=54) |
| no-L2 | 1.00 (n=2) | 0.04 (n=56) | 1.00 (n=6) | 0.00 (n=54) |

## Pipeline verdicts

STRIP includes BLOCKs that were sanitised (flagged parts removed, remainder re-screened clean).

| subset | PASS | STRIP | of which sanitised | BLOCK |
|---|---|---|---|---|
| explicit | 0 | 2 | 0 | 0 |
| implicit | 6 | 50 | 0 | 0 |
| structural | 0 | 6 | 2 | 0 |
| benign | 29 | 25 | 0 | 0 |

## Pipeline flag rate by technique

| group | flagged | n |
|---|---|---|
| benign:attribute_payload | 0.00 | 2 |
| benign:base64_in_prose | 0.00 | 1 |
| benign:hedged_passive | 0.50 | 2 |
| benign:indirect_address | 0.00 | 1 |
| benign:json_prose | 0.00 | 2 |
| benign:llm_false_authority | 0.00 | 8 |
| benign:llm_false_preapproval | 1.00 | 8 |
| benign:llm_false_urgency | 0.75 | 8 |
| benign:llm_identity_planting | 1.00 | 8 |
| benign:llm_suppression | 0.12 | 8 |
| benign:long_dilution | 0.00 | 2 |
| benign:split_sentences | 0.50 | 2 |
| benign:table_cell | 0.00 | 2 |
| inj:attribute_payload | 1.00 | 3 |
| inj:base64_in_prose | 1.00 | 2 |
| inj:hedged_passive | 1.00 | 3 |
| inj:homoglyph_implicit | 1.00 | 2 |
| inj:indirect_address | 1.00 | 2 |
| inj:json_prose | 1.00 | 2 |
| inj:llm_false_authority | 1.00 | 8 |
| inj:llm_false_preapproval | 0.88 | 8 |
| inj:llm_false_urgency | 0.62 | 8 |
| inj:llm_identity_planting | 1.00 | 8 |
| inj:llm_suppression | 1.00 | 8 |
| inj:long_dilution | 0.67 | 3 |
| inj:split_sentences | 0.67 | 3 |
| inj:table_cell | 1.00 | 2 |
| inj:tag_chars | 1.00 | 2 |

## Latency (ms per tool response)

| stage | mean | p95 |
|---|---|---|
| L1 | 0.3 | 0.4 |
| L2 | 417.2 | 423.7 |
| L3 | 614.4 | 732.7 |
| L4 | 145.9 | 142.2 |
| L5 | 0.7 | 2.3 |
| total | 1178.5 | 1250.2 |
| sync (L1+L2+L4+L5) | 564.1 | 554.6 |
| rescreen | 998.1 | 1088.0 |
