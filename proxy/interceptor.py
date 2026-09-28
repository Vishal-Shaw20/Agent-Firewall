import json, uuid, time
from redis import Redis
from proxy.models import ToolResponseRequest, FirewallVerdict
from proxy.decision_engine import make_decision
from layers.l1_heuristic import run_l1_heuristic

# ── Stub layer functions (replaced phase by phase) ─────────

def run_l2_classifier(content: str) -> dict:
    return {"score": 0.0, "layer": "L2_classifier"}

def run_l3_concealment(content: str) -> dict:
    return {"score": 0.0, "layer": "L3_concealment"}

def run_l4_taint(task_context: str, content: str) -> dict:
    return {"score": 0.0, "layer": "L4_taint"}

def run_l5_schema(tool_name: str, content: str) -> dict:
    return {"score": 0.0, "layer": "L5_schema"}

# ── Main interceptor ───────────────────────────────────────
async def intercept_tool_response(
    request: ToolResponseRequest,
    redis_client: Redis
) -> FirewallVerdict:

    # Run all five layers
    layer_scores = {
        "L1": run_l1_heuristic(request.content),
        "L2": run_l2_classifier(request.content),
        "L3": run_l3_concealment(request.content),
        "L4": run_l4_taint(request.task_context, request.content),
        "L5": run_l5_schema(request.tool_name, request.content),
    }

    # Get verdict from decision engine
    verdict, flagged, reason = make_decision(layer_scores)

    # Log to Redis
    log_entry = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "tool": request.tool_name,
        "subset_label": request.subset_label,
        "verdict": verdict,
        "flagged": flagged,
        "reason": reason,
        "layer_scores": layer_scores,
    }
    redis_client.lpush("firewall:logs", json.dumps(log_entry))

    return FirewallVerdict(
        verdict=verdict,
        content=request.content,
        flagged=flagged,
        layer_scores=layer_scores,
        reason=reason
    )
