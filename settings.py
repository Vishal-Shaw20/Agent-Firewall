"""
settings.py — Shared paths and config loading for Agent Firewall.
All paths are resolved relative to this file, so modules work from any cwd.
"""

from pathlib import Path
import yaml

ROOT        = Path(__file__).resolve().parent
CORPUS_PATH = ROOT / "corpus" / "corpus.jsonl"
PROBES_DIR  = ROOT / "corpus" / "probes"
MODELS_DIR  = ROOT / "models"
SCHEMAS_DIR = ROOT / "schemas"
CONFIG_DIR  = ROOT / "config"
LOGS_DIR    = ROOT / "logs"
RESULTS_DIR = ROOT / "eval" / "results"


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def firewall_config() -> dict:
    return load_yaml(CONFIG_DIR / "firewall.yaml")
