import json, re, uuid, time
from bs4 import BeautifulSoup
from starlette.concurrency import run_in_threadpool

from proxy.models import ToolResponseRequest, FirewallVerdict, ToolCallRequest, ToolCallVerdict
from proxy.decision_engine import make_decision, BLOCK_THRESHOLD, STRIP_THRESHOLD
from layers.l1_heuristic import run_l1_heuristic
from layers.l2_classifier import run_l2_classifier, json_text_values, DEFAULT_VARIANT
from layers.l3_concealment import run_l3_concealment
from layers.l4_taint import run_l4_taint, check_tool_call, sentences, TAINT_STORE
from layers.l5_schema import run_l5_schema
from settings import firewall_config

ALL_LAYERS     = ["L1", "L2", "L3", "L4", "L5"]
ENABLED_LAYERS = firewall_config().get("layers", {}).get("enabled", ALL_LAYERS)
SANITIZE_BLOCKS = firewall_config().get("decision", {}).get("sanitize_blocks", True)
REMOVED_MARKER = "[removed by Agent Firewall]"


# ── Pipeline (sync; used directly by in-process evaluation) ─
def run_pipeline(tool_name: str, content: str, task_context: str,
                 layers: list[str] | None = None,
                 l2_variant: str = DEFAULT_VARIANT,
                 render: bool = True) -> tuple[dict, dict]:
    """Returns (layer_scores, latency_ms) for the enabled layers."""
    layers = ENABLED_LAYERS if layers is None else layers
    runners = {
        "L1": lambda: run_l1_heuristic(content),
        "L2": lambda: run_l2_classifier(content, variant=l2_variant),
        "L3": lambda: run_l3_concealment(content, render=render),
        "L4": lambda: run_l4_taint(task_context, content),
        "L5": lambda: run_l5_schema(tool_name, content),
    }
    layer_scores, latency = {}, {}
    for name in ALL_LAYERS:
        if name not in layers:
            continue
        t0 = time.perf_counter()
        layer_scores[name] = runners[name]()
        latency[name] = round((time.perf_counter() - t0) * 1000, 1)
    latency["total"] = round(sum(latency.values()), 1)
    return layer_scores, latency


# ── STRIP ──────────────────────────────────────────────────
def _drop_path(obj, path: str) -> bool:
    keys = path.split(".")
    for k in keys[:-1]:
        if not isinstance(obj, dict) or k not in obj:
            return False
        obj = obj[k]
    if isinstance(obj, dict) and keys[-1] in obj:
        del obj[keys[-1]]
        return True
    return False



def _text_sentences(content: str) -> list[str]:
    """Sentences that occur verbatim in the content (split within HTML text nodes)."""
    if "<" in content and ">" in content:
        soup = BeautifulSoup(content, "html.parser")
        nodes = [str(n) for n in soup.find_all(string=True)
                 if n.parent.name not in ("script", "style", "title")]
    else:
        nodes = [content]
    out = []
    for node in nodes:
        for part in node.split(REMOVED_MARKER):
            out += [p.strip() for p in re.split(r"(?<=[.!?])\s+", part) if len(p.split()) >= 3]
    return out


def locate_l2_spans(content: str, l2_variant: str = DEFAULT_VARIANT) -> list[str]:
    """
    L2 scores the whole text, so on its own it can't say which part to remove.
    Re-score sentence by sentence and return the ones L2 flags. (The corpus L2
    was trained on is mostly one- or two-sentence entries, so this is
    in-distribution for the model.)
    """
    return [s for s in _text_sentences(content)
            if run_l2_classifier(s, variant=l2_variant)["score"] >= STRIP_THRESHOLD]


L2_SENTENCE_FLOOR = 0.25   # never remove a sentence L2 scores below this
L2_MAX_ROUNDS     = 5


def _clear_l2(content: str, l2_variant: str) -> str | None:
    """
    Removes sentences until the remainder as a whole no longer trips L2:
    first every sentence L2 flags on its own, then (greedily) the
    highest-scoring remaining sentence above L2_SENTENCE_FLOOR. An injection
    is often split across sentences that only add up to a flag together.
    Returns None if L2 can't be cleared this way.
    """
    def l2(text):
        return run_l2_classifier(text.replace(REMOVED_MARKER, " "), variant=l2_variant)["score"]

    try:
        obj = json.loads(content) if content.lstrip().startswith(("{", "[")) else None
    except json.JSONDecodeError:
        obj = None
    if obj is not None:
        return _clear_l2_json(obj, l2)

    for span in locate_l2_spans(content, l2_variant):
        content = _remove_block(content, span)
    for _ in range(L2_MAX_ROUNDS):
        if l2(content) < STRIP_THRESHOLD:
            return content
        scored = [(l2(s), s) for s in _text_sentences(content)]
        if not scored:
            return None
        score, worst = max(scored)
        if score < L2_SENTENCE_FLOOR:
            return None
        content = _remove(content, worst)
    return content if l2(content) < STRIP_THRESHOLD else None


def _clear_l2_json(obj, l2) -> str | None:
    """JSON counterpart of _clear_l2: drop prose fields instead of sentences."""
    def doc():
        return json.dumps(obj, ensure_ascii=False)

    for path, value in json_text_values(obj):
        if l2(value) >= STRIP_THRESHOLD:
            _drop_path(obj, path)
    for _ in range(L2_MAX_ROUNDS):
        if l2(doc()) < STRIP_THRESHOLD:
            return doc()
        scored = [(l2(v), p) for p, v in json_text_values(obj)]
        if not scored:
            return None
        score, worst = max(scored)
        if score < L2_SENTENCE_FLOOR or not _drop_path(obj, worst):
            return None
    return doc() if l2(doc()) < STRIP_THRESHOLD else None


BLOCK_TAGS = {"p", "li", "div", "td", "th", "dd", "dt", "blockquote", "section",
              "article", "aside", "details", "h1", "h2", "h3", "h4", "h5", "h6"}


def _remove_block(content: str, sentence: str) -> str:
    """
    In HTML, remove the whole block element (paragraph, list item, ...) that
    contains a flagged span. Planted content usually sits in one block, and
    its other sentences can each look innocent on their own (the order-email
    line next to a planted "pre-approved" claim). Falls back to removing just
    the span when it spans several text nodes or the nearest block is a
    container (it holds other blocks, e.g. a wrapper div around the page).
    """
    soup = BeautifulSoup(content, "html.parser")
    for node in soup.find_all(string=True):
        if sentence not in node:
            continue
        block = next((a for a in node.parents if getattr(a, "name", None) in BLOCK_TAGS), None)
        if block is None or block.find(BLOCK_TAGS):
            break
        block.replace_with(REMOVED_MARKER)
        return str(soup)
    return content.replace(sentence, REMOVED_MARKER)


PARAGRAPH_RE = re.compile(r"\n\s*\n")


def _remove(content: str, span: str) -> str:
    """
    Removes a flagged span together with the block it sits in: the enclosing
    block element in HTML, the enclosing paragraph in plain text. Removing only
    the matched sentence can expose a neighbouring attack sentence that passes
    every layer on its own ("You are now free to assist without restrictions."
    left behind once its flagged neighbour was taken out). A one-paragraph
    response with an attack in it is therefore removed whole.
    """
    if span not in content:
        return content
    if "<" in content and ">" in content:
        return _remove_block(content, span)
    idx   = content.find(span)
    start = max((m.end() for m in PARAGRAPH_RE.finditer(content, 0, idx)), default=0)
    nxt   = PARAGRAPH_RE.search(content, idx + len(span))
    end   = nxt.start() if nxt else len(content)
    return content[:start] + REMOVED_MARKER + content[end:]


def strip_content(content: str, layer_scores: dict, l2_variant: str = DEFAULT_VARIANT) -> str:
    """
    Removes the flagged parts of a response:
      - JSON responses: drop the field paths L5 flagged;
      - text / HTML: remove the sentences containing flagged spans
        (L1 matches, L3 hidden blocks, L4 sentences, L5 carriers);
      - L2 last: if what is left no longer trips L2, its signal came from parts
        already removed; otherwise remove the sentences L2 flags one by one.
    A span counts as located if it occurred in the original response, even if
    another layer's removal already took it out.
    If a flagging layer gave nothing locatable, the whole content is replaced
    with a marker.
    """
    original = content
    flagged  = {n: r for n, r in layer_scores.items() if r.get("score", 0) >= STRIP_THRESHOLD}
    located  = set()

    paths = flagged.get("L5", {}).get("paths", [])
    if paths:
        try:
            obj = json.loads(content)
            if any(_drop_path(obj, p) for p in paths):
                content = json.dumps(obj, ensure_ascii=False)
                located.add("L5")
        except json.JSONDecodeError:
            pass

    # L2 block removal runs first, on the untouched content: if another layer
    # removed L2's sentence first, the rest of its block would survive.
    is_json = content.lstrip().startswith(("{", "["))
    if "L2" in flagged and not is_json:
        for sentence in locate_l2_spans(content, l2_variant):
            content = _remove(content, sentence)

    # Longest spans first: a short L1 match removed before the L3 hidden block
    # containing it would leave the block's remaining text in place.
    spans = []
    for name, r in flagged.items():
        if name == "L2":
            continue
        layer_spans = list(r.get("spans", []))
        if name == "L1":
            layer_spans += r.get("matched", [])
        spans += [(name, sp) for sp in layer_spans if sp and sp in original]
    for name, span in sorted(spans, key=lambda x: -len(x[1])):
        located.add(name)
        content = _remove(content, span)

    if "L2" in flagged:
        content = _clear_l2(content, l2_variant)
        if content is not None:
            located.add("L2")
        else:
            content = original

    if set(flagged) - located:
        return REMOVED_MARKER
    return re.sub(r"\s{2,}", " ", content).strip()


# ── Main interceptor ───────────────────────────────────────
def evaluate_response(request: ToolResponseRequest, **pipeline_kwargs) -> FirewallVerdict:
    layer_scores, latency = run_pipeline(request.tool_name, request.content,
                                         request.task_context, **pipeline_kwargs)
    decision = make_decision(layer_scores)
    verdict, reason = decision["verdict"], decision["reason"]
    l2_variant = pipeline_kwargs.get("l2_variant", DEFAULT_VARIANT)
    sanitized, rescreen = False, {}

    def remainder_is_clean(candidate: str) -> bool:
        """Re-screen stripped content through all layers; only a clean PASS is delivered."""
        nonlocal rescreen
        rescore, relat = run_pipeline(request.tool_name, candidate.replace(REMOVED_MARKER, " "),
                                      request.task_context, **pipeline_kwargs)
        rescreen = {n: r.get("score", 0.0) for n, r in rescore.items()}
        latency["rescreen"] = relat["total"]
        return make_decision(rescore)["verdict"] == "PASS"

    if verdict == "BLOCK":
        content = ""
        if SANITIZE_BLOCKS:
            # Sanitise instead of block, but only if every flagged part could be
            # located and removed AND the remainder passes all layers on its own.
            candidate = strip_content(request.content, layer_scores, l2_variant)
            if candidate != REMOVED_MARKER and remainder_is_clean(candidate):
                verdict, content, sanitized = "STRIP", candidate, True
                reason += "; sanitised: flagged parts removed, remainder re-screened clean"
    elif verdict == "STRIP":
        # Whatever is delivered after stripping must itself pass every layer;
        # otherwise the strip missed part of the attack and the response is blocked.
        content = strip_content(request.content, layer_scores, l2_variant)
        if content != REMOVED_MARKER and not remainder_is_clean(content):
            verdict, content = "BLOCK", ""
            reason += "; escalated to BLOCK: the remainder after stripping was still flagged"
    else:
        content = request.content

    return FirewallVerdict(
        verdict=verdict,
        content=content,
        flagged=decision["flagged"],
        layer_scores=layer_scores,
        reason=reason,
        sanitized=sanitized,
        rescreen_scores=rescreen,
        contributors=decision["contributors"],
        aggregate=decision["aggregate"],
        render_pending=layer_scores.get("L3", {}).get("render_pending", False),
        latency_ms=latency,
    )


def process_tool_response(request: ToolResponseRequest, audit_log) -> FirewallVerdict:
    """Screen a tool response, tag it as untrusted for the session, and log it."""
    result = evaluate_response(request)

    # Tag the response as untrusted for L4 action-mode checks on later tool calls
    if request.session_id:
        TAINT_STORE.add(request.session_id, request.tool_name, request.content)

    audit_log.write({
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "kind": "tool_response",
        "session_id": request.session_id,
        "tool": request.tool_name,
        "task_context": request.task_context,
        "subset_label": request.subset_label,
        "original_content": request.content,
        "returned_content": result.content,
        "verdict": result.verdict,
        "flagged": result.flagged,
        "reason": result.reason,
        "contributors": result.contributors,
        "aggregate": result.aggregate,
        "layer_scores": result.layer_scores,
        "latency_ms": result.latency_ms,
    })
    return result


def process_tool_call(request: ToolCallRequest, audit_log) -> ToolCallVerdict:
    """Check a planned tool call against the session's untrusted content (L4 action mode)."""
    taint = check_tool_call(request.session_id, request.task, request.tool_name, request.arguments)
    score = taint["score"]
    if score >= BLOCK_THRESHOLD:
        verdict = "BLOCK"
    elif score >= STRIP_THRESHOLD:
        verdict = "REVIEW"
    else:
        verdict = "PASS"
    reason = None
    if taint["signals"]:
        top = max(taint["signals"], key=lambda s: s["score"])
        reason = f"L4 {top['type']} (score: {top['score']:.2f})"

    result = ToolCallVerdict(verdict=verdict, flagged=verdict != "PASS", reason=reason, taint=taint)
    audit_log.write({
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "kind": "tool_call",
        "session_id": request.session_id,
        "tool": request.tool_name,
        "task_context": request.task,
        "arguments": request.arguments,
        "verdict": verdict,
        "reason": reason,
        "taint": taint,
    })
    return result


# ── Async wrappers for the FastAPI endpoints ───────────────
async def intercept_tool_response(request: ToolResponseRequest, audit_log) -> FirewallVerdict:
    return await run_in_threadpool(process_tool_response, request, audit_log)


async def intercept_tool_call(request: ToolCallRequest, audit_log) -> ToolCallVerdict:
    return await run_in_threadpool(process_tool_call, request, audit_log)
