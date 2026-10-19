from dataclasses import replace

import pytest

from market_sim.dynamics import CycleDynamics, classify_phase, market_cycle
from market_sim.population import PopulationBuilder
from market_sim.types import MarketScenario
from market_sim.traders import ABMTraderPolicy
from market_sim.world import WorldStateBuilder


@pytest.fixture
def scenario():
    return MarketScenario("600519", "stock", "sector", 100, "mid", "neutral", 1,
        agent_count=500, seed=42, market_snapshot={"as_of": "2026-03-10T15:00:00+08:00"})


@pytest.mark.parametrize("pressure,change,buying,selling,expected", [
    (0.5, 0.1, 0.8, 0.2, "rising"),
    (0.5, -0.2, 0.8, 0.2, "top_consolidation"),
    (0.5, 0.1, 0.05, 0.95, "top_consolidation"),
    (-0.5, -0.1, 0.8, 0.2, "falling"),
    (-0.5, 0.2, 0.8, 0.2, "bottom_consolidation"),
])
def test_phases_depend_on_state_not_elapsed_time(pressure, change, buying, selling, expected):
    assert classify_phase(pressure, change, buying, selling) == expected


def test_depleted_cash_weakens_fomo_even_when_mood_stays_positive(scenario):
    profile = replace(PopulationBuilder.build_population(scenario)[0], archetype="fomo_momentum")
    snapshot = {"as_of": scenario.market_snapshot["as_of"]}
    base = {"stock_sentiment": 0.8, "simulated_at": "2026-03-10T15:00:00+08:00"}
    rich = CycleDynamics([replace(profile, cash=900, holdings=1)], snapshot, 100).observe(base)
    depleted = CycleDynamics([replace(profile, cash=10, holdings=10)], snapshot, 100).observe(base)
    assert rich["buying_capacity"] > depleted["buying_capacity"]
    assert depleted["cycle_phase"] == "top_consolidation"
    def score(cycle):
        context = {"policy_pressure": 0, "retail_herding": 0.8, "institutional_conviction": 0,
                   "valuation_temperature": 0, "tape_momentum_bias": 0, "downside_risk": 0, **cycle}
        observation = {"memory": {"belief": 0.5, "peer_signal": 0, "experience": 0}, "signals": {
            "momentum": 0, "valuation_gap": 0, "shock_bias": 0, "sector_bias": 0,
            "crowd_sentiment": 0.5, "crowd_buzz": 3, "drawdown": 0, "world_context": context}}
        return ABMTraderPolicy().decide(profile, observation)
    assert score(depleted) < score(rich)


def test_overnight_impulse_and_flow_use_completed_rounds(scenario):
    agent = PopulationBuilder.build_population(scenario)[0]
    dynamics = CycleDynamics([agent], {"as_of": scenario.market_snapshot["as_of"]}, 100)
    base = {"stock_sentiment": 0.6, "simulated_at": "2026-03-11T09:35:00+08:00"}
    before = dynamics.observe(base)
    assert before["flow_pressure"] == 0
    assert before["overnight_impulse"] > 0
    dynamics.commit(101, 0.01, [{"signed_quantity": 100}], before)
    after = dynamics.observe({**base, "simulated_at": "2026-03-11T09:40:00+08:00"})
    assert after["flow_pressure"] == 1
    assert after["overnight_impulse"] < before["overnight_impulse"]


def test_market_breadth_is_independent_and_not_invented(scenario):
    assert market_cycle([])["source"] == "missing_breadth"
    history = [{"timestamp": "2026-03-10T15:00:00+08:00", "advancers": 3500, "decliners": 1000,
                "limit_up": 90, "limit_down": 5, "promotion_rate": 0.7, "source": "test_market"}]
    snapshot_scenario = replace(scenario, market_snapshot={**scenario.market_snapshot, "market_breadth": history})
    snapshot = WorldStateBuilder.build(snapshot_scenario, [], [], [], {}).current_sentiment
    assert snapshot["market_cycle"]["phase"] == "rising"
    assert snapshot["channels"]["market"]["source_mode"] == "market_breadth"
    assert snapshot["channels"]["stock"]["source_mode"] == "insufficient"
    assert snapshot["channels"]["market"]["sources"] == ["test_market"]
    with pytest.raises(ValueError):
        replace(scenario, market_snapshot={**scenario.market_snapshot, "market_breadth": [
            {**history[0], "timestamp": "2026-03-11T15:00:00+08:00"}]})


def test_world_has_no_prescheduled_emotion_cycle(scenario):
    world = WorldStateBuilder.build(scenario, [], [], [], {})
    assert len(world.tick_blueprint) == 1
    assert world.tick_blueprint[0]["name"] == "adaptive_market"
