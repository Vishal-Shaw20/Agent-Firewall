# Agent Firewall 🛡️

A distribution-aware, multi-layer proxy for detecting **Indirect Prompt Injection** 
in LLM agent tool calls.

**B.Tech Major Project | 7th Semester**

## What it does
LLM agents that browse the web or call APIs cannot tell the difference between 
legitimate content and attacker-planted instructions. Agent Firewall sits between 
the agent and its tools, intercepting every tool response and screening it through 
a five-layer detection pipeline before it reaches the agent's context.

## Detection Pipeline
| Layer | Type | Description |
|---|---|---|
| L1 | Heuristic | Regex-based explicit injection pattern matching |
| L2 | Classifier | Fine-tuned DistilBERT (explicit + implicit trained) |
| L3 | Concealment | CSS/DOM hiding detection + render-vs-extract diff |
| L4 | Taint | Goal-consistency check via semantic similarity |
| L5 | Schema | Per-tool schema validation + entropy analysis |

## Tech Stack
- **Proxy**: FastAPI + Uvicorn
- **Agent**: LangChain + Ollama (Llama 3)
- **Classifier**: HuggingFace DistilBERT
- **Storage**: Redis
- **Eval**: pandas + scikit-learn

## Setup
```bash
conda activate agentfw
pip install -r requirements.txt
