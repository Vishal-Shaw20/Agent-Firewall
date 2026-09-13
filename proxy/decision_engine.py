def make_decision(layer_scores: dict) -> tuple[str, bool, str | None]:
    """
    Takes layer scores dict, returns (verdict, flagged, reason).

    Verdict rules:
      - Any layer score >= 0.8  → BLOCK
      - Any layer score >= 0.5  → STRIP
      - All scores < 0.5        → PASS
    """

    max_score = 0.0
    triggering_layer = None

    for layer_name, result in layer_scores.items():
        score = result.get("score", 0.0)
        if score > max_score:
            max_score = score
            triggering_layer = layer_name

    if max_score >= 0.8:
        return (
            "BLOCK",
            True,
            f"High-confidence injection detected by {triggering_layer} (score: {max_score:.2f})"
        )
    elif max_score >= 0.5:
        return (
            "STRIP",
            True,
            f"Suspicious content flagged by {triggering_layer} (score: {max_score:.2f})"
        )
    else:
        return ("PASS", False, None)
