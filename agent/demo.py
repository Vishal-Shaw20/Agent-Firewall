"""
demo.py — Live demo (FR13): every scenario run with the firewall off, on, and
with tool-call checks only, side by side, including the SRS's
explicit-vs-implicit pair.

Usage:
    python -m agent.demo                         # scripted gullible agent, in-process firewall
    python -m agent.demo --backend ollama        # local LLM via Ollama
    python -m agent.demo --backend ollama --model qwen2.5:7b
    python -m agent.demo --http http://localhost:8000   # use a running proxy (off/on modes)
    python -m agent.demo --only implicit         # one scenario

Writes eval/results/demo_<backend>.md.
"""

import os
import sys
import time

from agent.firewall_tools import FirewallClient
from agent.run_agent import run_scenario, DEFAULT_OLLAMA_MODEL
from agent.scenarios import SCENARIOS
from settings import RESULTS_DIR

# off        no firewall
# on         tool calls and tool responses screened
# calls_only response screening disabled; only L4 action mode checks tool calls
MODES = ("off", "on", "calls_only")
TAGS  = {"off": "firewall OFF ", "on": "firewall ON  ", "calls_only": "calls only   "}


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def _short(text: str, n: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 1] + "…"


def _calls(r) -> str:
    return " → ".join(name for name, _ in r.tool_calls) or "(none)"


def _fw(r) -> str:
    if r.firewall == "off":
        return "—"
    return "; ".join(f"{e.stage}:{e.tool}={e.verdict}" + (f" ({e.reason})" if e.verdict != "PASS" else "")
                     for e in r.events) or "(no tool calls)"


def main():
    backend = _arg("--backend", "scripted")
    only    = _arg("--only")
    client  = FirewallClient(_arg("--http"))
    modes   = [m for m in MODES if not (m == "calls_only" and client.base_url)]
    scenarios = [s for s in SCENARIOS if not only or s.key == only]

    model = _arg("--model") or os.getenv("OLLAMA_MODEL") or DEFAULT_OLLAMA_MODEL
    label = "scripted gullible agent" if backend == "scripted" else f"Ollama ({model})"
    print(f"\nAgent Firewall demo — backend: {label}\n")

    rows = []
    for s in scenarios:
        print(f"━━ {s.title}  [{s.style}]")
        print(f"   task: {s.task}")
        runs = {}
        for mode in modes:
            r = run_scenario(s, backend=backend, firewall=mode, client=client, model_name=model)
            runs[mode] = r
            status = "HARMED: " + "; ".join(r.harms) if r.harms else "no harm"
            print(f"   {TAGS[mode]}| calls: {_calls(r)}")
            if mode != "off":
                print(f"                | firewall: {_fw(r)}")
            print(f"                | side effects: {', '.join(r.side_effects) or 'none'}")
            print(f"                | answer: {_short(r.answer or r.error or '')}")
            print(f"                | => {status}  ({r.seconds}s)")
        print()
        rows.append((s, runs))

    attacks = sum(1 for s, _ in rows if s.style != "benign")

    def harmed(mode):
        return sum(bool(runs[mode].harms) for s, runs in rows if s.style != "benign")

    benign_ok = all(not runs["on"].harms and not runs["on"].error
                    for s, runs in rows if s.style == "benign")
    summary = (f"Attacks that succeeded: {harmed('off')}/{attacks} with the firewall off, "
               f"{harmed('on')}/{attacks} with it on"
               + (f", {harmed('calls_only')}/{attacks} with tool-call checks only" if "calls_only" in modes else "")
               + f". Benign control unaffected: {'yes' if benign_ok else 'NO'}.")
    print(summary)

    md = [f"# Agent Firewall demo — {label}", "", f"Run at {time.strftime('%Y-%m-%d %H:%M:%S')}.", "",
          summary, "",
          "Modes: **off** = no firewall; **on** = tool calls and tool responses screened; "
          "**calls_only** = response screening disabled, only L4 action mode checks tool calls.", "",
          "| scenario | style | mode | tool calls | firewall decisions | side effects | outcome |",
          "|---|---|---|---|---|---|---|"]
    for s, runs in rows:
        for mode, r in runs.items():
            outcome = ("**harmed**: " + "; ".join(r.harms)) if r.harms else ("error: " + r.error if r.error else "ok")
            md.append(f"| {s.key} | {s.style} | {mode} | {_calls(r)} | {_fw(r)} | "
                      f"{', '.join(r.side_effects) or 'none'} | {outcome} |")
    md += ["", "## Answers", ""]
    for s, runs in rows:
        for mode, r in runs.items():
            md.append(f"- **{s.key}, {mode}:** {_short(r.answer or r.error or '', 400)}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = backend if backend == "scripted" else f"{backend}_{model.replace(':', '-')}"
    out = RESULTS_DIR / f"demo_{suffix}.md"
    out.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
