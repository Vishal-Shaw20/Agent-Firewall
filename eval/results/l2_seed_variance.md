# L2 seed variance

Held-out test split (TPR / FPR / AUC) and benign probe sets (FPR). The model used is picked by validation loss only.

| model | val_loss | explicit_tpr | implicit_tpr | structural_tpr | benign_fpr | implicit_auc | concealment_fpr | structural_benign_fpr |
|---|---|---|---|---|---|---|---|---|
| l2_seed42 | 0.087 | 1.000 | 0.955 | 0.000 | 0.000 | 0.992 | 0.150 | 0.050 |
| l2_seed1 | 0.070 | 1.000 | 0.955 | 0.000 | 0.000 | 0.992 | 1.000 | 0.050 |
| l2_seed2 | 0.100 | 1.000 | 0.955 | 0.250 | 0.000 | 1.000 | 0.900 | 0.050 |
| l2_ensemble | 0.102 | 1.000 | 0.909 | 0.000 | 0.000 | 1.000 | 0.275 | 0.050 |

Lowest validation loss: **l2_seed1**.
