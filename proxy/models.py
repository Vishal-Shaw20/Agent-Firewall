from pydantic import BaseModel
from typing import Optional

class ToolResponseRequest(BaseModel):
    tool_name: str
    content: str
    task_context: str
    session_id: Optional[str] = None    # enables L4 action-mode taint tracking
    subset_label: Optional[str] = None  # for evaluation runs

class FirewallVerdict(BaseModel):
    verdict: str                          # PASS / STRIP / BLOCK
    content: str                          # returned content (stripped, or "" on BLOCK)
    flagged: bool = False
    layer_scores: dict = {}
    reason: Optional[str] = None
    contributors: list[str] = []          # layers at/above STRIP threshold, highest first
    aggregate: float = 0.0
    render_pending: bool = False          # L3 render-diff exceeded its latency budget
    sanitized: bool = False               # a BLOCK downgraded to STRIP: flagged parts removed,
                                          # remainder re-screened clean
    rescreen_scores: dict = {}            # layer scores of the remainder, when re-screened
    latency_ms: dict = {}

class ToolCallRequest(BaseModel):
    session_id: str
    task: str                             # the user's original task
    tool_name: str
    arguments: dict = {}

class ToolCallVerdict(BaseModel):
    verdict: str                          # PASS / REVIEW (ask the user) / BLOCK
    flagged: bool = False
    reason: Optional[str] = None
    taint: dict = {}
