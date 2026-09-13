from fastapi import FastAPI
from contextlib import asynccontextmanager
from dotenv import load_dotenv
import os, redis

from proxy.interceptor import intercept_tool_response
from proxy.models import ToolResponseRequest, FirewallVerdict

load_dotenv()

# ── Redis connection ───────────────────────────────────────
redis_client = redis.Redis(
    host=os.getenv("REDIS_HOST", "localhost"),
    port=int(os.getenv("REDIS_PORT", 6379)),
    decode_responses=True
)

# ── App ────────────────────────────────────────────────────
app = FastAPI(
    title="Agent Firewall",
    description="Multi-layer proxy for detecting indirect prompt injection in LLM agent tool calls",
    version="0.1.0"
)

@app.get("/health")
def health():
    return {"status": "ok", "proxy": "agent-firewall", "version": "0.1.0"}

@app.post("/tool_response", response_model=FirewallVerdict)
async def handle_tool_response(request: ToolResponseRequest):
    verdict = await intercept_tool_response(request, redis_client)
    return verdict

@app.get("/logs")
def get_logs(limit: int = 20):
    logs = redis_client.lrange("firewall:logs", 0, limit - 1)
    return {"logs": logs, "count": len(logs)}
