"""
ablation.py — Classifier ablation (SRS 8.2): the explicit-only-trained L2
vs the explicit+implicit-trained L2, scored on the identical held-out test
split of the headline corpus.

Usage:  python -m eval.ablation
"""

import json

from sklearn.metrics import roc_auc_score

from eval.evaluate import load_corpus, load_test_ids, SPLIT_PATH, SUBSETS, THRESHOLD
from layers.l2_classifier import run_l2_classifier, VARIANT_DIRS, ENSEMBLES
from settings import CORPUS_PATH, RESULTS_DIR

# The deployed ensemble, the single validation-selected model, and the ablation
VARIANTS = ["ensemble", "full", "explicit_only"]


def main():
    test_ids = load_test_ids(SPLIT_PATH)
    singles = [m for v in VARIANTS for m in ENSEMBLES.get(v, [v])]
    for variant in singles:
        other = load_test_ids(VARIANT_DIRS[variant] / "split.json")
        assert other == test_ids, f"{variant} was trained with a different test split"

    entries = [e for e in load_corpus(CORPUS_PATH) if e["id"] in test_ids]
    rows = {}
    for variant in VARIANTS:
        per = {}
        for e in entries:
            s = run_l2_classifier(e["content"], variant=variant)["score"]
            per.setdefault(e["subset"], []).append(s)
        rows[variant] = {
            sub: {"rate": sum(x >= THRESHOLD for x in v) / len(v),
                  "mean_score": sum(v) / len(v), "n": len(v)}
            for sub, v in per.items()
        }
        # Threshold-free separation of each injection subset from benign
        for sub in ("explicit", "implicit", "structural"):
            y = [1] * len(per[sub]) + [0] * len(per["benign"])
            rows[variant][sub]["auc_vs_benign"] = roc_auc_score(y, per[sub] + per["benign"])

    print(f"\nL2 classifier ablation on the held-out test split ({len(entries)} entries)")
    print("Injection subsets: TPR; benign: FPR. Mean score in brackets.\n")
    print(f"  {'variant':<15}" + "".join(f"{s:>20}" for s in SUBSETS))
    for variant, per in rows.items():
        print(f"  {variant:<15}" + "".join(
            f"{per[s]['rate']:>11.2f} ({per[s]['mean_score']:.2f})" for s in SUBSETS))
    print("\n  AUC vs benign (threshold-free):")
    for variant, per in rows.items():
        print(f"  {variant:<15}" + "".join(
            f"{per[s]['auc_vs_benign']:>20.2f}" for s in SUBSETS if s != "benign"))

    md = ["# L2 classifier ablation", "",
          f"Held-out test split, {len(entries)} entries. Injection subsets show TPR, benign shows FPR "
          f"(threshold {THRESHOLD}). Mean L2 score in brackets.", "",
          "| variant | " + " | ".join(SUBSETS) + " |", "|---|" + "---|" * len(SUBSETS)]
    for variant, per in rows.items():
        md.append(f"| {variant} | " + " | ".join(
            f"{per[s]['rate']:.2f} ({per[s]['mean_score']:.2f}, n={per[s]['n']})" for s in SUBSETS) + " |")
    md += ["", "AUC of each injection subset against benign (threshold-free):", "",
           "| variant | explicit | implicit | structural |", "|---|---|---|---|"]
    for variant, per in rows.items():
        md.append(f"| {variant} | " + " | ".join(
            f"{per[s]['auc_vs_benign']:.2f}" for s in ("explicit", "implicit", "structural")) + " |")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "l2_ablation.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (RESULTS_DIR / "l2_ablation.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"\nSaved {RESULTS_DIR / 'l2_ablation.md'}")


if __name__ == "__main__":
    main()
