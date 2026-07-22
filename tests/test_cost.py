"""Tests for the cost model (no external services needed)."""
from agentops.cost import PRICING, cost_for


def test_known_model_cost():
    b = cost_for("gpt-4o", 1_000_000, 1_000_000)
    assert b.input_cost_usd == 2.50
    assert b.output_cost_usd == 10.00
    assert b.total_usd == 12.50


def test_real_local_model_cost():
    b = cost_for("llama3.2:1b", 1_000_000, 1_000_000)
    assert b.input_cost_usd == 0.02
    assert b.output_cost_usd == 0.04


def test_zero_tokens():
    b = cost_for("llama3.2:1b", 0, 0)
    assert b.total_usd == 0.0


def test_unknown_model_falls_back():
    # must not raise; uses the local fallback model's pricing
    b = cost_for("does-not-exist", 1_000_000, 0)
    assert b.input_cost_usd == PRICING["llama3.2:1b"][0]
