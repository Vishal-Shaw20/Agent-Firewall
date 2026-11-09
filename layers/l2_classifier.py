"""
l2_classifier.py — DistilBERT inference layer for Agent Firewall.
Loaded once at startup, called per request.
"""

import os
import json
import torch
from settings import MODELS_DIR
from transformers import (
    DistilBertForSequenceClassification,
    DistilBertTokenizerFast,
)

# Variants:
#   full           single explicit+implicit model (the validation-selected seed)
#   explicit_only  ablation model trained without implicit examples (SRS 8.2)
#   seed42/1/2     the three training seeds of the full model
#   ensemble       mean probability of the three seeds (default). Single
#                  fine-tunes on this data swing a lot from seed to seed
#                  (eval/results/l2_seed_variance.md); averaging removes most of that.
# Override with the L2_VARIANT environment variable.
VARIANT_DIRS = {
    "full":          MODELS_DIR / "l2_distilbert",
    "explicit_only": MODELS_DIR / "l2_distilbert_explicit_only",
    "seed42":        MODELS_DIR / "l2_seed42",
    "seed1":         MODELS_DIR / "l2_seed1",
    "seed2":         MODELS_DIR / "l2_seed2",
}
ENSEMBLES = {"ensemble": ["seed42", "seed1", "seed2"]}
ENSEMBLE_DIRS = {"ensemble": MODELS_DIR / "l2_ensemble"}   # holds threshold.json
DEFAULT_VARIANT = os.getenv("L2_VARIANT", "ensemble")
MAX_LENGTH = 256
WINDOW_STRIDE = 64      # token overlap between windows for long inputs

# ── Load each model once, on first use ────────────────────
_loaded = {}


def _read_thresholds(directory) -> dict | None:
    path = os.path.join(directory, "threshold.json")
    return json.load(open(path, encoding="utf-8")) if os.path.exists(path) else None


def _load(variant: str):
    """(tokenizer, model, thresholds) for a single-model variant."""
    if variant not in _loaded:
        model_dir = VARIANT_DIRS[variant]
        if not os.path.exists(model_dir):
            flag = "" if variant == "full" else f" --variant {variant}"
            raise FileNotFoundError(
                f"L2 model not found at '{model_dir}'. "
                f"Run: python -m training.train_l2{flag}"
            )
        tokenizer = DistilBertTokenizerFast.from_pretrained(model_dir)
        model     = DistilBertForSequenceClassification.from_pretrained(model_dir)
        model.eval()
        # Thresholds calibrated on the validation split by training.train_l2
        _loaded[variant] = (tokenizer, model, _read_thresholds(model_dir))
    return _loaded[variant]


def thresholds_for(variant: str) -> dict | None:
    if variant in ENSEMBLES:
        return _read_thresholds(ENSEMBLE_DIRS[variant])
    return _load(variant)[2]


def raw_prob(text: str, variant: str = DEFAULT_VARIANT) -> float:
    """Uncalibrated probability of injection (ensembles: mean over members)."""
    if variant in ENSEMBLES:
        members = ENSEMBLES[variant]
        return sum(raw_prob(text, m) for m in members) / len(members)
    tokenizer, model, _ = _load(variant)
    # Long inputs are scored in overlapping windows and the most suspicious
    # window wins; truncating at MAX_LENGTH would let a payload placed after
    # the first ~256 tokens of filler go unread.
    inputs = tokenizer(text, return_tensors="pt", truncation=True, padding="max_length",
                       max_length=MAX_LENGTH, stride=WINDOW_STRIDE,
                       return_overflowing_tokens=True)
    inputs.pop("overflow_to_sample_mapping", None)
    with torch.no_grad():
        probs = torch.softmax(model(**inputs).logits, dim=1)[:, 1]
    return probs.max().item()


def calibrate(prob: float, thresholds: dict | None) -> float:
    """
    Maps the raw probability onto the decision engine's scale, piecewise
    linearly: calibrated strip threshold -> 0.5, block threshold -> 0.8.
    Without a threshold file the raw probability is returned.
    """
    if not thresholds:
        return prob
    t_strip, t_block = thresholds["strip"], max(thresholds["block"], thresholds["strip"] + 1e-6)
    if prob < t_strip:
        return 0.5 * prob / t_strip
    if prob < t_block:
        return 0.5 + 0.3 * (prob - t_strip) / (t_block - t_strip)
    return 0.8 + 0.2 * (prob - t_block) / max(1 - t_block, 1e-6)


# ── Structured responses: classify the text, not the format ─
MIN_TEXT_WORDS = 3   # shorter string values (ids, names, status codes) aren't prose


def json_text_values(obj, path: str = "") -> list[tuple[str, str]]:
    """(path, value) for every string value in a JSON document that reads as prose."""
    out = []
    if isinstance(obj, str):
        if len(obj.split()) >= MIN_TEXT_WORDS:
            out.append((path, obj))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            out += json_text_values(v, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out += json_text_values(v, f"{path}[{i}]")
    return out


def l2_text(content: str) -> str | None:
    """
    What L2 actually classifies. L2 is a natural-language classifier, so for a
    JSON response it reads only the prose string values. Scored on the raw
    JSON, it learned "unusual JSON = injection": it flagged structural
    carriers by format alone and 15% of benign JSON with them. Encoded
    carriers (base64, number arrays) are L5's job.
    Returns None when a JSON response contains no prose at all.
    Used identically at training time (training/dataset.py).
    """
    if not content.lstrip().startswith(("{", "[")):
        return content
    try:
        obj = json.loads(content)
    except json.JSONDecodeError:
        return content
    values = [v.strip() for _, v in json_text_values(obj)]
    if not values:
        return None
    return " ".join(v if v[-1:] in ".!?" else v + "." for v in values)


def run_l2_classifier(content: str, variant: str = DEFAULT_VARIANT) -> dict:
    """
    Runs DistilBERT inference on content (JSON responses: on their prose
    string values only; see l2_text).
    Returns the calibrated score (0.5 = calibrated STRIP threshold) and the
    raw probability of being an injection.
    """
    text = l2_text(content)
    if text is None:
        return {"score": 0.0, "prob": 0.0, "calibrated": True, "layer": "L2_classifier",
                "variant": variant, "skipped": "structured response with no natural-language text"}

    prob = raw_prob(text, variant)
    thresholds = thresholds_for(variant)

    return {
        "score": round(calibrate(prob, thresholds), 4),
        "prob": round(prob, 4),
        "calibrated": thresholds is not None,
        "layer": "L2_classifier",
        "variant": variant,
    }
