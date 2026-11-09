# L2 classifier ablation

Held-out test split, 40 entries. Injection subsets show TPR, benign shows FPR (threshold 0.5). Mean L2 score in brackets.

| variant | explicit | implicit | structural | benign |
|---|---|---|---|---|
| ensemble | 1.00 (0.79, n=8) | 0.91 (0.79, n=22) | 0.00 (0.06, n=4) | 0.00 (0.05, n=6) |
| full | 1.00 (0.88, n=8) | 0.95 (0.84, n=22) | 0.00 (0.03, n=4) | 0.00 (0.06, n=6) |
| explicit_only | 1.00 (0.94, n=8) | 0.00 (0.21, n=22) | 0.00 (0.12, n=4) | 0.00 (0.22, n=6) |

AUC of each injection subset against benign (threshold-free):

| variant | explicit | implicit | structural |
|---|---|---|---|
| ensemble | 1.00 | 1.00 | 0.25 |
| full | 1.00 | 0.99 | 0.21 |
| explicit_only | 1.00 | 0.26 | 0.25 |
