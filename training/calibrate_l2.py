"""
calibrate_l2.py — Recomputes an L2 variant's threshold.json from its
validation split without retraining (train_l2 does the same at the end).
For an ensemble, the members' probabilities are averaged first.

Usage:
    python -m training.calibrate_l2                          # full
    python -m training.calibrate_l2 --variant explicit_only
    python -m training.calibrate_l2 --variant ensemble
"""

import json
import sys

import numpy as np

from layers.l2_classifier import ENSEMBLE_DIRS, ENSEMBLES, VARIANT_DIRS, raw_prob
from training.dataset import build_dataset
from training.train_l2 import VARIANT_SUBSETS, calibrate_thresholds


def main(variant: str):
    # Seeds and ensembles of the full model share its training subsets and val split
    subsets = VARIANT_SUBSETS.get(variant, VARIANT_SUBSETS["full"])
    _, _, split, _ = build_dataset(train_subsets=subsets)

    probs  = np.array([raw_prob(e["l2_input"], variant) for e in split["val"]])
    labels = np.array([e["label"] for e in split["val"]])
    thresholds = calibrate_thresholds(probs, labels)

    if variant in ENSEMBLES:
        out_dir = ENSEMBLE_DIRS[variant]
        out_dir.mkdir(parents=True, exist_ok=True)
        thresholds["members"] = ENSEMBLES[variant]
        val_loss = float(np.mean(-np.log(np.clip(np.where(labels == 1, probs, 1 - probs), 1e-7, 1))))
        json.dump({"eval_loss": val_loss, "members": ENSEMBLES[variant]},
                  open(out_dir / "val_metrics.json", "w", encoding="utf-8"), indent=2)
    else:
        out_dir = VARIANT_DIRS[variant]
    with open(out_dir / "threshold.json", "w", encoding="utf-8") as f:
        json.dump(thresholds, f, indent=2)
    print(json.dumps(thresholds, indent=2))


if __name__ == "__main__":
    main(sys.argv[sys.argv.index("--variant") + 1] if "--variant" in sys.argv else "full")
