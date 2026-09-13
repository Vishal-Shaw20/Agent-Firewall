from pydantic import BaseModel
from typing import Optional

class ToolResponseRequest(BaseModel):
    tool_name: str
    content: str
    task_context: str
    subset_label: Optional[str] = None  # for evaluation runs

class FirewallVerdict(BaseModel):
    verdict: str                          # PASS / STRIP / BLOCK
    content: str                          # returned content (may be stripped)
    flagged: bool = False
    layer_scores: dict = {}               # fills in phase by phase
    reason: Optional[str] = None
