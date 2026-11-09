"""
dataset.py — Loads corpus.jsonl and prepares HuggingFace Datasets
for DistilBERT fine-tuning.

Split is shuffled (fixed seed) and stratified by subset, so every subset
(explicit / implicit / structural / benign) appears in train, val and test:
  train (70%) — fine-tuning
  val   (10%) — checkpoint selection during training
  test  (20%) — never seen during training; used by eval/evaluate.py
"""

import json
import random
from collections import defaultdict
from datasets import Dataset
from transformers import DistilBertTokenizerFast
from settings import CORPUS_PATH, ROOT
from layers.l2_classifier import l2_text

EXTRA_PATH  = ROOT / "corpus" / "l2_extra.jsonl"
ADV_PATH    = ROOT / "corpus" / "adversarial" / "adversarial.jsonl"

MODEL_NAME  = "distilbert-base-uncased"
MAX_LENGTH  = 256   # shorter = faster on CPU
SEED        = 42
VAL_RATIO   = 0.10
TEST_RATIO  = 0.20

def load_raw(path=CORPUS_PATH) -> list[dict]:
    entries = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    return entries

def split_corpus(raw: list[dict], seed: int = SEED) -> dict[str, list[dict]]:
    """
    Returns {"train": [...], "val": [...], "test": [...]},
    shuffled and stratified by subset.
    """
    by_subset = defaultdict(list)
    for e in raw:
        by_subset[e["subset"]].append(e)

    rng   = random.Random(seed)
    split = {"train": [], "val": [], "test": []}

    for subset in sorted(by_subset):
        items = by_subset[subset][:]
        rng.shuffle(items)
        n_test = max(1, round(len(items) * TEST_RATIO))
        n_val  = max(1, round(len(items) * VAL_RATIO))
        split["test"]  += items[:n_test]
        split["val"]   += items[n_test:n_test + n_val]
        split["train"] += items[n_test + n_val:]

    return split

def build_dataset(path: str = CORPUS_PATH, train_subsets: set[str] | None = None) -> tuple:
    """
    Returns (train_dataset, val_dataset, split, tokenizer).
    `split` holds the raw entries so the caller can persist the test ids.

    train_subsets restricts train/val to those subsets (e.g. explicit + benign
    for the explicit-only ablation). The split itself is computed on the full
    corpus first, so the held-out test set is identical across variants.

    Extra training data (corpus/l2_extra.jsonl, built by corpus.build_l2_extra)
    is appended to train / val by its own `extra_split` field. It never enters
    the test split.
    """
    split = split_corpus(load_raw(path))
    if EXTRA_PATH.exists():
        for e in load_raw(EXTRA_PATH):
            split[e["extra_split"]].append(e)
    # M7: the DEV half of the adversarial set (reviewed attacks + benign
    # look-alikes; "weak" generated attacks are left out as label-ambiguous).
    # The held-out half is never used for training or calibration.
    if ADV_PATH.exists():
        for e in load_raw(ADV_PATH):
            if e["adv_split"] == "dev" and e.get("review") != "weak":
                split["val" if int(e["id"].split("_")[1]) % 5 == 0 else "train"].append(e)
    if train_subsets is not None:
        for part in ("train", "val"):
            split[part] = [e for e in split[part] if e["subset"] in train_subsets]

    # Same input transform as inference: JSON entries are reduced to their prose
    # string values, and entries with no prose (encoded carriers) are left to L5.
    for part in ("train", "val"):
        split[part] = [dict(e, l2_input=t) for e in split[part]
                       if (t := l2_text(e["content"])) is not None]

    def to_hf(data):
        return Dataset.from_dict({
            "text":  [d["l2_input"] for d in data],
            "label": [d["label"]   for d in data],
        })

    # Tokenize
    tokenizer = DistilBertTokenizerFast.from_pretrained(MODEL_NAME)

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            padding="max_length",
            truncation=True,
            max_length=MAX_LENGTH,
        )

    train_ds = to_hf(split["train"]).map(tokenize, batched=True)
    val_ds   = to_hf(split["val"]).map(tokenize, batched=True)

    train_ds.set_format("torch", columns=["input_ids", "attention_mask", "label"])
    val_ds.set_format("torch",   columns=["input_ids", "attention_mask", "label"])

    print(f"Train: {len(split['train'])} | Val: {len(split['val'])} | Test (held out): {len(split['test'])}")
    return train_ds, val_ds, split, tokenizer

if __name__ == "__main__":
    build_dataset()
