"""
l5_schema.py — Schema-deviation layer (L5) for Agent Firewall.

Content-agnostic structural check (SRS 3.4, FR8/FR9):
  1. Load the declared schema for the tool (schemas/<tool>.yaml).
  2. Profile the response: undeclared fields, type mismatches, nesting depth,
     opaque high-entropy strings, numeric arrays, mixed-script tokens.
  3. Reconstruction probe: anything that looks like a carrier (base64 / hex
     strings, integer arrays in the printable-ASCII range, homoglyph tokens)
     is decoded and the decoded text is run through L1. A carrier that
     decodes to an instruction is the strongest signal this layer emits.
"""

import base64
import binascii
import json
import math
import re
import unicodedata
from collections import Counter
from functools import lru_cache

from layers.l1_heuristic import run_l1_heuristic
from settings import SCHEMAS_DIR, load_yaml

# ── Scores per signal type ────────────────────────────────
SCORE_DECODED_INSTRUCTION = 0.95   # carrier decodes to text that L1 flags
SCORE_DECODED_TEXT        = 0.70   # carrier decodes to natural-language text
SCORE_MIXED_SCRIPT        = 0.60   # homoglyph tokens present
SCORE_SCHEMA_VIOLATION    = 0.50   # undeclared field / wrong type / bad JSON
SCORE_OPAQUE_BLOB         = 0.40   # high-entropy string that does not decode
SCORE_DEPTH               = 0.30

DEFAULT_TOOL = "web_fetch"

BLOB_RE      = re.compile(r"[A-Za-z0-9+/=_-]{16,}")
HEX_RE       = re.compile(r"^(?:[0-9a-fA-F]{2}){8,}$")
TEXT_ARRAY_RE = re.compile(r"\[\s*(-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?){4,})\s*\]")

# Cyrillic / Greek letters that render like Latin ones
CONFUSABLES = str.maketrans({
    "А": "A", "а": "a", "В": "B", "Е": "E", "е": "e", "К": "K", "М": "M",
    "Н": "H", "О": "O", "о": "o", "Р": "P", "р": "p", "С": "C", "с": "c",
    "Т": "T", "у": "y", "Х": "X", "х": "x", "І": "I", "і": "i", "Ј": "J",
    "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "Α": "A", "Β": "B", "Ε": "E",
    "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O",
    "ο": "o", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X", "ν": "v",
})

TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool":   lambda v: isinstance(v, bool),
    "list":   lambda v: isinstance(v, list),
    "object": lambda v: isinstance(v, dict),
    "any":    lambda v: True,
}


# ── Schema registry ───────────────────────────────────────
@lru_cache(maxsize=None)
def load_schema(tool_name: str) -> dict:
    path = SCHEMAS_DIR / f"{tool_name}.yaml"
    if not path.exists():
        # Unregistered tools fall back to the generic profile for their format
        return {}
    return load_yaml(path)


def _schema_for(tool_name: str, content: str) -> dict:
    schema = load_schema(tool_name)
    if schema:
        return schema
    looks_json = content.lstrip().startswith(("{", "["))
    return load_schema("json_api" if looks_json else DEFAULT_TOOL)


# ── Helpers ───────────────────────────────────────────────
def _entropy(s: str) -> float:
    counts = Counter(s)
    n = len(s)
    return -sum(c / n * math.log2(c / n) for c in counts.values())


def _is_text(s: str) -> bool:
    """Decoded bytes look like natural-language text."""
    if len(s) < 4:
        return False
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in s) / len(s)
    alpha     = sum(ch.isalpha() or ch.isspace() for ch in s) / len(s)
    words     = [w for w in re.findall(r"[A-Za-z]{2,}", s)]
    return printable >= 0.95 and alpha >= 0.8 and len(words) >= 2


def _decode_once(s: str) -> str | None:
    s = s.strip()
    if HEX_RE.match(s):
        try:
            return bytes.fromhex(s).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return None
    padded = s + "=" * (-len(s) % 4)
    if "-" in padded or "_" in padded:
        padded = padded.replace("-", "+").replace("_", "/")   # url-safe alphabet
    try:
        return base64.b64decode(padded, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None


def reconstruct(s: str, max_depth: int = 3) -> str | None:
    """Iteratively decode base64/hex layers until natural text appears."""
    current = s
    for _ in range(max_depth):
        decoded = _decode_once(current)
        if decoded is None:
            return None
        if _is_text(decoded):
            return decoded
        current = decoded
    return None


def decode_numeric_array(values: list) -> str | None:
    """Integer arrays in the printable ASCII range, read as character codes."""
    if len(values) < 5:
        return None
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
        return None
    if not all(float(v).is_integer() and 32 <= v <= 126 for v in values):
        return None
    text = "".join(chr(int(v)) for v in values)
    return text if _is_text(text) else None


def _scripts(token: str) -> set[str]:
    scripts = set()
    for ch in token:
        if ch.isalpha():
            try:
                scripts.add(unicodedata.name(ch).split()[0])
            except ValueError:
                pass
    return scripts


def mixed_script_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"\w+", text) if len(_scripts(t)) > 1]


# ── Per-string checks (shared by text and JSON paths) ─────
def _check_string(value: str, path: str, schema: dict, signals: list, opaque_ok: bool):
    # Homoglyph carrier
    mixed = mixed_script_tokens(value)
    if len(mixed) > schema.get("max_mixed_script_tokens", 0):
        folded = value.translate(CONFUSABLES)
        l1 = run_l1_heuristic(folded)
        signals.append({
            "type": "mixed_script",
            "path": path,
            "tokens": mixed[:10],
            "decoded": folded,
            "decoded_l1": l1["matched"],
            "score": SCORE_DECODED_INSTRUCTION if l1["score"] > 0 else SCORE_MIXED_SCRIPT,
            "spans": mixed,
        })

    # Encoded blobs (whole value, or long tokens inside free text)
    min_len   = schema.get("min_blob_length", 16)
    max_ent   = schema.get("max_token_entropy", 4.5)
    candidates = [value.strip()] if BLOB_RE.fullmatch(value.strip() or "-") else BLOB_RE.findall(value)
    for blob in candidates:
        if len(blob) < min_len:
            continue
        decoded = reconstruct(blob)
        if decoded is not None:
            l1 = run_l1_heuristic(decoded)
            signals.append({
                "type": "encoded_payload",
                "path": path,
                "decoded": decoded,
                "decoded_l1": l1["matched"],
                "score": SCORE_DECODED_INSTRUCTION if l1["score"] > 0 else SCORE_DECODED_TEXT,
                "spans": [blob],
            })
        elif not opaque_ok and _entropy(blob) > max_ent:
            signals.append({
                "type": "opaque_blob",
                "path": path,
                "entropy": round(_entropy(blob), 2),
                "score": SCORE_OPAQUE_BLOB,
                "spans": [blob],
            })


def _check_array(values: list, path: str, signals: list, span: str | None = None):
    decoded = decode_numeric_array(values)
    if decoded is not None:
        l1 = run_l1_heuristic(decoded)
        signals.append({
            "type": "numeric_carrier",
            "path": path,
            "decoded": decoded,
            "decoded_l1": l1["matched"],
            "score": SCORE_DECODED_INSTRUCTION if l1["score"] > 0 else SCORE_DECODED_TEXT,
            "spans": [span] if span else [],
        })


def _walk_json(node, path: str, depth: int, schema: dict, signals: list):
    max_depth = schema.get("max_depth", 4)
    if depth > max_depth:
        signals.append({"type": "depth_exceeded", "path": path,
                        "score": SCORE_DEPTH, "spans": []})
        return

    opaque_fields = set(schema.get("opaque_fields", []))

    if isinstance(node, dict):
        fields = schema.get("fields") or {}
        for key, value in node.items():
            child = f"{path}.{key}" if path else key
            # Declared fields / types only apply at the top level
            if depth == 0 and fields:
                if key not in fields and not schema.get("allow_undeclared_fields", True):
                    signals.append({"type": "undeclared_field", "path": child,
                                    "score": SCORE_SCHEMA_VIOLATION, "spans": []})
                expected = fields.get(key)
                if expected and not TYPE_CHECKS.get(expected, TYPE_CHECKS["any"])(value):
                    signals.append({"type": "type_mismatch", "path": child,
                                    "expected": expected, "score": SCORE_SCHEMA_VIOLATION,
                                    "spans": []})
            if isinstance(value, str):
                _check_string(value, child, schema, signals, opaque_ok=key in opaque_fields)
            else:
                _walk_json(value, child, depth + 1, schema, signals)

    elif isinstance(node, list):
        if node and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in node):
            _check_array(node, path, signals)
        else:
            for i, value in enumerate(node):
                child = f"{path}[{i}]"
                if isinstance(value, str):
                    _check_string(value, child, schema, signals, opaque_ok=False)
                else:
                    _walk_json(value, child, depth + 1, schema, signals)


# ── Entry point ───────────────────────────────────────────
def run_l5_schema(tool_name: str, content: str) -> dict:
    """
    Returns score 0.0–1.0 for how far the response deviates from the tool's
    declared schema, plus the signals and any reconstructed payloads.
    For JSON responses, flagged field paths are returned so STRIP can drop them.
    """
    schema  = _schema_for(tool_name, content)
    signals = []
    is_json = False

    if schema.get("format") == "json" or content.lstrip().startswith(("{", "[")):
        try:
            parsed  = json.loads(content)
            is_json = True
            _walk_json(parsed, "", 0, schema, signals)
        except json.JSONDecodeError:
            if schema.get("format") == "json":
                signals.append({"type": "invalid_json", "path": "",
                                "score": SCORE_SCHEMA_VIOLATION, "spans": []})

    if not is_json:
        _check_string(content, "", schema, signals, opaque_ok=False)
        for m in TEXT_ARRAY_RE.finditer(content):
            values = [float(x) for x in m.group(1).split(",")]
            _check_array(values, "", signals, span=m.group(0))

    score = max((s["score"] for s in signals), default=0.0)
    return {
        "score": score,
        "layer": "L5_schema",
        "schema": schema.get("tool", "none"),
        "signals": signals,
        "spans": [sp for s in signals if s["score"] >= 0.5 for sp in s.get("spans", [])],
        "paths": [s["path"] for s in signals if s["score"] >= 0.5 and is_json and s["path"]],
    }
