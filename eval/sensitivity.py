"""
sensitivity.py — How much do the headline numbers depend on the assumed
attack mix? (SRS Section 12: "report results at multiple alternative splits")

Takes the per-subset detection rates measured on the held-out test split
(eval/results/headline_test.json, written by eval.evaluate) and reweights them
to alternative explicit / implicit / structural / benign mixes:

  TPR(mix)       = sum over attack subsets of share x subset TPR, / attack share
  FPR(mix)       = benign FPR (independent of the attack mix)
  precision(mix) = attack share x TPR / (attack share x TPR + benign share x FPR)

Reported for the full pipeline (any layer >= 0.5) and for single layers, so a
detector that only looks good on an explicit-heavy benchmark mix shows up.

Two estimates are less noisy than the 40-entry test split allows:
  - structural rate: all 20 structural entries (headline_all.json). Only L2
    learns from the corpus, so an L2 hit counts only on test-split entries.
  - precision is given twice: with the test split's benign FPR (6 entries)
    and with the FPR on the 28 held-out adversarial benign look-alikes
    (adversarial_roundB.json), which are written in the attacks' own style.

Usage:  python -m eval.sensitivity
"""

import json

from eval.evaluate import SPLIT_PATH, load_test_ids
from settings import RESULTS_DIR

MIXES = {
    "SRS real-world-calibrated (55/20/10/15)":  {"implicit": .55, "explicit": .20, "structural": .10, "benign": .15},
    "resume-study injected split (77/8/0/15)":  {"implicit": .77, "explicit": .08, "structural": .00, "benign": .15},
    "balanced (35/35/15/15)":                   {"implicit": .35, "explicit": .35, "structural": .15, "benign": .15},
    "structural-heavy (30/20/35/15)":           {"implicit": .30, "explicit": .20, "structural": .35, "benign": .15},
    "benchmark-like explicit-heavy (5/70/10/15)": {"implicit": .05, "explicit": .70, "structural": .10, "benign": .15},
}
DETECTORS = {
    "pipeline (all layers)": ["L1", "L2", "L3", "L4", "L5"],
    "L1 heuristic only":     ["L1"],
    "L2 classifier only":    ["L2"],
    "pipeline without L2":   ["L1", "L3", "L4", "L5"],
}
ATTACKS = ("implicit", "explicit", "structural")


def hit(e: dict, layers: list[str], test_ids: set | None = None) -> bool:
    return any((e["scores"].get(l) or 0) >= 0.5 for l in layers
               if l != "L2" or test_ids is None or e["id"] in test_ids)


def subset_rates(entries: list[dict], layers: list[str]) -> dict:
    per = {}
    for e in entries:
        per.setdefault(e["subset"], []).append(hit(e, layers))
    return {s: sum(v) / len(v) for s, v in per.items()}


def aggregate(rates: dict, mix: dict, hard_fpr: float) -> dict:
    attack_share = sum(mix[s] for s in ATTACKS)
    tpr_mass = sum(mix[s] * rates.get(s, 0.0) for s in ATTACKS)
    prec = lambda fpr: tpr_mass / (tpr_mass + mix["benign"] * fpr) if tpr_mass + mix["benign"] * fpr else 0.0
    return {"tpr": tpr_mass / attack_share, "fpr": rates.get("benign", 0.0),
            "precision": prec(rates.get("benign", 0.0)), "precision_hard": prec(hard_fpr)}


def main():
    load = lambda name: json.load(open(RESULTS_DIR / f"{name}.json", encoding="utf-8"))["entries"]
    entries = load("headline_test")
    structural = [e for e in load("headline_all") if e["subset"] == "structural"]
    hard_benign = [e for e in load("adversarial_roundB") if int(e["label"]) == 0]
    test_ids = load_test_ids(SPLIT_PATH)
    rows = {}
    for det, layers in DETECTORS.items():
        rates = subset_rates(entries, layers)
        rates["structural"] = sum(hit(e, layers, test_ids) for e in structural) / len(structural)
        hard_fpr = sum(hit(e, layers) for e in hard_benign) / len(hard_benign)
        rows[det] = {"rates": rates, "hard_benign_fpr": hard_fpr,
                     "mixes": {m: aggregate(rates, w, hard_fpr) for m, w in MIXES.items()}}

    lines = ["# Sensitivity to the assumed attack mix", "",
             "Per-subset rates from the held-out test split (40 entries; structural from all 20 "
             "structural entries, with L2 counted on test entries only), reweighted to each mix. "
             "TPR = detection rate over the attacks in the mix; FPR doesn't depend on the mix; "
             "precision = share of flagged items that are attacks.", "",
             "## Per-subset rates used", "",
             "| detector | implicit (22) | explicit (8) | structural (20) | benign FPR (6) "
             "| hard-benign FPR (28 adversarial look-alikes) |", "|---|---|---|---|---|---|"]
    for det, r in rows.items():
        lines.append(f"| {det} | " + " | ".join(f"{r['rates'].get(s, 0):.2f}"
                                               for s in ("implicit", "explicit", "structural", "benign"))
                     + f" | {r['hard_benign_fpr']:.2f} |")
    lines += ["", "## Aggregate TPR by mix", "",
              "| detector | " + " | ".join(MIXES) + " |", "|---|" + "---|" * len(MIXES)]
    for det, r in rows.items():
        lines.append(f"| {det} | " + " | ".join(f"{r['mixes'][m]['tpr']:.2f}" for m in MIXES) + " |")
    lines += ["", "## Precision by mix", "",
              "| detector | " + " | ".join(MIXES) + " |", "|---|" + "---|" * len(MIXES)]
    for det, r in rows.items():
        lines.append(f"| {det} | " + " | ".join(f"{r['mixes'][m]['precision']:.2f}" for m in MIXES) + " |")
    lines += ["", "## Precision by mix, with the hard-benign FPR", "",
              "The test split's 6 benign entries are all PASSed, which makes precision 1.00 by "
              "construction. With the FPR measured on benign text written in the attacks' style:", "",
              "| detector | " + " | ".join(MIXES) + " |", "|---|" + "---|" * len(MIXES)]
    for det, r in rows.items():
        lines.append(f"| {det} | " + " | ".join(f"{r['mixes'][m]['precision_hard']:.2f}" for m in MIXES) + " |")

    # Base rate: the mixes above have 85% attacks; real traffic is mostly benign
    # (about 1% of resumes in the production study carried an injection).
    pipe = rows["pipeline (all layers)"]
    tpr = pipe["mixes"]["SRS real-world-calibrated (55/20/10/15)"]["tpr"]
    fprs = {"hard-benign look-alikes": pipe["hard_benign_fpr"]}
    conceal = RESULTS_DIR / "concealment.json"
    if conceal.exists():
        ben = [e for e in json.load(open(conceal, encoding="utf-8"))["entries"] if int(e["label"]) == 0]
        fprs["benign HTML with hidden elements"] = sum(hit(e, DETECTORS["pipeline (all layers)"]) for e in ben) / len(ben)
    prevalences = [0.15, 0.05, 0.01, 0.001]
    lines += ["", "## Precision of the full pipeline at realistic prevalence", "",
              f"TPR {tpr:.2f} (SRS mix). Precision = p x TPR / (p x TPR + (1 - p) x FPR) for "
              "attack prevalence p. Flags here are mostly STRIPs, which keep the rest of the response.", "",
              "| benign FPR source | FPR | " + " | ".join(f"p = {q:g}" for q in prevalences) + " |",
              "|---|---|" + "---|" * len(prevalences)]
    for name, fpr in fprs.items():
        cells = [q * tpr / (q * tpr + (1 - q) * fpr) if fpr else 1.0 for q in prevalences]
        lines.append(f"| {name} | {fpr:.2f} | " + " | ".join(f"{c:.2f}" for c in cells) + " |")
        pipe.setdefault("prevalence", {})[name] = dict(zip(map(str, prevalences), cells))

    l1 = rows["L1 heuristic only"]["mixes"]
    gap = l1["benchmark-like explicit-heavy (5/70/10/15)"]["tpr"] - l1["SRS real-world-calibrated (55/20/10/15)"]["tpr"]
    lines += ["", f"The L1 heuristic's aggregate TPR is {gap:+.2f} higher on the benchmark-like mix than on the "
              "real-world-calibrated one: the same detector looks much better when evaluated on the style "
              "most benchmarks use. The test split is small (8 explicit, 22 implicit, 6 benign), "
              "so per-subset rates carry wide error bars."]
    (RESULTS_DIR / "sensitivity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    json.dump(rows, open(RESULTS_DIR / "sensitivity.json", "w", encoding="utf-8"), indent=2)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
