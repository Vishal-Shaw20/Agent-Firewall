from settings import firewall_config

_cfg            = firewall_config().get("decision", {})
BLOCK_THRESHOLD = _cfg.get("block_threshold", 0.8)
STRIP_THRESHOLD = _cfg.get("strip_threshold", 0.5)
WEIGHTS         = _cfg.get("weights", {})


def make_decision(layer_scores: dict) -> dict:
    """
    Takes layer scores dict, returns the verdict and the audit fields (NFR3).

    Verdict rules (FR10):
      - Any layer score >= block_threshold  → BLOCK
      - Any layer score >= strip_threshold  → STRIP
      - All scores below                    → PASS

    Also recorded, for audit and analysis:
      contributors — layers at or above the STRIP threshold, highest first
      aggregate    — weighted mean of layer scores (config/firewall.yaml)
    """
    scores = {name: r.get("score", 0.0) for name, r in layer_scores.items()}
    if not scores:
        return {"verdict": "PASS", "flagged": False, "reason": None,
                "contributors": [], "aggregate": 0.0}

    top_layer = max(scores, key=scores.get)
    max_score = scores[top_layer]

    weight_sum = sum(WEIGHTS.get(n, 1.0) for n in scores)
    aggregate  = sum(WEIGHTS.get(n, 1.0) * s for n, s in scores.items()) / weight_sum

    contributors = sorted((n for n, s in scores.items() if s >= STRIP_THRESHOLD),
                          key=lambda n: -scores[n])

    if max_score >= BLOCK_THRESHOLD:
        verdict = "BLOCK"
        reason  = f"High-confidence injection detected by {top_layer} (score: {max_score:.2f})"
    elif max_score >= STRIP_THRESHOLD:
        verdict = "STRIP"
        reason  = f"Suspicious content flagged by {top_layer} (score: {max_score:.2f})"
    else:
        verdict, reason = "PASS", None

    return {
        "verdict": verdict,
        "flagged": verdict != "PASS",
        "reason": reason,
        "contributors": contributors,
        "aggregate": round(aggregate, 4),
    }
