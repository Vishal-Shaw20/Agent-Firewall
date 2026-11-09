"""
calibrate_l4.py — Picks the L4 content-mode STRIP threshold on TRAINING data.

Calibration pool (the held-out test split is never touched):
  - corpus train split (all subsets)
  - in-domain benign from corpus/l2_extra.jsonl, train portion: hard negatives,
    benign HTML and benign JSON. Wikipedia / news are left out: they are
    off-topic for a procurement agent and would make the threshold look
    better than it is on the content that actually causes false positives.

The score is the steering-minus-neutral margin (layers/l4_taint.py). The
threshold is set at TARGET_FPR on the benign pool.

Usage:  python -m eval.calibrate_l4   then copy the value into
        config/taint_anchors.yaml -> thresholds.strip
"""

import numpy as np
from sklearn.metrics import roc_auc_score

from layers.l4_taint import content_margins
from training.dataset import EXTRA_PATH, load_raw, split_corpus

TARGET_FPR      = 0.05
IN_DOMAIN_KINDS = {"hard_neg", "html_benign", "json_benign"}


def max_margin(content: str) -> float:
    rows = content_margins(content)
    return max((r["margin"] for r in rows), default=-1.0)


def main():
    pool = split_corpus(load_raw())["train"]
    pool += [e for e in load_raw(EXTRA_PATH)
             if e["extra_split"] == "train" and e["kind"] in IN_DOMAIN_KINDS]

    margins = {}
    for e in pool:
        margins.setdefault(e["subset"], []).append(max_margin(e["content"]))

    print(f"{'subset':<12} {'n':>4} {'min':>7} {'median':>7} {'max':>7}")
    for subset, v in margins.items():
        v = np.array(v)
        print(f"{subset:<12} {len(v):>4} {v.min():>7.3f} {np.median(v):>7.3f} {v.max():>7.3f}")

    neg = np.array(margins["benign"])
    t = float(np.quantile(neg, 1 - TARGET_FPR))
    print(f"\nSuggested strip threshold (benign FPR <= {TARGET_FPR:.0%}): {t:.3f}")
    for sub in ("explicit", "implicit"):
        pos = np.array(margins[sub])
        auc = roc_auc_score([1] * len(pos) + [0] * len(neg), list(pos) + list(neg))
        print(f"  train {sub:<9} TPR {(pos >= t).mean():.2f}   AUC vs benign {auc:.2f}")
    print(f"  train benign    FPR {(neg >= t).mean():.2f}")
    print("Set this in config/taint_anchors.yaml -> thresholds.strip")


if __name__ == "__main__":
    main()
