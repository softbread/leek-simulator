import json
import time
from dataclasses import replace

import pytest

from app import create_app
from app.config import Config
from app.models.market import MarketRunManager
from app.services.market.us_seeds import USEquitySeedProvider
from market_sim.adapters import MiroFishMarketAdapter
from market_sim.population import PopulationBuilder
from market_sim.sentiment import forecast_time
from market_sim.traders import ABMTraderPolicy
from market_sim.types import MarketScenario
from markets import get_profile
from markets.us_equity.semantics import score_text, social_signals


@pytest.fixture
def scenario():
    return MarketScenario("NVDA", "NVIDIA", "semiconductors", 100, "large", "neutral", 1,
        market="us_equity", agent_count=500, seed=42, data_mode="import_only",
        market_snapshot={"as_of": "2026-03-10T16:00:00-04:00"})


def test_us_sessions_dst_and_profile_boundaries():
    assert get_profile("us_equity").ticks_per_day == 78
    assert get_profile("cn_equity").ticks_per_day == 48
    assert get_profile("us_equity").daily_price_limit is None
    assert forecast_time("2026-03-06T16:00:00-05:00", 0, "us_equity").isoformat() == "2026-03-09T09:35:00-04:00"
    assert forecast_time("2026-03-10T16:00:00-04:00", 77, "us_equity").isoformat() == "2026-03-11T16:00:00-04:00"
    assert forecast_time("2026-03-10T16:00:00-04:00", 78, "us_equity").isoformat() == "2026-03-12T09:35:00-04:00"


def test_us_population_excludes_fundamentals(scenario):
    agents = PopulationBuilder.build_population(scenario)
    assert all(agent.archetype != "fundamental" and agent.fundamental_bias == 0 for agent in agents)
    assert any(agent.archetype == "social_contrarian" for agent in agents)
    with pytest.raises(ValueError, match="fundamental agents"):
        replace(scenario, trader_mix_overrides={"fundamental": 0.2})


def test_english_social_scoring_deduplicates_and_handles_negation(scenario):
    assert score_text("$NVDA bullish breakout") > 0
    assert score_text("$NVDA not bullish") < 0
    assert score_text("$NVDA not bearish") > 0
    assert score_text("$NVDA bullish /s") == 0
    posts = [{"source": "x", "scope": "ticker", "text": "$NVDA bullish", "published_at": "2026-03-10T15:55:00-04:00"},
             {"source": "reddit", "scope": "ticker", "text": "$NVDA bullish", "published_at": "2026-03-10T15:56:00-04:00"},
             {"source": "reddit", "scope": "ticker", "text": "unrelated bullish stock", "published_at": "2026-03-10T15:56:00-04:00"}]
    signals = social_signals(posts, scenario)
    assert len(signals) == 1
    assert signals[0].metadata["timestamp_basis"] == "published_at"


def test_fundamental_values_do_not_affect_us_decisions(scenario):
    agent = PopulationBuilder.build_population(scenario)[0]
    signals = {"momentum": 0.01, "valuation_gap": -0.5, "shock_bias": 0.2, "sector_bias": 0,
        "crowd_sentiment": 0.3, "crowd_buzz": 5, "drawdown": 0,
        "world_context": {"fundamentals_enabled": False, "policy_pressure": 0, "retail_herding": 0.2,
                          "institutional_conviction": 0, "valuation_temperature": 0, "tape_momentum_bias": 0, "downside_risk": 0}}
    observation = {"signals": signals, "memory": {"belief": 0, "peer_signal": 0, "experience": 0}}
    policy = ABMTraderPolicy()
    first = policy.decide(agent, observation)
    agent.fundamental_bias = 10000
    observation["signals"]["valuation_gap"] = 10000
    observation["signals"]["world_context"]["valuation_temperature"] = 10000
    assert policy.decide(agent, observation) == first


def test_us_social_weight_and_replay(scenario, monkeypatch):
    monkeypatch.setattr("market_sim.engine.time.sleep", lambda *_: None)
    config = {"market_scenario": scenario.to_dict(), "seed_inputs": {
        "news_items": [{"source": "bloomberg_import", "title": "NVIDIA bullish", "sentiment": 1,
                        "published_at": "2026-03-10T15:59:00-04:00", "affected_scope": "ticker", "relevance_score": 1}],
        "social_posts": [{"source": "reddit", "scope": "ticker", "text": "$NVDA bearish",
                          "published_at": "2026-03-10T15:59:00-04:00"}]}}
    adapter = MiroFishMarketAdapter.from_config(config)
    assert adapter.world.state["current_sentiment"]["channels"]["stock"]["sentiment_score"] < 0
    ticks, summary = adapter.run()
    assert len(ticks) == 78
    adapter.reset()
    replay, replay_summary = adapter.run()
    assert [tick.to_dict() for tick in ticks] == [tick.to_dict() for tick in replay]
    assert summary == replay_summary


def test_us_provider_missing_credentials_and_partial_failure(scenario, monkeypatch):
    monkeypatch.setattr(Config, "US_X_BEARER_TOKEN", "")
    monkeypatch.setattr(Config, "US_REDDIT_ACCESS_TOKEN", "")
    monkeypatch.setattr(Config, "US_NEWS_FEED_URL", "")
    provider = USEquitySeedProvider()
    def unavailable(*args, **kwargs):
        raise TimeoutError("test failure")
    monkeypatch.setattr(provider, "_read", unavailable)
    news, signals, health = provider.collect(replace(scenario, data_mode="live_and_imported"))
    assert not news and not signals
    assert health["providers"]["cnbc"] == "unavailable:TimeoutError"
    assert health["providers"]["x"] == "missing_credentials"


def test_live_provider_parsers_with_mocked_responses(scenario, monkeypatch):
    monkeypatch.setattr(Config, "US_X_BEARER_TOKEN", "test_token")
    monkeypatch.setattr(Config, "US_REDDIT_ACCESS_TOKEN", "test_token")
    monkeypatch.setattr(Config, "US_NEWS_FEED_URL", "")
    provider = USEquitySeedProvider()
    def read(url, token=None):
        if "cnbc.com" in url:
            return b'<rss><channel><item><title>NVIDIA bullish breakout</title><description>semiconductors growth</description><pubDate>Tue, 10 Mar 2026 19:55:00 GMT</pubDate><link>https://example.com/news</link></item></channel></rss>'
        if "api.x.com" in url:
            return json.dumps({"data": [{"text": "$NVDA bearish", "created_at": "2026-03-10T19:55:00Z"}]}).encode()
        return json.dumps({"data": {"children": [{"data": {"title": "$NVDA bullish", "selftext": "", "created_utc": 1773172500}}]}}).encode()
    monkeypatch.setattr(provider, "_read", read)
    news, signals, health = provider.collect(replace(scenario, data_mode="live_and_imported"))
    assert {item.affected_scope for item in news} == {"ticker", "sector", "market"}
    assert {item.source for item in signals} == {"x", "reddit"}
    assert health["providers"]["x"] == health["providers"]["reddit"] == "fetched"


def test_us_full_api_flow_never_calls_cn_sources(scenario, monkeypatch, tmp_path):
    monkeypatch.setattr(MarketRunManager, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr("market_sim.engine.time.sleep", lambda *_: None)
    def forbidden(*args, **kwargs):
        raise AssertionError("US must not call CN sources or auth")
    monkeypatch.setattr("app.services.market.runs.EastmoneyNewsAdapter.fetch_news", forbidden)
    monkeypatch.setattr("app.services.market.runs.XueqiuBrowserAuthService.is_authenticated", forbidden)
    monkeypatch.setattr("app.services.market.us_seeds.USEquitySeedProvider._read", forbidden)
    client = create_app().test_client()
    payload = scenario.to_dict()
    payload["seed_inputs"] = {"social_posts": [{"source": "robinhood_social", "scope": "ticker",
        "text": "$NVDA bullish breakout", "published_at": "2026-03-10T15:59:00-04:00"}]}
    response = client.post("/api/market/runs", json=payload)
    assert response.status_code == 200
    run_id = response.get_json()["data"]["run_id"]
    assert client.post(f"/api/market/runs/{run_id}/build-world").status_code == 200
    prepared = client.post(f"/api/market/runs/{run_id}/prepare").get_json()["data"]
    assert "xueqiu_authenticated" not in prepared["prepared_context"]["source_health"]
    assert all(item["fundamental_bias"] == 0 for item in prepared["prepared_context"]["population"])
    assert client.post(f"/api/market/runs/{run_id}/start").status_code == 200
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        run = MarketRunManager.get_run(run_id)
        if run.status.value in {"completed", "failed"}:
            break
    assert run.status.value == "completed", run.error
    result = client.get(f"/api/market/runs/{run_id}/results").get_json()["data"]
    assert len(result["series"]) == 78
    assert result["market_profile"]["currency"] == "USD"
    assert result["current_sentiment"]["channels"]["stock"]["sources"] == ["robinhood_social"]
