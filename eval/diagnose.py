"""
diagnose.py — Inspect raw L2 probability scores on benign vs implicit examples.
Run: python -m eval.diagnose
"""

import json
import torch
from transformers import DistilBertForSequenceClassification, DistilBertTokenizerFast

MODEL_DIR  = "models/l2_distilbert"
MAX_LENGTH = 256

def load_corpus():
    entries = []
    with open("corpus/corpus.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries

def main():
    print("Loading model...")
    tok = DistilBertTokenizerFast.from_pretrained(MODEL_DIR)
    mdl = DistilBertForSequenceClassification.from_pretrained(MODEL_DIR)
    mdl.eval()

    entries  = load_corpus()
    benign   = [e for e in entries if e["subset"] == "benign"]
    implicit = [e for e in entries if e["subset"] == "implicit"][:10]
    explicit = [e for e in entries if e["subset"] == "explicit"][:5]

    def score(text: str) -> float:
        inp = tok(text, return_tensors="pt", truncation=True,
                  max_length=MAX_LENGTH, padding="max_length")
        with torch.no_grad():
            logits = mdl(**inp).logits
        return torch.softmax(logits, dim=1)[0][1].item()

    print("\n" + "="*60)
    print("  BENIGN SCORES  (label=0, want score < 0.5)")
    print("="*60)
    benign_scores = []
    for e in benign:
        s = score(e["content"])
        benign_scores.append(s)
        flag = "❌ WRONG" if s >= 0.5 else "✅ ok"
        print(f"  {s:.4f}  {flag}  {e['content'][:65]}...")

    print("\n" + "="*60)
    print("  IMPLICIT SCORES  (label=1, want score >= 0.5)")
    print("="*60)
    implicit_scores = []
    for e in implicit:
        s = score(e["content"])
        implicit_scores.append(s)
        flag = "✅ ok" if s >= 0.5 else "❌ MISSED"
        print(f"  {s:.4f}  {flag}  {e['content'][:65]}...")

    print("\n" + "="*60)
    print("  EXPLICIT SCORES  (label=1, want score >= 0.5)")
    print("="*60)
    for e in explicit:
        s = score(e["content"])
        flag = "✅ ok" if s >= 0.5 else "❌ MISSED"
        print(f"  {s:.4f}  {flag}  {e['content'][:65]}...")

    print("\n" + "="*60)
    print("  SCORE DISTRIBUTION SUMMARY")
    print("="*60)
    print(f"  Benign   — avg: {sum(benign_scores)/len(benign_scores):.4f}  "
          f"min: {min(benign_scores):.4f}  max: {max(benign_scores):.4f}")
    print(f"  Implicit — avg: {sum(implicit_scores)/len(implicit_scores):.4f}  "
          f"min: {min(implicit_scores):.4f}  max: {max(implicit_scores):.4f}")

    # Suggest threshold
    avg_benign   = sum(benign_scores) / len(benign_scores)
    avg_implicit = sum(implicit_scores) / len(implicit_scores)
    suggested    = round((avg_benign + avg_implicit) / 2, 2)
    print(f"\n  Suggested threshold: {suggested:.2f}")
    print("  (set THRESHOLD in eval/evaluate.py if this separates the classes)")

if __name__ == "__main__":
    main()
