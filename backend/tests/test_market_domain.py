"""Domain and adapter contracts, independently of the Flask application."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from market_sim.adapters import MiroFishMarketAdapter
from market_sim.engine import PriceImpactEngine
from market_sim.population import PopulationBuilder
from market_sim.types import MarketScenario


@pytest.fixture
def scenario():
    return MarketScenario("600519", "stock", "sector", 100, "mid", "neutral", 1,
                          agent_count=500, seed=42)


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setattr("market_sim.engine.time.sleep", lambda *_: None)


def test_extraction_preserves_recorded_behavior(scenario):
    engine = PriceImpactEngine(scenario, PopulationBuilder.build_population(scenario), [], [])
    ticks, summary = engine.run()
    digest = hashlib.sha256(json.dumps({
        "ticks": [tick.to_dict() for tick in ticks], "summary": summary,
        "agents": engine.world.agent_states(),
    }, sort_keys=True).encode()).hexdigest()
    assert digest == "6e32bc3d5a8bb35d75c7177d83845b49e978649a17d4b98716feff5d6d34b4fe"


def test_domain_imports_with_only_standard_library():
    result = subprocess.run([
        sys.executable, "-S", "-c",
        "from market_sim.adapters import MiroFishMarketAdapter; "
        "from market_sim.traders import TraderAgent; "
        "import sys; assert 'app' not in sys.modules; assert 'flask' not in sys.modules",
    ], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_adapter_steps_reset_and_exports(scenario):
    adapter = MiroFishMarketAdapter.from_config({"market_scenario": scenario.to_dict()})
    initial = adapter.observe()
    assert initial["tick_index"] == -1
    first = adapter.step()
    assert first["tick_index"] == 0
    ticks, summary = adapter.run()
    assert len(ticks) == 48
    exported = adapter.export()
    assert exported["completed"]
    assert len(exported["timeline"]) == 48
    assert len(exported["actions"]) == sum(summary["action_totals"].values())
    assert exported["actions"][0]["action_type"] in {"BUY", "SELL", "HOLD"}
    json.dumps(exported)
    with pytest.raises(RuntimeError):
        adapter.step()
    adapter.reset()
    assert adapter.observe()["price"] == scenario.starting_price
    replay, replay_summary = adapter.run()
    assert [tick.to_dict() for tick in replay] == [tick.to_dict() for tick in ticks]
    assert replay_summary == summary
    memory = adapter.observe(1)
    memory["memory"]["belief"] = 999
    assert adapter.observe(1)["memory"]["belief"] != 999


def test_agent_configuration_and_mixed_policies(scenario):
    observations = []

    class HoldPolicy:
        def decide(self, agent, observation):
            observations.append(observation)
            return 0

    config = {"market_scenario": scenario.to_dict(), "agent_configs": [
        {"agent_id": 1, "activity_level": 1, "influence_weight": 3},
        {"agent_id": 2, "activity_level": 0},
    ]}
    adapter = MiroFishMarketAdapter.from_config(
        config, policy_factory=lambda agent: HoldPolicy() if agent.agent_id == 1 else None)
    before = adapter.observe(1)["profile"]
    adapter.run()
    after = adapter.observe(1)
    assert observations and "world_context" in observations[0]["signals"]
    assert after["profile"]["cash"] == before["cash"]
    assert after["profile"]["holdings"] == before["holdings"]
    assert after["memory"]["observations"] > 0
    assert all(item["action"] == "hold" for item in after["memory"]["episodes"])
    assert adapter.observe(2)["memory"]["observations"] == 0
    assert adapter.observe(1)["profile"]["influence_weight"] == 3


def test_adapter_rejects_invalid_inputs(scenario):
    with pytest.raises(ValueError, match="minutes_per_round"):
        MiroFishMarketAdapter.from_config({"market_scenario": scenario.to_dict(),
                                          "time_config": {"minutes_per_round": 60}})
    with pytest.raises(ValueError, match="activity_level"):
        MiroFishMarketAdapter.from_config({"market_scenario": scenario.to_dict(),
            "agent_configs": [{"agent_id": 1, "activity_level": float("nan")}]})


def test_policy_cannot_emit_nonfinite_decision(scenario):
    class InvalidPolicy:
        def decide(self, agent, observation):
            return float("nan")

    adapter = MiroFishMarketAdapter.from_config({"market_scenario": scenario.to_dict()},
                                               policy_factory=lambda _: InvalidPolicy())
    with pytest.raises(ValueError, match="finite decision"):
        adapter.step()
