from dataclasses import replace

import pytest

from market_sim.types import MarketScenario, NewsItem, SentimentSignal
from market_sim.world import WorldStateBuilder
from market_sim.engine import PriceImpactEngine
from market_sim.population import PopulationBuilder
from market_sim.world import ShockBuilder
from market_sim.sentiment import news_weight, parse_time, forecast_time


@pytest.fixture
def scenario():
    return MarketScenario("600519", "stock", "sector", 100, "mid", "neutral", 1,
                          agent_count=500, seed=42,
                          market_snapshot={"as_of": "2026-03-10T15:00:00+08:00", "recent_prices": [
                              {"timestamp": "2026-03-10T14:50:00+08:00", "close": 98, "volume": 100},
                              {"timestamp": "2026-03-10T14:55:00+08:00", "close": 100, "volume": 200},
                          ]})


def signal(score=-0.7, mode="browser", timestamp="2026-03-10T14:59:00+08:00"):
    return SentimentSignal("xueqiu", timestamp, timestamp, "600519", "sector", score, 8, [],
                           {"mode": mode, "scope": "ticker", "sample_size": 12})


def news(timestamp, score):
    return NewsItem("test", timestamp, "headline", "", score, 1, "ticker", "")


def test_snapshot_excludes_future_and_stale_inputs(scenario):
    world = WorldStateBuilder.build(scenario, [
        news("2026-03-10T14:50:00+08:00", -0.5),
        news("2026-03-10T15:01:00+08:00", 1),
        news("2026-02-01T15:00:00+08:00", 1),
    ], [signal(), signal(1, timestamp="2026-03-11T15:00:00+08:00")], [], {}).to_dict()
    snapshot = world["current_sentiment"]
    assert snapshot["source_mode"] == "observed"
    assert snapshot["sentiment_score"] < 0
    assert snapshot["discussion_samples"] == 12
    assert snapshot["price_momentum"] == pytest.approx(100 / 98 - 1, abs=1e-5)
    assert snapshot["volume_ratio"] == 2
    assert snapshot["warnings"]
    assert len(world["seed_inputs"]["news_items"]) == 1
    assert len(world["seed_inputs"]["sentiment_signals"]) == 1
    # High discussion volume must not turn a bearish crowd into a bullish one.
    assert world["regime_factors"]["retail_herding"] < 0


def test_proxy_is_not_reported_as_observed_sentiment(scenario):
    world = WorldStateBuilder.build(scenario, [news("2026-03-10T14:50:00+08:00", -0.5)],
                                    [signal(1, mode="fallback")], [], {}).to_dict()
    snapshot = world["current_sentiment"]
    assert snapshot["source_mode"] == "news_proxy"
    assert snapshot["observed_windows"] == 0
    assert snapshot["sentiment_score"] < 0


def test_current_mood_seeds_memory_then_decays_without_future_inputs(scenario):
    world = WorldStateBuilder.build(scenario, [], [signal()], [], {}).to_dict()
    engine = PriceImpactEngine(scenario, PopulationBuilder.build_population(scenario, world), [], [], world)
    assert engine.world.memories[1]["belief"] < 0
    first, _ = engine._sentiment_state(0)
    later, _ = engine._sentiment_state(48)
    assert first < later < 0


@pytest.mark.parametrize("bars", [
    [{"timestamp": "2026-03-11T15:00:00+08:00", "close": 100, "volume": 1}],
    [{"timestamp": "2026-03-10T14:00:00+08:00", "close": float("nan"), "volume": 1}],
    [{"timestamp": "2026-03-10T14:00:00+08:00", "close": 100, "volume": -1}],
])
def test_invalid_market_tape_is_rejected(scenario, bars):
    with pytest.raises(ValueError):
        replace(scenario, market_snapshot={"as_of": scenario.market_snapshot["as_of"], "recent_prices": bars})


def test_market_and_stock_have_independent_sources_and_directions(scenario):
    market_signal = signal(0.8)
    market_signal.source = "macro_feed"
    market_signal.metadata["scope"] = "market"
    stock_signal = signal(-0.8)
    stock_signal.source = "stock_feed"
    world = WorldStateBuilder.build(scenario, [], [market_signal, stock_signal], [], {}).to_dict()
    channels = world["current_sentiment"]["channels"]
    assert channels["market"]["sentiment_score"] > 0
    assert channels["stock"]["sentiment_score"] < 0
    assert channels["market"]["sources"] == ["macro_feed"]
    assert channels["stock"]["sources"] == ["stock_feed"]
    no_macro = WorldStateBuilder.build(scenario, [], [stock_signal], [], {}).current_sentiment
    assert no_macro["channels"]["market"]["source_mode"] == "insufficient"


def test_news_fades_from_publication_and_does_not_restart_each_run(scenario):
    published = "2026-03-10T15:00:00+08:00"
    assert news_weight(published, parse_time(published)) == 1
    assert news_weight(published, parse_time("2026-03-12T03:00:00+08:00")) == 0.5
    assert news_weight(published, parse_time("2026-03-13T15:00:00+08:00")) == 0
    inputs = [news("2026-03-10T14:50:00+08:00", 0.8)]
    world = WorldStateBuilder.build(scenario, inputs, [], [], {}).to_dict()
    later = WorldStateBuilder.build(scenario, inputs, [], [], {},
                                    as_of=parse_time("2026-03-13T15:00:00+08:00"))
    assert later.current_sentiment["channels"]["stock"]["news_sentiment"] == 0
    assert later.regime_factors["institutional_conviction"] == 0
    assert later.archetype_biases["macro_news"]["world_alignment"] == 0
    durable = inputs[0]
    durable.metadata["sentiment_lifetime_hours"] = 168
    explicit = WorldStateBuilder.build(scenario, [durable], [], [], {},
                                       as_of=parse_time("2026-03-13T15:00:00+08:00"))
    assert explicit.current_sentiment["channels"]["stock"]["news_sentiment"] > 0


def test_runtime_expiry_applies_to_news_and_world_biases(scenario):
    scenario = replace(scenario, horizon_days=5)
    inputs = [news("2026-03-10T14:50:00+08:00", 0.8)]
    world = WorldStateBuilder.build(scenario, inputs, [], [], {}).to_dict()
    engine = PriceImpactEngine(scenario, PopulationBuilder.build_population(scenario, world),
                                ShockBuilder.build(scenario, inputs, []), [], world)
    assert engine._shock_state(0)[0] > 0
    assert engine._world_state_at(0)["institutional_conviction"] > 0
    # T143 is Friday 15:00, over 72 hours after Tuesday's publication.
    assert engine._shock_state(143)[0] == 0
    assert engine._world_state_at(143)["institutional_conviction"] == 0
    assert engine._sentiment_state(143)[0] == 0
    assert forecast_time("2026-03-13T15:00:00+08:00", 0).isoformat() == "2026-03-16T09:35:00+08:00"


def test_news_does_not_move_prices_without_trades(scenario, monkeypatch):
    monkeypatch.setattr("market_sim.engine.time.sleep", lambda *_: None)
    class HoldPolicy:
        def decide(self, agent, observation):
            return 0
    paths = []
    for score in (-0.8, 0.8):
        inputs = [news("2026-03-10T14:50:00+08:00", score)]
        world = WorldStateBuilder.build(scenario, inputs, [], [], {}).to_dict()
        engine = PriceImpactEngine(scenario, PopulationBuilder.build_population(scenario, world),
            ShockBuilder.build(scenario, inputs, []), [], world, policy_factory=lambda _: HoldPolicy())
        ticks, _ = engine.run()
        assert all(tick.net_demand == 0 for tick in ticks)
        paths.append([tick.price for tick in ticks])
    assert paths[0] == paths[1]
