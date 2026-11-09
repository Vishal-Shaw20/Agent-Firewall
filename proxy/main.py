from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from starlette.concurrency import run_in_threadpool
import os

from proxy.audit_log import AuditLog
from proxy.interceptor import intercept_tool_response, intercept_tool_call, ENABLED_LAYERS
from proxy.models import ToolResponseRequest, FirewallVerdict, ToolCallRequest, ToolCallVerdict
from layers.l2_classifier import run_l2_classifier
from layers.l3_concealment import warm_up as warm_up_render
from layers.l4_taint import run_l4_taint

load_dotenv()

# ── Audit log: Redis if reachable, else logs/audit.jsonl ──
audit_log = AuditLog(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load models and start the render browser before the first request
    def warm():
        run_l2_classifier("warm up")
        run_l4_taint("warm up", "This is a warm up sentence.")
        warm_up_render()
    await run_in_threadpool(warm)
    yield


# ── App ────────────────────────────────────────────────────
app = FastAPI(
    title="Agent Firewall",
    description="Multi-layer proxy for detecting indirect prompt injection in LLM agent tool calls",
    version="0.2.0",
    lifespan=lifespan,
)

@app.get("/health")
def health():
    return {"status": "ok", "proxy": "agent-firewall", "version": "0.2.0",
            "layers": ENABLED_LAYERS, "audit_log": audit_log.backend}

@app.post("/tool_response", response_model=FirewallVerdict)
async def handle_tool_response(request: ToolResponseRequest):
    return await intercept_tool_response(request, audit_log)

@app.post("/tool_call", response_model=ToolCallVerdict)
async def handle_tool_call(request: ToolCallRequest):
    return await intercept_tool_call(request, audit_log)

@app.get("/logs")
def get_logs(limit: int = 20):
    logs = audit_log.recent(limit)
    return {"logs": logs, "count": len(logs), "backend": audit_log.backend}
