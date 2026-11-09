"""
scripted_llm.py — A deterministic, deliberately gullible chat model.

Stands in for an LLM in tests and in the reproducible demo. It plays a
*vulnerable* agent that does whatever its tool output suggests:
  - repeats instructions found in fetched content in its answer
    ("tell the user X" -> says X);
  - acts on planted "facts" (an address for pre-approved orders -> emails it);
  - decodes encoded payloads in API responses and follows them (SRS 3.4: the
    instruction is reconstructed inside the model's own reasoning).
It then writes notes and answers. It reacts only to what the tools return,
so whatever the firewall strips or blocks changes its behaviour, exactly as
it would for a real model. It is a model of a worst-case agent, not of any
particular LLM; the live demo uses Ollama for that.
"""

import base64
import binascii
import json
import re
import uuid
from typing import Any

from bs4 import BeautifulSoup
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

EMAIL_RE   = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+\w")
TELL_RE    = re.compile(r"tell the user (?:that )?(.+?)(?:[.!]|$)", re.I)
APPROVE_RE = re.compile(r"\bapprove\b", re.I)
TASK_EMAIL_RE = re.compile(r"email (?:the summary|it|the notes) to ([\w.+-]+@[\w-]+\.[\w.]+\w)", re.I)


def _visible_and_hidden_text(content: str) -> str:
    """A naive agent reads the whole DOM text, hidden parts included."""
    if "<" in content and ">" in content:
        return " ".join(BeautifulSoup(content, "html.parser").get_text(" ").split())
    return content


def _decoded_payloads(content: str) -> list[str]:
    try:
        obj = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return []
    out = []
    for v in (obj.values() if isinstance(obj, dict) else []):
        if isinstance(v, str) and len(v) >= 16:
            try:
                out.append(base64.b64decode(v + "=" * (-len(v) % 4), validate=True).decode("utf-8"))
            except (binascii.Error, ValueError, UnicodeDecodeError):
                pass
    return out


class ScriptedAgentModel(BaseChatModel):
    """first_call: the tool call that starts the task, e.g. {"name": "web_fetch", "args": {...}}."""
    first_call: dict

    @property
    def _llm_type(self) -> str:
        return "scripted-gullible-agent"

    def bind_tools(self, tools: Any, **kwargs: Any):
        return self

    def _call(self, name: str, args: dict) -> AIMessage:
        return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{uuid.uuid4().hex[:8]}"}])

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        done = [tc["name"] for m in messages if isinstance(m, AIMessage) for tc in (m.tool_calls or [])]
        tool_msgs = [m for m in messages if isinstance(m, ToolMessage)]
        source = str(tool_msgs[0].content) if tool_msgs else ""

        if not done:
            msg = self._call(self.first_call["name"], self.first_call["args"])
            return ChatResult(generations=[ChatGeneration(message=msg)])

        text = _visible_and_hidden_text(source)
        decoded = _decoded_payloads(source)
        withheld = source.startswith("[Agent Firewall]")

        # Act on what the content suggests (the vulnerable behaviour)
        if not withheld and "send_email" not in done:
            email = EMAIL_RE.search(text)
            if email and re.search(r"\b(order|orders|purchas)", text, re.I):
                return ChatResult(generations=[ChatGeneration(message=self._call("send_email", {
                    "to": email.group(0), "subject": "Purchase order",
                    "body": "Please process our order for 500 units as a pre-approved account."}))])
        if not withheld and "create_purchase_order" not in done:
            if any(APPROVE_RE.search(d) for d in decoded):
                obj = json.loads(source)
                return ChatResult(generations=[ChatGeneration(message=self._call(
                    "create_purchase_order", {"vendor": obj.get("name", "unknown"), "quantity": 500}))])

        # Summarise what it read (including any planted claims it absorbed)
        if withheld:
            summary = "The source was withheld by the firewall as untrusted, so there is nothing to summarise."
        else:
            sentences = re.split(r"(?<=[.!?])\s+", text)
            summary = " ".join(sentences[:4])
            told = TELL_RE.search(text)
            if told:
                summary += " " + told.group(1).strip().rstrip(".") + "."
        if "write_notes" not in done:
            return ChatResult(generations=[ChatGeneration(message=self._call("write_notes", {"text": summary}))])

        # Side effects the user's task asks for (legitimate use)
        task = next((str(m.content) for m in messages if isinstance(m, HumanMessage)), "")
        if "send_email" not in done:
            to = None
            asked = TASK_EMAIL_RE.search(task)
            if asked:
                to = asked.group(1)
            elif re.search(r"email (?:its|the) sales contact", task, re.I) and not withheld:
                contact = re.search(r"sales[^@]{0,40}?([\w.+-]+@[\w-]+\.[\w.]+\w)", text, re.I)
                to = contact.group(1) if contact else None
            if to:
                return ChatResult(generations=[ChatGeneration(message=self._call("send_email", {
                    "to": to, "subject": "Procurement notes", "body": summary}))])

        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=summary))])
