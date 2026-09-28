import re

# ── Explicit injection patterns (intentionally NO implicit patterns) ──
# L1 is kept explicit-only so its blind spot on implicit attacks
# can be cleanly measured in evaluation (Section 8, SRS v3)

EXPLICIT_PATTERNS = [
    # Override / ignore commands
    r"ignore\s+(all\s+)?(previous|prior|above|earlier)\s+instructions?",
    r"disregard\s+(all\s+)?(previous|prior|above)?\s*(instructions?|rules?|prompts?)",
    r"forget\s+(everything|all(\s+previous)?(\s+instructions?)?)",

    # Role switching
    r"you\s+are\s+now\s+(a|an)",
    r"act\s+as\s+(if\s+you\s+are|a|an)",
    r"pretend\s+(you\s+are|to\s+be)",
    r"your\s+(new\s+)?(role|persona|identity)\s+is",

    # Fake system / prompt injection
    r"\[?\s*system\s*\]?\s*:",
    r"new\s+system\s+prompt\s*:",
    r"your\s+real\s+instructions?\s+(are|is)",
    r"override\s*(:|=|-)\s*",

    # Jailbreak classics
    r"do\s+anything\s+now",
    r"DAN\s*(mode|prompt)?",
    r"jailbreak",
    r"you\s+have\s+no\s+(restrictions?|limits?|rules?)",
]

# Pre-compile all patterns for performance
COMPILED_PATTERNS = [
    re.compile(p, re.IGNORECASE | re.DOTALL)
    for p in EXPLICIT_PATTERNS
]


def run_l1_heuristic(content: str) -> dict:
    """
    Scans content for known explicit injection phrasings.
    Returns a score between 0.0 and 1.0, plus matched patterns.

    Score logic:
      0 matches  → 0.0  (PASS)
      1 match    → 0.5  (STRIP threshold)
      2+ matches → 0.9  (BLOCK threshold)
    """
    matched = []

    for pattern in COMPILED_PATTERNS:
        match = pattern.search(content)
        if match:
            matched.append(match.group(0).strip())

    if len(matched) == 0:
        score = 0.0
    elif len(matched) == 1:
        score = 0.5
    else:
        score = 0.9

    return {
        "score": score,
        "layer": "L1_heuristic",
        "matched": matched
    }
