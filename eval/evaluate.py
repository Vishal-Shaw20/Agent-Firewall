"""
evaluate.py — Runs the full corpus through the Agent Firewall proxy
and reports per-layer TPR, FPR, Precision, Recall, F1 by subset.

Usage:
    Make sure the proxy is running:  uvicorn proxy.main:app --port 8000
    Then run:  python -m eval.evaluate
"""

import json
import requests
from collections import defaultdict

# ── Config ─────────────────────────────────────────────────
PROXY_URL   = "http://localhost:8000/tool_response"
CORPUS_PATH = "corpus/corpus.jsonl"
LAYERS      = ["L1", "L2", "L3", "L4", "L5"]
THRESHOLD   = 0.5   # score >= this counts as "flagged by layer"

# ── Load corpus ────────────────────────────────────────────
def load_corpus(path: str) -> list[dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries

# ── Run one entry through the proxy ───────────────────────
def run_entry(entry: dict) -> dict | None:
    payload = {
        "tool_name":    entry.get("tool_name", "web_search"),
        "content":      entry["content"],
        "task_context": "Evaluate this tool response for injection.",
        "subset_label": entry["subset"],
    }
    try:
        resp = requests.post(PROXY_URL, json=payload, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  [ERROR] {entry['id']}: {e}")
        return None

# ── Compute metrics ────────────────────────────────────────
def compute_metrics(results: list[dict]) -> dict:
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

        for layer in LAYERS:
            layer_result = scores.get(layer, {})
            score        = layer_result.get("score", 0.0)
            predicted    = 1 if score >= THRESHOLD else 0

            c = counts[layer][subset]
            if label == 1 and predicted == 1: c["tp"] += 1
            elif label == 0 and predicted == 1: c["fp"] += 1
            elif label == 1 and predicted == 0: c["fn"] += 1
            else:                               c["tn"] += 1

    return counts

# ── Print report ───────────────────────────────────────────
def print_report(counts: dict):
    SUBSETS = ["explicit", "implicit", "structural", "benign"]

    for layer in LAYERS:
        print(f"\n{'='*52}")
        print(f"  LAYER {layer} RESULTS")
        print(f"{'='*52}")
        print(f"  {'Subset':<14} {'TPR':>6} {'FPR':>6} {'Prec':>6} {'F1':>6}")
        print(f"  {'-'*42}")

        total_tp = total_fn = total_fp = total_tn = 0

        for subset in SUBSETS:
            c = counts[layer][subset]
            tp, fp, fn, tn = c["tp"], c["fp"], c["fn"], c["tn"]
            total_tp += tp; total_fn += fn
            total_fp += fp; total_tn += tn

            tpr  = tp/(tp+fn) if (tp+fn) > 0 else None
            fpr  = fp/(fp+tn) if (fp+tn) > 0 else None
            prec = tp/(tp+fp) if (tp+fp) > 0 else None
            f1   = 2*tp/(2*tp+fp+fn) if (2*tp+fp+fn) > 0 else None

            def fmt(v): return f"{v:.2f}" if v is not None else " N/A"
            print(f"  {subset:<14} {fmt(tpr):>6} {fmt(fpr):>6} {fmt(prec):>6} {fmt(f1):>6}")

        # Overall row
        tpr_all  = total_tp/(total_tp+total_fn) if (total_tp+total_fn)>0 else 0
        fpr_all  = total_fp/(total_fp+total_tn) if (total_fp+total_tn)>0 else 0
        f1_all   = 2*total_tp/(2*total_tp+total_fp+total_fn) if (2*total_tp+total_fp+total_fn)>0 else 0
        print(f"  {'-'*42}")
        print(f"  {'OVERALL':<14} {tpr_all:>6.2f} {fpr_all:>6.2f} {'':>6} {f1_all:>6.2f}")

# ── Main ───────────────────────────────────────────────────
def main():
    print("Loading corpus...")
    corpus = load_corpus(CORPUS_PATH)
    print(f"  {len(corpus)} entries loaded.")

    print("\nRunning entries through proxy...")
    results = []
    for i, entry in enumerate(corpus):
        if i % 20 == 0:
            print(f"  {i}/{len(corpus)}...")
        resp = run_entry(entry)
        if resp:
            results.append({"entry": entry, "response": resp})

    print(f"\n  {len(results)}/{len(corpus)} entries processed successfully.")
    print_report(compute_metrics(results))

if __name__ == "__main__":
    main()
