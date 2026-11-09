"""
evaluate.py — Runs a corpus through the Agent Firewall pipeline and reports
detection rates per layer, per layer-combination and per subset (SRS 8.2).

By default only the held-out test split (models/l2_distilbert/split.json,
written by training.train_l2) of the headline corpus is evaluated, so L2 is
never scored on its own training data. Probe sets (--corpus corpus/probes/...)
are evaluated in full; their injections already come from the test split.

Usage:
    python -m eval.evaluate --inprocess                  # no proxy / Redis needed
    python -m eval.evaluate                              # via a running proxy:
                                                         #   uvicorn proxy.main:app --port 8000
Options:
    --corpus <path>      evaluate another corpus file (e.g. a probe set)
    --all                full headline corpus (L2 numbers include training data)
    --l2-variant <name>  ensemble (default) | full | explicit_only | seedN (in-process only)
    --where field=value  evaluate only matching entries (e.g. adv_split=heldout)
    --no-render          skip L3 render-diff (rule-based concealment only)
    --tag <name>         name for the saved results file
"""

import os
import sys
import json
import time
import requests
import numpy as np
from collections import defaultdict
from pathlib import Path

from settings import CORPUS_PATH, MODELS_DIR, RESULTS_DIR
from layers.l2_classifier import DEFAULT_VARIANT

# ── Config ─────────────────────────────────────────────────
PROXY_URL   = "http://localhost:8000/tool_response"
SPLIT_PATH  = MODELS_DIR / "l2_distilbert" / "split.json"
LAYERS      = ["L1", "L2", "L3", "L4", "L5"]
THRESHOLD   = 0.5   # score >= this counts as "flagged by layer"
SUBSETS     = ["explicit", "implicit", "structural", "benign"]

# Layer combinations reported side by side (SRS 8.2 / FR12).
# L1-L4 vs L1-L5 is the structural-layer ablation.
COMBOS = {
    "L1":       ["L1"],
    "L2":       ["L2"],
    "L3":       ["L3"],
    "L4":       ["L4"],
    "L5":       ["L5"],
    "L1+L2":    ["L1", "L2"],
    "L1-L3":    ["L1", "L2", "L3"],
    "L1-L4":    ["L1", "L2", "L3", "L4"],
    "L1-L5":    LAYERS,
    "no-L2":    ["L1", "L3", "L4", "L5"],
}

def _arg(name: str, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default

# ── Load corpus ────────────────────────────────────────────
def load_corpus(path) -> list[dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries

def load_test_ids(path) -> set[str]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Split file not found at '{path}'. "
            f"Run: python -m training.train_l2  (or pass --all)"
        )
    with open(path, "r", encoding="utf-8") as f:
        return set(json.load(f)["test"])

def _payload(entry: dict) -> dict:
    return {
        "tool_name":    entry.get("tool_name", "web_fetch"),
        "content":      entry["content"],
        "task_context": entry.get("task", "Summarize this tool response."),
        "subset_label": entry["subset"],
    }

# ── Run one entry ──────────────────────────────────────────
def run_entry_http(entry: dict) -> dict | None:
    try:
        resp = requests.post(PROXY_URL, json=_payload(entry), timeout=30)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [ERROR] {entry['id']}: {e}")
        return None

def make_inprocess_runner(l2_variant: str, render: bool):
    from proxy.interceptor import evaluate_response
    from proxy.models import ToolResponseRequest
    def run(entry: dict) -> dict:
        req = ToolResponseRequest(**_payload(entry))
        return evaluate_response(req, l2_variant=l2_variant, render=render).model_dump()
    return run

# ── Compute metrics ────────────────────────────────────────
def compute_metrics(results: list[dict], layers=LAYERS) -> dict:
    """
    results: list of {"entry": corpus_entry, "response": proxy_response}
    Returns nested dict: metrics[layer][subset] = {tp, fp, tn, fn}
    """
    counts = defaultdict(lambda: defaultdict(lambda: {"tp":0,"fp":0,"tn":0,"fn":0}))

    for r in results:
        entry    = r["entry"]
        response = r["response"]
        label    = entry["label"]      # 1 = injection, 0 = benign
        subset   = entry["subset"]
        scores   = response.get("layer_scores", {})

        for layer in layers:
            layer_result = scores.get(layer, {})
            score        = layer_result.get("score", 0.0)
            predicted    = 1 if score >= THRESHOLD else 0

            c = counts[layer][subset]
            if label == 1 and predicted == 1: c["tp"] += 1
            elif label == 0 and predicted == 1: c["fp"] += 1
            elif label == 1 and predicted == 0: c["fn"] += 1
            else:                               c["tn"] += 1

    return counts

def combo_rates(results: list[dict]) -> dict:
    """rates[combo][subset] = TPR (injection subsets) or FPR (benign)."""
    rates = {}
    for name, layers in COMBOS.items():
        per_subset = defaultdict(list)
        for r in results:
            scores = r["response"].get("layer_scores", {})
            hit = any(scores.get(l, {}).get("score", 0.0) >= THRESHOLD for l in layers)
            per_subset[r["entry"]["subset"]].append(hit)
        rates[name] = {s: (sum(v) / len(v), len(v)) for s, v in per_subset.items()}
    return rates

def verdict_breakdown(results: list[dict]) -> dict:
    out = defaultdict(lambda: {"PASS": 0, "STRIP": 0, "BLOCK": 0, "sanitized": 0})
    for r in results:
        out[r["entry"]["subset"]][r["response"]["verdict"]] += 1
        out[r["entry"]["subset"]]["sanitized"] += bool(r["response"].get("sanitized"))
    return out

def latency_summary(results: list[dict]) -> dict:
    lat = defaultdict(list)
    for r in results:
        for k, v in r["response"].get("latency_ms", {}).items():
            lat[k].append(v)
        ms = r["response"].get("latency_ms", {})
        lat["sync (L1+L2+L4+L5)"].append(sum(ms.get(l, 0) for l in ("L1", "L2", "L4", "L5")))
    return {k: {"mean": float(np.mean(v)), "p95": float(np.percentile(v, 95))} for k, v in lat.items()}

def per_group_rates(results: list[dict], key: str) -> dict:
    """Pipeline flag rate grouped by an entry field (e.g. technique)."""
    groups = defaultdict(list)
    for r in results:
        groups[(r["entry"]["label"], r["entry"].get(key))].append(r["response"]["verdict"] != "PASS")
    return {f"{'inj' if lab else 'benign'}:{g}": (sum(v) / len(v), len(v))
            for (lab, g), v in sorted(groups.items(), key=str)}

# ── Print report ───────────────────────────────────────────
def print_report(counts: dict):
    """Per-layer TPR/FPR by subset (kept from the original runner)."""
    for layer in counts:
        print(f"\n  {layer}: " + "  ".join(
            f"{s}={_rate(counts[layer][s])}" for s in SUBSETS if s in counts[layer]))

def _rate(c: dict) -> str:
    if c["tp"] + c["fn"]:
        return f"TPR {c['tp'] / (c['tp'] + c['fn']):.2f}"
    return f"FPR {c['fp'] / (c['fp'] + c['tn']):.2f}"

def print_matrix(rates: dict):
    subsets = [s for s in SUBSETS if any(s in v for v in rates.values())]
    header = "  " + f"{'combo':<8}" + "".join(
        f"{(s + (' FPR' if s == 'benign' else ' TPR')):>16}" for s in subsets)
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, per in rates.items():
        print("  " + f"{name:<8}" + "".join(
            f"{per[s][0]:>12.2f} ({per[s][1]:>2})" if s in per else f"{'—':>16}" for s in subsets))

def to_markdown(meta: dict, rates: dict, verdicts: dict, latency: dict, groups: dict | None) -> str:
    subsets = [s for s in SUBSETS if any(s in v for v in rates.values())]
    lines = [f"# Evaluation: {meta['tag']}", "",
             f"- Corpus: `{meta['corpus']}` ({meta['n']} entries{', held-out test split' if meta['test_only'] else ''})",
             f"- L2 variant: `{meta['l2_variant']}` · render-diff: {meta['render']} · mode: {meta['mode']}",
             f"- Run at: {meta['timestamp']}", "",
             "## Detection rate by layer combination", "",
             "Injection subsets show TPR, the benign subset shows FPR. A combination flags an entry "
             f"if any of its layers scores ≥ {THRESHOLD}.", "",
             "| combo | " + " | ".join(f"{s} ({'FPR' if s == 'benign' else 'TPR'})" for s in subsets) + " |",
             "|---|" + "---|" * len(subsets)]
    for name, per in rates.items():
        lines.append(f"| {name} | " + " | ".join(
            f"{per[s][0]:.2f} (n={per[s][1]})" if s in per else "—" for s in subsets) + " |")
    lines += ["", "## Pipeline verdicts", "",
              "STRIP includes BLOCKs that were sanitised (flagged parts removed, remainder re-screened clean).", "",
              "| subset | PASS | STRIP | of which sanitised | BLOCK |", "|---|---|---|---|---|"]
    for s in subsets:
        v = verdicts[s]
        lines.append(f"| {s} | {v['PASS']} | {v['STRIP']} | {v['sanitized']} | {v['BLOCK']} |")
    if groups:
        lines += ["", "## Pipeline flag rate by technique", "", "| group | flagged | n |", "|---|---|---|"]
        lines += [f"| {g} | {r:.2f} | {n} |" for g, (r, n) in groups.items()]
    lines += ["", "## Latency (ms per tool response)", "", "| stage | mean | p95 |", "|---|---|---|"]
    lines += [f"| {k} | {v['mean']:.1f} | {v['p95']:.1f} |" for k, v in latency.items()]
    return "\n".join(lines) + "\n"

# ── Main ───────────────────────────────────────────────────
def main():
    corpus_path = Path(_arg("--corpus", CORPUS_PATH))
    inprocess   = "--inprocess" in sys.argv
    l2_variant  = _arg("--l2-variant", DEFAULT_VARIANT)
    render      = "--no-render" not in sys.argv
    where       = _arg("--where")                     # e.g. adv_split=heldout
    is_headline = corpus_path.resolve() == Path(CORPUS_PATH).resolve()
    test_only   = is_headline and "--all" not in sys.argv
    tag         = _arg("--tag", corpus_path.stem
                       + ("" if l2_variant == DEFAULT_VARIANT else f"_{l2_variant}")
                       + (f"_{where.split('=', 1)[1]}" if where else ""))

    print("Loading corpus...")
    corpus = load_corpus(corpus_path)
    print(f"  {len(corpus)} entries loaded from {corpus_path.name}.")
    if where:
        field, value = where.split("=", 1)
        corpus = [e for e in corpus if str(e.get(field)) == value]
        print(f"  --where {where}: {len(corpus)} entries.")

    if test_only:
        test_ids = load_test_ids(SPLIT_PATH)
        corpus   = [e for e in corpus if e["id"] in test_ids]
        print(f"  Evaluating held-out test split only: {len(corpus)} entries.")
    elif is_headline:
        print("  --all: evaluating full corpus (L2 scores include training data)")

    run = make_inprocess_runner(l2_variant, render) if inprocess else run_entry_http
    print(f"\nRunning entries ({'in-process' if inprocess else PROXY_URL})...")
    results = []
    for i, entry in enumerate(corpus):
        if i % 20 == 0:
            print(f"  {i}/{len(corpus)}...")
        resp = run(entry)
        if resp:
            results.append({"entry": entry, "response": resp})
    print(f"\n  {len(results)}/{len(corpus)} entries processed successfully.")

    print("\nPer-layer rates by subset:")
    print_report(compute_metrics(results))

    rates = combo_rates(results)
    print("\nDetection rate by layer combination (TPR; benign = FPR):\n")
    print_matrix(rates)

    verdicts = verdict_breakdown(results)
    print("\nPipeline verdicts:")
    for s in SUBSETS:
        if s in verdicts:
            print(f"  {s:<12} {dict(verdicts[s])}")

    groups = per_group_rates(results, "technique") if any("technique" in r["entry"] for r in results) else None
    latency = latency_summary(results)
    print("\nLatency (ms): " + ", ".join(f"{k} {v['mean']:.0f}/{v['p95']:.0f}" for k, v in latency.items()))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    meta = {"tag": tag, "corpus": corpus_path.name, "n": len(results), "test_only": test_only,
            "l2_variant": l2_variant, "render": render,
            "mode": "in-process" if inprocess else "http",
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")}
    with open(RESULTS_DIR / f"{tag}.json", "w", encoding="utf-8") as f:
        json.dump({"meta": meta, "rates": rates, "verdicts": verdicts, "latency": latency,
                   "groups": groups,
                   "entries": [{"id": r["entry"]["id"], "subset": r["entry"]["subset"],
                                "label": r["entry"]["label"], "verdict": r["response"]["verdict"],
                                "sanitized": r["response"].get("sanitized", False),
                                "returned_content": r["response"].get("content", ""),
                                "scores": {l: r["response"]["layer_scores"].get(l, {}).get("score")
                                           for l in LAYERS}} for r in results]},
                  f, indent=2, default=dict)
    with open(RESULTS_DIR / f"{tag}.md", "w", encoding="utf-8") as f:
        f.write(to_markdown(meta, rates, verdicts, latency, groups))
    print(f"\nSaved {RESULTS_DIR / (tag + '.json')} and .md")

if __name__ == "__main__":
    main()
