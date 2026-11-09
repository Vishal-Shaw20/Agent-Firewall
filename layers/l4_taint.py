"""
l4_taint.py — Taint / goal-consistency layer (L4) for Agent Firewall.

Two modes:

  Action mode (SRS 3.1 / FR7, used live with an agent):
    Every tool response is tagged untrusted and stored per session. When the
    agent submits its next planned tool call (POST /tool_call), L4 checks
      - provenance: argument values (emails, URLs, amounts, ids, names) that
        appear in untrusted tool output but not in the user's task, sent to a
        side-effecting tool;
      - drift: the call is semantically far from the task but close to a
        tainted sentence.
    Neither check depends on how the injected content was phrased.

  Content mode (used for corpus evaluation, where there is no agent):
    Each sentence of a tool response is compared against decision-steering
    anchors (config/taint_anchors.yaml). This is an approximation of
    goal-consistency, reported as such.
"""

import re
import threading
from collections import defaultdict, deque

from bs4 import BeautifulSoup

from settings import CONFIG_DIR, firewall_config, load_yaml

_cfg     = firewall_config().get("l4", {})
_anchors = load_yaml(CONFIG_DIR / _cfg.get("anchors_file", "taint_anchors.yaml"))

ANCHORS           = _anchors["anchors"]
NEUTRAL_ANCHORS   = _anchors.get("neutral_anchors", [])
STRIP_THRESHOLD   = _anchors["thresholds"]["strip"]    # on the steering-minus-neutral margin
CONTENT_MAX_SCORE = _anchors.get("content_mode_max_score", 0.79)
SIDE_EFFECT_TOOLS = _anchors.get("side_effect_tools", {})    # tool -> target arguments
MODEL_NAME        = _cfg.get("model", "sentence-transformers/all-MiniLM-L6-v2")

SCORE_TAINTED_ARGUMENT = 0.90
SCORE_DRIFT_STRONG     = 0.85
SCORE_DRIFT            = 0.60

SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n+")
VALUE_RE    = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+"            # emails
    r"|https?://\S+"                      # urls
    r"|\b[A-Z]{2,}-?\d{2,}\b"             # ids like PO-4411, INV2201
    r"|\$?\d[\d,]*(?:\.\d+)?"             # amounts / numbers
    r"|\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)+"   # multi-word proper names
)

_model = None
_anchor_emb = None
_neutral_emb = None
_lock = threading.Lock()


def _load():
    global _model, _anchor_emb, _neutral_emb
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL_NAME, device="cpu")
            _anchor_emb = _model.encode(list(ANCHORS.values()), normalize_embeddings=True)
            if NEUTRAL_ANCHORS:
                _neutral_emb = _model.encode(NEUTRAL_ANCHORS, normalize_embeddings=True)
    return _model, _anchor_emb


def _embed(texts: list[str]):
    model, _ = _load()
    return model.encode(texts, normalize_embeddings=True)


def sentences(content: str) -> list[str]:
    if "<" in content and ">" in content:
        content = BeautifulSoup(content, "html.parser").get_text(" ")
    parts = [s.strip() for s in SENTENCE_RE.split(content)]
    return [s for s in parts if len(s.split()) >= 3]


# ── Content mode ──────────────────────────────────────────
def margin_to_score(margin: float) -> float:
    """Margin threshold -> 0.5; capped below BLOCK (content mode can only STRIP)."""
    if margin < STRIP_THRESHOLD:
        return max(0.0, 0.5 * margin / STRIP_THRESHOLD)
    return min(CONTENT_MAX_SCORE, 0.5 + (margin - STRIP_THRESHOLD))


def content_margins(content: str) -> list[dict]:
    """Per sentence: steering similarity, neutral similarity and their margin."""
    sents = sentences(content)
    if not sents:
        return []
    _, anchor_emb = _load()
    sent_emb = _embed(sents)
    steer    = sent_emb @ anchor_emb.T                       # (n_sentences, n_anchors)
    if _neutral_emb is not None:
        neutral = (sent_emb @ _neutral_emb.T).max(axis=1)
    else:
        neutral = [0.0] * len(sents)
    names = list(ANCHORS)
    out = []
    for i, s in enumerate(sents):
        j = int(steer[i].argmax())
        out.append({"sentence": s, "anchor": names[j], "anchor_sim": float(steer[i, j]),
                    "neutral_sim": float(neutral[i]),
                    "margin": float(steer[i, j]) - float(neutral[i]), "emb": sent_emb[i]})
    return out


def run_l4_taint(task_context: str, content: str) -> dict:
    rows = content_margins(content)
    if not rows:
        return {"score": 0.0, "layer": "L4_taint", "mode": "content", "sentences": [], "spans": []}

    task_emb = _embed([task_context])[0]
    scored = []
    for r in rows:
        scored.append({"sentence": r["sentence"], "anchor": r["anchor"],
                       "anchor_sim": round(r["anchor_sim"], 3),
                       "neutral_sim": round(r["neutral_sim"], 3),
                       "margin": round(r["margin"], 3),
                       "task_sim": round(float(r["emb"] @ task_emb), 3),
                       "score": round(margin_to_score(r["margin"]), 3)})

    top = max(scored, key=lambda x: x["margin"])
    return {
        "score": top["score"],
        "layer": "L4_taint",
        "mode": "content",
        "max_margin": top["margin"],
        "max_anchor_sim": max(x["anchor_sim"] for x in scored),
        "sentences": [x for x in scored if x["score"] >= 0.5],
        "spans": [x["sentence"] for x in scored if x["score"] >= 0.5],
    }


# ── Action mode ───────────────────────────────────────────
class TaintStore:
    """Untrusted tool output per session (bounded, in memory)."""

    def __init__(self, max_responses: int = 50):
        self._data = defaultdict(lambda: deque(maxlen=max_responses))
        self._lock = threading.Lock()

    def add(self, session_id: str, tool_name: str, content: str):
        sents = sentences(content)
        emb = _embed(sents) if sents else None
        with self._lock:
            self._data[session_id].append({
                "tool": tool_name, "content": content,
                "sentences": sents, "emb": emb,
            })

    def get(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self._data.get(session_id, []))


TAINT_STORE = TaintStore()


def _values(text: str) -> set[str]:
    return {v.strip().rstrip(".,").lower() for v in VALUE_RE.findall(text) if len(v.strip()) >= 3}


def check_tool_call(session_id: str, task: str, tool_name: str, arguments: dict) -> dict:
    tainted = TAINT_STORE.get(session_id)

    # Read-only / output tools (fetching a page, writing the requested notes)
    # can't act on the attacker's behalf, and a faithful summary naturally
    # resembles its untrusted source, so drift there is expected. Only calls
    # with side effects are checked.
    if tool_name not in SIDE_EFFECT_TOOLS:
        return {"score": 0.0, "layer": "L4_taint", "mode": "action", "task_sim": None,
                "signals": [], "tainted_responses": len(tainted), "checked": False,
                "note": "not a side-effecting tool"}

    # Only the arguments that decide where the action goes (recipient, URL,
    # vendor, amount) are checked. Free-text fields such as an email body
    # legitimately carry a summary of untrusted content; an attacker steering
    # the action still has to put their own value in a target argument.
    targets = {k: v for k, v in arguments.items() if k in SIDE_EFFECT_TOOLS[tool_name]} or arguments
    action_text = f"{tool_name} " + " ".join(f"{k}: {v}" for k, v in targets.items())

    signals = []

    # 1. Provenance: target values that come from untrusted output, not the task
    task_values = _values(task)
    arg_values  = _values(" ".join(str(v) for v in targets.values()))
    for entry in tainted:
        src_values = _values(entry["content"])
        traced = sorted((arg_values & src_values) - task_values)
        if traced and tool_name in SIDE_EFFECT_TOOLS:
            signals.append({"type": "tainted_argument", "values": traced,
                            "source_tool": entry["tool"], "score": SCORE_TAINTED_ARGUMENT})

    # 2. Drift: far from the task, close to something an untrusted tool said
    task_emb, action_emb = _embed([task, action_text])
    task_sim = float(task_emb @ action_emb)
    best_sim, best_sent = 0.0, None
    for entry in tainted:
        if entry["emb"] is None:
            continue
        sims = entry["emb"] @ action_emb
        i = int(sims.argmax())
        if float(sims[i]) > best_sim:
            best_sim, best_sent = float(sims[i]), entry["sentences"][i]
    if best_sent is not None:
        if task_sim < 0.30 and best_sim > 0.45:
            signals.append({"type": "goal_drift", "task_sim": round(task_sim, 3),
                            "taint_sim": round(best_sim, 3), "source_sentence": best_sent,
                            "score": SCORE_DRIFT_STRONG})
        elif best_sim - task_sim > 0.15:
            signals.append({"type": "goal_drift", "task_sim": round(task_sim, 3),
                            "taint_sim": round(best_sim, 3), "source_sentence": best_sent,
                            "score": SCORE_DRIFT})

    return {
        "score": max((s["score"] for s in signals), default=0.0),
        "layer": "L4_taint",
        "mode": "action",
        "task_sim": round(task_sim, 3),
        "signals": signals,
        "checked_arguments": sorted(targets),
        "tainted_responses": len(tainted),
        "checked": True,
    }
