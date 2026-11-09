"""
train_l2.py — Fine-tunes DistilBERT on the Agent Firewall corpus.
Uses class-weighted loss to handle 85/15 injection/benign imbalance.

Usage:
    conda activate agentfw
    python -m training.train_l2                          # full: explicit + implicit
    python -m training.train_l2 --variant explicit_only  # ablation (SRS 8.2)
    options: --seed N  --output-dir DIR
"""

import os
import sys
import json
import torch
import numpy as np
from transformers import (
    DistilBertForSequenceClassification,
    TrainingArguments,
    Trainer,
)
from sklearn.metrics import accuracy_score, f1_score, roc_auc_score
from training.dataset import build_dataset
from layers.l2_classifier import VARIANT_DIRS

MODEL_NAME = "distilbert-base-uncased"

# Training subsets per variant. explicit_only mirrors how most public
# prompt-injection datasets are built (no implicit / structural examples).
VARIANT_SUBSETS = {
    "full":          None,
    "explicit_only": {"explicit", "benign"},
}


# ── Class weights (fix 85/15 imbalance) ──────────────────────────────
def get_class_weights(train_entries: list[dict]) -> torch.Tensor:
    # Computed on the training split only, so held-out data never leaks in
    n_benign    = sum(1 for e in train_entries if e["label"] == 0)
    n_injection = sum(1 for e in train_entries if e["label"] == 1)
    # Inverse frequency: higher weight = penalise misclassification more
    w_benign    = n_injection / n_benign
    w_injection = 1.0
    print(f"  Class weights -> benign: {w_benign:.2f}, injection: {w_injection:.2f}")
    return torch.tensor([w_benign, w_injection], dtype=torch.float)


# ── Custom Trainer with weighted loss ─────────────────────────────────
class WeightedTrainer(Trainer):
    def __init__(self, class_weights: torch.Tensor, **kwargs):
        super().__init__(**kwargs)
        self.class_weights = class_weights

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels  = inputs.pop("labels")
        outputs = model(**inputs)
        logits  = outputs.logits
        loss_fn = torch.nn.CrossEntropyLoss(weight=self.class_weights)
        loss    = loss_fn(logits, labels)
        return (loss, outputs) if return_outputs else loss


# ── Metrics ───────────────────────────────────────────────────────────
def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=1)
    probs = torch.softmax(torch.tensor(logits), dim=1)[:, 1].numpy()
    return {
        "accuracy": accuracy_score(labels, preds),
        "f1":       f1_score(labels, preds, zero_division=0),
        "auc":      roc_auc_score(labels, probs),
    }


# ── Threshold calibration on the validation split ─────────────────────
TARGET_TPR = 0.95

def calibrate_thresholds(probs: np.ndarray, labels: np.ndarray) -> dict:
    """
    strip: operating point at TARGET_TPR on val. Among thresholds that keep
           val TPR >= TARGET_TPR, take those with the lowest val FPR, and use
           the middle of that range so the threshold doesn't sit on one example.
           (Youden's J was tried first: it chased a single numeric-carrier
           example L2 can't read, which is L5's job, and dropped the threshold
           to ~0.02.)
    block: lowest threshold >= strip with val FPR <= 1%
    layers/l2_classifier.py maps these onto the decision engine's 0.5 / 0.8.
    """
    pos, neg = probs[labels == 1], probs[labels == 0]
    grid = np.linspace(0.001, 0.999, 999)
    tpr  = np.array([(pos >= t).mean() for t in grid])
    fpr  = np.array([(neg >= t).mean() for t in grid])
    feasible = tpr >= TARGET_TPR
    if not feasible.any():
        feasible = tpr == tpr.max()
    best = fpr[feasible].min()
    tied = grid[feasible & (fpr == best)]
    strip = float((tied.min() + tied.max()) / 2)
    block = next((float(t) for t in grid if t >= strip and (neg >= t).mean() <= 0.01), 1.0)
    return {
        "strip": strip, "block": block,
        "val_tpr_at_strip": float((pos >= strip).mean()), "val_fpr_at_strip": float((neg >= strip).mean()),
        "val_tpr_at_block": float((pos >= block).mean()), "val_fpr_at_block": float((neg >= block).mean()),
        "n_val_pos": int(len(pos)), "n_val_neg": int(len(neg)),
    }


# ── Main ──────────────────────────────────────────────────────────────
def main(variant: str, seed: int = 42, output_dir: str | None = None):
    OUTPUT_DIR = output_dir or str(VARIANT_DIRS[variant])
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print(f"Building dataset (variant: {variant})...")
    train_ds, val_ds, split, tokenizer = build_dataset(train_subsets=VARIANT_SUBSETS[variant])

    print(f"\nLoading base model: {MODEL_NAME}")
    model = DistilBertForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=2,
    )

    print("\nCalculating class weights...")
    class_weights = get_class_weights(split["train"])

    args = TrainingArguments(
        output_dir                  = OUTPUT_DIR,
        num_train_epochs            = 5,          # more epochs with weighted loss
        per_device_train_batch_size = 8,
        per_device_eval_batch_size  = 8,
        learning_rate               = 2e-5,
        weight_decay                = 0.01,
        warmup_steps                = 10,
        eval_strategy               = "epoch",
        save_strategy               = "epoch",
        load_best_model_at_end      = True,
        metric_for_best_model       = "auc",       # thresholds are calibrated afterwards
        logging_steps               = 10,
        use_cpu                     = True,
        report_to                   = "none",
        seed                        = seed,
    )

    trainer = WeightedTrainer(
        class_weights   = class_weights,
        model           = model,
        args            = args,
        train_dataset   = train_ds,
        eval_dataset    = val_ds,
        processing_class = tokenizer,   # saves vocab/tokenizer files with the model
        compute_metrics = compute_metrics,
    )

    print("\nStarting training with class weights (CPU — ~20-30 mins)...\n")
    trainer.train()

    print(f"\nSaving model to {OUTPUT_DIR}/")
    trainer.save_model(OUTPUT_DIR)
    tokenizer.save_pretrained(OUTPUT_DIR)

    # Persist the split so eval/evaluate.py reports on held-out data only
    with open(os.path.join(OUTPUT_DIR, "split.json"), "w", encoding="utf-8") as f:
        json.dump({k: [e["id"] for e in v] for k, v in split.items()}, f, indent=2)

    print("\nFinal validation results:")
    results = trainer.evaluate()
    for k, v in results.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")
    with open(os.path.join(OUTPUT_DIR, "val_metrics.json"), "w", encoding="utf-8") as f:
        json.dump({"seed": seed, **results}, f, indent=2)

    # Calibrate the decision threshold on the validation split
    pred   = trainer.predict(val_ds)
    probs  = torch.softmax(torch.tensor(pred.predictions), dim=1)[:, 1].numpy()
    labels = np.array([e["label"] for e in split["val"]])
    thresholds = calibrate_thresholds(probs, labels)
    with open(os.path.join(OUTPUT_DIR, "threshold.json"), "w", encoding="utf-8") as f:
        json.dump(thresholds, f, indent=2)
    print("\nCalibrated thresholds (validation split):")
    for k, v in thresholds.items():
        print(f"  {k}: {v:.4f}" if isinstance(v, float) else f"  {k}: {v}")

    print(f"\n✅ Model saved to {OUTPUT_DIR}")


if __name__ == "__main__":
    def arg(name, default=None):
        return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default
    main(arg("--variant", "full"), seed=int(arg("--seed", 42)), output_dir=arg("--output-dir"))
