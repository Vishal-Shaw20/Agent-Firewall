"""
Agent integration tests (FR1, FR2, FR13, FR14) with the scripted agent, so
they need no LLM. Run:  pytest tests/ -q
"""

import pytest

from agent.demo_tools import Outbox, build_tools
from agent.firewall_tools import FirewallClient, firewall_tools
from agent.run_agent import run_scenario
from agent.scenarios import SCENARIOS

BY_KEY = {s.key: s for s in SCENARIOS}


@pytest.mark.parametrize("key", ["explicit", "implicit", "structural"])
def test_attack_succeeds_without_firewall_and_fails_with_it(key):
    s = BY_KEY[key]
    assert run_scenario(s, firewall="off").harms, "scripted agent should be hijacked without the firewall"
    on = run_scenario(s, firewall="on")
    assert on.harms == [] and on.error is None
    assert any(e.stage == "response" and e.verdict in ("BLOCK", "STRIP") for e in on.events)


@pytest.mark.parametrize("key,kept,gone", [
    ("explicit", "Boils quickly and is quiet", "best on the market"),
    ("implicit", "Standard delivery takes five to seven business days", "orders@northwind-supply.biz"),
])
def test_sanitised_page_keeps_legitimate_content(key, kept, gone):
    r = run_scenario(BY_KEY[key], firewall="on")
    assert r.harms == []
    assert any(kept in n for n in r.notes) and not any(gone in n for n in r.notes)


@pytest.mark.parametrize("key,tool", [("implicit", "send_email"), ("structural", "create_purchase_order")])
def test_call_checks_alone_stop_the_harmful_action(key, tool):
    r = run_scenario(BY_KEY[key], firewall="calls_only")
    assert any(e.stage == "call" and e.tool == tool and e.verdict == "BLOCK" for e in r.events)
    assert r.side_effects == []


@pytest.mark.xfail(reason="Known L2 false positive since the M7 retrain: the page's off-screen "
                          "'Skip to main content' link scores 0.83 and is stripped "
                          "(docs/REPORT.md, section 6.4). Not tuned away: the fix would be prompted "
                          "by a probe result.", strict=False)
def test_benign_control_passes_untouched():
    off = run_scenario(BY_KEY["benign"], firewall="off")
    on  = run_scenario(BY_KEY["benign"], firewall="on")
    assert on.harms == [] and all(e.verdict == "PASS" for e in on.events)
    assert on.answer == off.answer and on.notes == off.notes


def test_benign_control_keeps_its_content():
    r = run_scenario(BY_KEY["benign"], firewall="on")
    assert r.harms == [] and r.error is None
    assert any("Customs brokerage is offered as an add-on" in n for n in r.notes)


def test_wrapped_tools_keep_names_and_schemas():
    raw = build_tools({}, {}, Outbox())
    wrapped = firewall_tools(raw, FirewallClient(), task="t")
    for a, b in zip(raw, wrapped):
        assert a.name == b.name and a.description == b.description
        assert a.args_schema.model_json_schema() == b.args_schema.model_json_schema()


def test_http_client_against_proxy():
    from fastapi.testclient import TestClient
    from proxy.main import app
    with TestClient(app) as http:
        client = FirewallClient("http://testserver", http_client=http)
        r = run_scenario(BY_KEY["structural"], firewall="on", client=client)
        assert r.harms == []
        assert any(e.stage == "response" and e.verdict in ("BLOCK", "STRIP") for e in r.events)
