"""
adversarial_compare.py — M7 before/after on the HELD-OUT half of the
adversarial set (corpus/adversarial/adversarial.jsonl).

Reads two eval.evaluate result files:
  Round A  eval/results/adversarial_roundA.json  (all entries, before the dev-only patches)
  Round B  eval/results/adversarial_roundB.json  (held-out only, after them)
and reports, on held-out entries only:
  - detection per technique, before and after (primary = reviewed attacks;
    full = also the "weak" generated attacks), benign FPR the same way;
  - the residual bypasses (attacks the pipeline still PASSes);
  - a leakage check over attacks delivered in stripped form.

Leakage: the adversarial entries carry no span annotation, so "attack text"
is every sentence of >= 3 words that is unique to its entry. Sentences that
appear in two or more entries are shared page shells (titles, "Contact the
sales desk for a quote.", the red-team look-alike bodies) and are not counted.

Run:  python -m eval.adversarial_compare
"""

import json
import re
from collections import Counter, defaultdict

from settings import ROOT

ADV = ROOT / "corpus" / "adversarial" / "adversarial.jsonl"
RES = ROOT / "eval" / "results"
FLAG = ("STRIP", "BLOCK")


def sentences(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text or "")
    parts = re.split(r"(?<=[.!?])\s+|\n+|\"\s*,\s*\"", text)
    return [" ".join(p.split()) for p in parts if len(p.split()) >= 3]


def load(path):
    return {e["id"]: e for e in json.load(open(path, encoding="utf-8"))["entries"]}


def rate(rows, key):
    return f"{sum(key(r) for r in rows)}/{len(rows)}" if rows else "–"


def main():
    corpus = [json.loads(l) for l in open(ADV, encoding="utf-8") if l.strip()]
    held = [e for e in corpus if e["adv_split"] == "heldout"]
    a, b = load(RES / "adversarial_roundA.json"), load(RES / "adversarial_roundB.json")

    caught = lambda r: r["verdict"] in FLAG
    rows = []
    for e in held:
        rows.append(dict(e, A=a[e["id"]], B=b[e["id"]]))
    atk = [r for r in rows if r["label"] == 1]
    ben = [r for r in rows if r["label"] == 0]
    prim = [r for r in atk if r["primary"]]

    out = ["# M7 adversarial iteration: Round A vs Round B (held-out half)", "",
           "Round A: ensemble before the patches. Round B: after the dev-only patches "
           "(L2 sliding-window chunking; L2 retrained with dev adversarial data, 3 seeds, "
           "ensemble re-calibrated on validation). Both rows are the same held-out entries; "
           "nothing here was used for training, calibration or design.", "",
           "## Overall", "",
           "| set | n | Round A caught | Round B caught |", "|---|---|---|---|"]
    for name, rs in [("attacks, primary (reviewed steering)", prim),
                     ("attacks, full (incl. weak generated)", atk)]:
        out.append(f"| {name} | {len(rs)} | {rate(rs, lambda r: caught(r['A']))} "
                   f"| {rate(rs, lambda r: caught(r['B']))} |")
    out.append(f"| benign look-alikes (FPR) | {len(ben)} | {rate(ben, lambda r: caught(r['A']))} "
               f"| {rate(ben, lambda r: caught(r['B']))} |")

    out += ["", "## Per technique (attacks: caught; benign: flagged)", "",
            "| technique | review | n | Round A | Round B |", "|---|---|---|---|---|"]
    groups = defaultdict(list)
    for r in rows:
        groups[(r["technique"], r["review"])].append(r)
    for (tech, rev), rs in sorted(groups.items()):
        out.append(f"| {tech} | {rev} | {len(rs)} | {rate(rs, lambda r: caught(r['A']))} "
                   f"| {rate(rs, lambda r: caught(r['B']))} |")

    out += ["", "## Residual bypasses (held-out attacks Round B still PASSes)", "",
            "| id | technique | review | L1 | L2 | L3 | L4 | L5 | excerpt |", "|---|---|---|---|---|---|---|---|---|"]
    for r in atk:
        if not caught(r["B"]):
            s = r["B"]["scores"]
            txt = " ".join(re.sub(r"<[^>]+>", " ", r["content"]).split())[:110].replace("|", "/")
            out.append(f"| {r['id']} | {r['technique']} | {r['review']} | "
                       + " | ".join(f"{s.get(k, 0):.2f}" for k in ("L1", "L2", "L3", "L4", "L5"))
                       + f" | {txt}… |")

    # Leakage over attacks delivered in stripped form (Round B)
    counts = Counter(s for e in corpus for s in set(sentences(e["content"])))
    delivered = [r for r in atk if r["B"]["verdict"] in FLAG and r["B"].get("returned_content")]
    leaks = []
    for r in delivered:
        uniq = [s for s in sentences(r["content"]) if counts[s] == 1]
        kept = [s for s in uniq if s in " ".join(r["B"]["returned_content"].split())]
        if kept:
            leaks.append((r["id"], kept))
    out += ["", "## Leakage check (Round B)", "",
            f"Attacks delivered in stripped form: {len(delivered)}. "
            f"Entries where an attack sentence (unique to the entry, >= 3 words) survives: {len(leaks)}."]
    for i, kept in leaks:
        out.append(f"- {i}: " + "; ".join(f"\"{k[:100]}\"" for k in kept))

    summary = {
        "primary": {"n": len(prim), "A": sum(caught(r["A"]) for r in prim), "B": sum(caught(r["B"]) for r in prim)},
        "full": {"n": len(atk), "A": sum(caught(r["A"]) for r in atk), "B": sum(caught(r["B"]) for r in atk)},
        "benign": {"n": len(ben), "A": sum(caught(r["A"]) for r in ben), "B": sum(caught(r["B"]) for r in ben)},
        "residual": [r["id"] for r in atk if not caught(r["B"])],
        "delivered_stripped": len(delivered), "leaks": [i for i, _ in leaks],
    }
    (RES / "adversarial.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    (RES / "adversarial.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n".join(out))


if __name__ == "__main__":
    main()
