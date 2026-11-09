"""
seed_compare.py — L2 run-to-run variance across training seeds.

Fine-tuning DistilBERT on a few hundred examples is not stable from seed to
seed, and that changes the numbers this project reports. This script scores
each trained seed on the same held-out sets so the variance is visible.
The model actually used is chosen by VALIDATION loss only (never by these
held-out numbers), with --select copying it into models/l2_distilbert/.

Usage:
    python -m eval.seed_compare models/l2_seed42 models/l2_seed1 models/l2_seed2 models/l2_ensemble
    python -m eval.seed_compare ... --select       (single models only)
"""

import json
import shutil
import sys
from pathlib import Path

from sklearn.metrics import roc_auc_score

import layers.l2_classifier as l2
from eval.evaluate import load_corpus, load_test_ids, SPLIT_PATH, THRESHOLD
from settings import CORPUS_PATH, PROBES_DIR, RESULTS_DIR, ROOT


def score_dir(model_dir: Path) -> dict:
    if model_dir.name == "l2_ensemble":
        variant = "ensemble"
    else:
        variant = "seed_eval"
        l2.VARIANT_DIRS["seed_eval"] = model_dir
        l2._loaded.pop("seed_eval", None)
    run = lambda c: l2.run_l2_classifier(c, variant=variant)["score"]

    test = [e for e in load_corpus(CORPUS_PATH) if e["id"] in load_test_ids(SPLIT_PATH)]
    by = {}
    for e in test:
        by.setdefault(e["subset"], []).append(run(e["content"]))
    ben = by["benign"]
    out = {"val_loss": json.load(open(model_dir / "val_metrics.json"))["eval_loss"]
           if (model_dir / "val_metrics.json").exists() else None}
    for sub in ("explicit", "implicit", "structural"):
        out[f"{sub}_tpr"] = sum(s >= THRESHOLD for s in by[sub]) / len(by[sub])
        out[f"{sub}_auc"] = roc_auc_score([1] * len(by[sub]) + [0] * len(ben), by[sub] + ben)
    out["benign_fpr"] = sum(s >= THRESHOLD for s in ben) / len(ben)
    for name in ("concealment", "structural_benign"):
        rows = [r for r in load_corpus(PROBES_DIR / f"{name}.jsonl") if r["label"] == 0]
        out[f"{name}_fpr"] = sum(run(r["content"]) >= THRESHOLD for r in rows) / len(rows)
    return out


def main():
    dirs = [ROOT / a for a in sys.argv[1:] if not a.startswith("--")]
    rows = {d.name: score_dir(d) for d in dirs}
    cols = ["val_loss", "explicit_tpr", "implicit_tpr", "structural_tpr", "benign_fpr",
            "implicit_auc", "concealment_fpr", "structural_benign_fpr"]
    print(f"{'model':<16}" + "".join(f"{c:>22}" for c in cols))
    for name, r in rows.items():
        print(f"{name:<16}" + "".join(f"{r[c]:>22.3f}" if r[c] is not None else f"{'—':>22}" for c in cols))

    md = ["# L2 seed variance", "",
          "Held-out test split (TPR / FPR / AUC) and benign probe sets (FPR). The model used is "
          "picked by validation loss only.", "",
          "| model | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for name, r in rows.items():
        md.append(f"| {name} | " + " | ".join(f"{r[c]:.3f}" if r[c] is not None else "—" for c in cols) + " |")
    best = min((n for n in rows if rows[n]["val_loss"] is not None), key=lambda n: rows[n]["val_loss"])
    md += ["", f"Lowest validation loss: **{best}**."]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "l2_seed_variance.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"\nLowest validation loss: {best}")

    if "--select" in sys.argv and best != "l2_distilbert":
        target = ROOT / "models" / "l2_distilbert"
        src = ROOT / "models" / best
        for f in src.iterdir():
            if f.is_file():
                shutil.copy2(f, target / f.name)
        print(f"Copied {best} into {target}")


if __name__ == "__main__":
    main()
