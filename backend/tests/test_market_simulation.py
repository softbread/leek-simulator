import json
import time

import pytest

from app import create_app
from app.models.market import MarketRunManager, MarketScenario
from app.services.market_simulation import (
    EastmoneyNewsAdapter,
    NewsItem,
    PopulationBuilder,
    PriceImpactEngine,
    SentimentSignal,
    WorldStateBuilder,
    XueqiuSentimentAdapter,
)


class FakeHttpResponse:
    def __init__(self, payload: str):
        self.payload = payload.encode("utf-8")
        self.status = 200

    def read(self):
        return self.payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_population_builder_respects_agent_count_and_mix():
    scenario = MarketScenario(
        ticker="SH600519",
        stock_name="贵州茅台",
        sector_name="白酒",
        starting_price=1400,
        float_shares_band="mega",
        market_regime="volatile",
        horizon_days=3,
        agent_count=500,
        trader_mix_overrides={
            "fundamental": 0.7,
            "fomo_momentum": 0.1,
            "macro_news": 0.1,
            "mean_reversion": 0.05,
            "passive_retail": 0.05,
        },
        seed=7,
    )
    population = PopulationBuilder.build_population(scenario)
    summary = PopulationBuilder.summarize_population(population)

    assert len(population) == 500
    assert summary["archetypes"]["fundamental"] > summary["archetypes"]["fomo_momentum"]
    assert summary["agent_count"] == 500


def test_eastmoney_adapter_parses_jsonp(monkeypatch):
    payload = {
        "bizCode": "",
        "bizMsg": "",
        "hitsTotal": 2,
        "result": {
            "cmsArticleWebOld": [
                {
                    "date": "2026-03-09 17:29:07",
                    "title": "贵州茅台 回购进展",
                    "content": "公司回购属于典型利好。",
                    "mediaName": "测试媒体",
                    "url": "http://example.com/a",
                }
            ]
        },
    }

    def fake_urlopen(request, timeout=15):
        return FakeHttpResponse(f"?({json.dumps(payload, ensure_ascii=False)})")

    monkeypatch.setattr("app.services.market_simulation.urllib.request.urlopen", fake_urlopen)

    adapter = EastmoneyNewsAdapter()
    items = adapter.fetch_news("贵州茅台", "ticker", limit=5)

    assert len(items) == 1
    assert items[0].source == "eastmoney"
    assert items[0].affected_scope == "ticker"
    assert items[0].sentiment > 0


def test_price_impact_engine_is_deterministic():
    scenario = MarketScenario(
        ticker="SH600519",
        stock_name="贵州茅台",
        sector_name="白酒",
        starting_price=1400,
        float_shares_band="large",
        market_regime="neutral",
        horizon_days=1,
        agent_count=500,
        seed=42,
    )
    agents_one = PopulationBuilder.build_population(scenario)
    agents_two = PopulationBuilder.build_population(scenario)
    signals = [
        SentimentSignal(
            source="xueqiu",
            window_start="D1-W1",
            window_end="D1-W2",
            ticker="SH600519",
            sector="白酒",
            sentiment_score=0.15,
            buzz_score=2.5,
            topic_tags=["白酒"],
            metadata={"mode": "fallback"},
        )
    ]
    shocks = []

    engine_one = PriceImpactEngine(scenario, agents_one, shocks, signals)
    engine_two = PriceImpactEngine(scenario, agents_two, shocks, signals)
    ticks_one, _ = engine_one.run()
    ticks_two, _ = engine_two.run()

    assert ticks_one[-1].price == ticks_two[-1].price
    assert ticks_one[-1].volume == ticks_two[-1].volume


def test_world_state_changes_agent_path():
    scenario = MarketScenario(
        ticker="SH600519",
        stock_name="贵州茅台",
        sector_name="白酒",
        starting_price=1400,
        float_shares_band="large",
        market_regime="neutral",
        horizon_days=1,
        agent_count=500,
        seed=42,
    )
    news = [
        NewsItem(
            source="eastmoney",
            published_at="2026-03-10 09:30:00",
            title="消费修复预期升温",
            summary="白酒板块迎来强劲修复，情绪利好。",
            sentiment=0.6,
            relevance_score=0.9,
            affected_scope="sector",
            url="http://example.com/news",
        )
    ]
    signals = [
        SentimentSignal(
            source="xueqiu",
            window_start="D1-W1",
            window_end="D1-W2",
            ticker="SH600519",
            sector="白酒",
            sentiment_score=0.45,
            buzz_score=6.0,
            topic_tags=["消费修复", "白酒"],
            metadata={"mode": "fallback"},
        )
    ]
    world_state = WorldStateBuilder.build(
        scenario,
        news,
        signals,
        ["纪要提到渠道改善、风险偏好提升。"],
        {"eastmoney_news_count": 1, "xueqiu_mode": "fallback", "xueqiu_authenticated": False},
    ).to_dict()
    baseline_agents = PopulationBuilder.build_population(scenario)
    world_agents = PopulationBuilder.build_population(scenario, world_state=world_state)

    baseline_engine = PriceImpactEngine(scenario, baseline_agents, [], signals)
    world_engine = PriceImpactEngine(scenario, world_agents, [], signals, world_state=world_state)
    baseline_ticks, _ = baseline_engine.run()
    world_ticks, _ = world_engine.run()

    assert baseline_ticks[-1].price != world_ticks[-1].price


def test_xueqiu_adapter_prefers_browser_session(monkeypatch):
    scenario = MarketScenario(
        ticker="SH600519",
        stock_name="贵州茅台",
        sector_name="白酒",
        starting_price=1400,
        float_shares_band="large",
        market_regime="neutral",
        horizon_days=1,
        agent_count=500,
        seed=42,
    )
    adapter = XueqiuSentimentAdapter()

    monkeypatch.setattr("app.services.market_simulation.XueqiuBrowserAuthService.is_authenticated", lambda: True)
    monkeypatch.setattr(
        "app.services.market_simulation.XueqiuBrowserAuthService.fetch_search_statuses",
        lambda query, count=10: [{"text": f"{query} 利好 修复 看多"}],
    )
    monkeypatch.setattr(
        "app.services.market_simulation.XueqiuBrowserAuthService.scrape_stock_page",
        lambda ticker, sample_limit=12: ["散户 FOMO，继续看多 贵州茅台"],
    )

    signals = adapter.fetch_signals(scenario, [])

    assert signals
    assert signals[0].metadata["mode"] == "browser"
    assert signals[0].buzz_score > 0


@pytest.fixture()
def app_client(monkeypatch):
    monkeypatch.setattr("app.services.market_simulation.time.sleep", lambda *_args, **_kwargs: None)

    def fake_fetch_news(self, keyword, affected_scope, limit=6):
        sentiment = 0.25 if affected_scope == "ticker" else 0.08
        return [
            NewsItem(
                source="eastmoney",
                published_at="2026-03-10 09:30:00",
                title=f"{keyword} 新闻脉冲",
                summary=f"{keyword} 出现正向催化。",
                sentiment=sentiment,
                relevance_score=0.8,
                affected_scope=affected_scope,
                url=f"http://example.com/{keyword}",
            )
        ]

    def fake_fetch_signals(self, scenario, news_items):
        return [
            SentimentSignal(
                source="xueqiu",
                window_start="D1-W1",
                window_end="D1-W2",
                ticker=scenario.ticker,
                sector=scenario.sector_name,
                sentiment_score=0.22,
                buzz_score=4.0,
                topic_tags=["情绪", "白酒"],
                metadata={"mode": "fallback"},
            ),
            SentimentSignal(
                source="xueqiu",
                window_start="D1-W2",
                window_end="D1-W3",
                ticker=scenario.ticker,
                sector=scenario.sector_name,
                sentiment_score=0.1,
                buzz_score=3.2,
                topic_tags=["修复"],
                metadata={"mode": "fallback"},
            ),
        ]

    monkeypatch.setattr("app.services.market_simulation.EastmoneyNewsAdapter.fetch_news", fake_fetch_news)
    monkeypatch.setattr("app.services.market_simulation.XueqiuSentimentAdapter.fetch_signals", fake_fetch_signals)

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_market_api_flow(app_client):
    create_response = app_client.post(
        "/api/market/runs",
        json={
            "ticker": "SH600519",
            "stock_name": "贵州茅台",
            "sector_name": "白酒",
            "starting_price": 1400,
            "float_shares_band": "large",
            "market_regime": "volatile",
            "horizon_days": 1,
            "agent_count": 500,
            "trader_mix_overrides": {
                "fomo_momentum": 30,
                "macro_news": 25,
                "fundamental": 20,
                "mean_reversion": 15,
                "passive_retail": 10,
            },
        },
    )
    assert create_response.status_code == 200
    run_id = create_response.get_json()["data"]["run_id"]

    world_response = app_client.post(f"/api/market/runs/{run_id}/build-world")
    assert world_response.status_code == 200
    assert world_response.get_json()["data"]["world_state"]["world_summary"]["top_narrative"]

    prepare_response = app_client.post(f"/api/market/runs/{run_id}/prepare")
    assert prepare_response.status_code == 200
    prepared_context = prepare_response.get_json()["data"]["prepared_context"]
    assert prepared_context["source_health"]["eastmoney_news_count"] >= 2
    assert prepared_context["world_state"]["world_summary"]["top_narrative"]

    start_response = app_client.post(f"/api/market/runs/{run_id}/start")
    assert start_response.status_code == 200

    deadline = time.time() + 5
    while time.time() < deadline:
        status_response = app_client.get(f"/api/market/runs/{run_id}/status")
        payload = status_response.get_json()["data"]
        if payload["status"] == "completed":
            break
        time.sleep(0.05)

    final_run = MarketRunManager.get_run(run_id)
    assert final_run is not None
    assert final_run.status.value == "completed"

    results_response = app_client.get(f"/api/market/runs/{run_id}/results")
    assert results_response.status_code == 200
    results_payload = results_response.get_json()["data"]
    assert results_payload["metrics"]["ending_price"] > 0
    assert results_payload["xueqiu_summary"]["average_buzz"] > 0

    chat_response = app_client.post(f"/api/market/runs/{run_id}/chat", json={"message": "这轮走势是谁主导的？"})
    assert chat_response.status_code == 200
    assert chat_response.get_json()["data"]["answer"]
