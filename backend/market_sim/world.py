"""Build a seeded market world without network or persistence dependencies."""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List
from .utils import _clamp, _extract_topics, _now_iso, _score_sentiment
from .types import MarketScenario, MarketWorldState, NewsItem, SentimentSignal, MarketShock, TICKS_PER_DAY
from .sentiment import build_snapshot, current_seeds, news_lifetime_hours
from markets import get_profile


def score_material(text, scenario):
    if scenario.market == "us_equity":
        from markets.us_equity.semantics import score_text
        return score_text(text)
    return _score_sentiment(text)

class ShockBuilder:
    @staticmethod
    def build(
        scenario: MarketScenario,
        news_items: List[NewsItem],
        upload_texts: List[str],
    ) -> List[MarketShock]:
        shocks: List[MarketShock] = []
        for index, item in enumerate(news_items[:12]):
            # Collected news is known at the forecast boundary, not future news.
            start_tick = 0
            duration = scenario.horizon_days * get_profile(scenario.market).ticks_per_day
            strength = round(0.6 + abs(item.sentiment) * 1.6 + item.relevance_score * 0.8, 4)
            shocks.append(
                MarketShock(
                    shock_type="news",
                    start_tick=start_tick,
                    duration_ticks=duration,
                    direction=item.sentiment,
                    strength=strength,
                    affected_scope=item.affected_scope,
                    headline=item.title,
                    source_refs=[item.url] if item.url else [],
                    published_at=item.published_at,
                    decay_hours=news_lifetime_hours(item),
                )
            )
        for index, text in enumerate(upload_texts[:4]):
            score = score_material(text, scenario)
            if abs(score) < 0.05:
                continue
            excerpt = re.sub(r"\s+", " ", text)[:80]
            shocks.append(
                MarketShock(
                    shock_type="upload_context",
                    start_tick=0,
                    duration_ticks=scenario.horizon_days * get_profile(scenario.market).ticks_per_day,
                    direction=1.0 if score >= 0 else -1.0,
                    strength=round(0.85 + abs(score), 4),
                    affected_scope="ticker",
                    headline=f"上传材料提及: {excerpt}",
                    source_refs=[],
                    published_at=scenario.market_snapshot.get("as_of") or datetime.now(timezone.utc).isoformat(),
                )
            )
        return shocks

class WorldStateBuilder:
    @staticmethod
    def build(
        scenario: MarketScenario,
        news_items: List[NewsItem],
        sentiment_signals: List[SentimentSignal],
        upload_texts: List[str],
        source_health: Dict[str, Any],
        as_of=None,
        upload_decay=1.0,
    ) -> MarketWorldState:
        cutoff, news_items, sentiment_signals, excluded = current_seeds(scenario, news_items, sentiment_signals, as_of)
        snapshot = build_snapshot(scenario, news_items, sentiment_signals, cutoff, excluded)
        ticker_sentiment = snapshot["ticker_news_sentiment"]
        sector_sentiment = snapshot["sector_news_sentiment"]
        crowd_sentiment = snapshot["channels"]["stock"]["sentiment_score"]
        market_sentiment = snapshot["channels"]["market"]["sentiment_score"]
        crowd_buzz = snapshot["buzz_score"]
        upload_sentiment = sum(score_material(text, scenario) for text in upload_texts) / max(len(upload_texts), 1) * upload_decay
        regime_bias = {
            "bullish": 0.22,
            "neutral": 0.0,
            "bearish": -0.22,
            "volatile": 0.04 if crowd_sentiment >= 0 else -0.04,
        }.get(scenario.market_regime, 0.0)
        policy_pressure = _clamp(market_sentiment * 0.8 + sector_sentiment * 0.3 + upload_sentiment * 0.15 + regime_bias, -1.4, 1.4)
        retail_herding = _clamp(crowd_sentiment * (0.85 + min(crowd_buzz / 8.5, 1.2) * 0.45), -1.4, 1.6)
        institutional_conviction = _clamp(
            ticker_sentiment * 0.55 + sector_sentiment * 0.28 + upload_sentiment * 0.45 - retail_herding * 0.12,
            -1.2,
            1.2,
        )
        valuation_temperature = _clamp(
            crowd_sentiment * 0.45 + min(crowd_buzz / 10.0, 1.0) * 0.35 - institutional_conviction * 0.2 + regime_bias * 0.4,
            -1.0,
            1.35,
        )
        if not get_profile(scenario.market).fundamentals_enabled:
            valuation_temperature = 0.0
        liquidity_temperature = _clamp(
            0.42 + min(crowd_buzz / 7.5, 1.4) + abs(policy_pressure) * 0.25
            + _clamp((snapshot["volume_ratio"] - 1) * 0.2, -0.2, 0.4)
            + (0.18 if scenario.market_regime == "volatile" else 0.0),
            0.15,
            2.0,
        )
        tape_momentum_seed = _clamp(ticker_sentiment * 0.55 + crowd_sentiment * 0.35
                                    + regime_bias * 0.6 + _clamp(snapshot["price_momentum"] * 5, -0.6, 0.6), -1.2, 1.2)
        downside_risk = _clamp(
            max(0.0, -policy_pressure) * 0.7
            + max(0.0, -institutional_conviction) * 0.55
            + (0.18 if scenario.market_regime == "bearish" else 0.0),
            0.0,
            1.5,
        )
        sector_heat = _clamp(sector_sentiment * 0.75 + min(crowd_buzz / 11.0, 1.0) * 0.25 + regime_bias * 0.35, -1.2, 1.2)
        narrative_temperature = _clamp((abs(policy_pressure) + abs(retail_herding) + abs(institutional_conviction)) / 3, 0.1, 1.6)

        all_texts = [item.title for item in news_items] + [item.summary for item in news_items] + upload_texts
        topics = _extract_topics(all_texts, limit=10)
        narratives = WorldStateBuilder._build_narratives(
            scenario=scenario,
            news_items=news_items,
            sentiment_signals=sentiment_signals,
            topics=topics,
            factors={
                "policy_pressure": policy_pressure,
                "retail_herding": retail_herding,
                "institutional_conviction": institutional_conviction,
                "valuation_temperature": valuation_temperature,
                "sector_heat": sector_heat,
            },
        )
        causal_graph = WorldStateBuilder._build_causal_graph(scenario, narratives, topics, {
            "policy_pressure": policy_pressure,
            "retail_herding": retail_herding,
            "institutional_conviction": institutional_conviction,
            "liquidity_temperature": liquidity_temperature,
            "valuation_temperature": valuation_temperature,
            "tape_momentum_seed": tape_momentum_seed,
            "downside_risk": downside_risk,
            "sector_heat": sector_heat,
        })
        total_ticks = max(1, scenario.horizon_days) * get_profile(scenario.market).ticks_per_day
        tick_blueprint = WorldStateBuilder._build_tick_blueprint(total_ticks, narratives, {
            "policy_pressure": policy_pressure,
            "retail_herding": retail_herding,
            "institutional_conviction": institutional_conviction,
            "liquidity_temperature": liquidity_temperature,
            "valuation_temperature": valuation_temperature,
            "tape_momentum_seed": tape_momentum_seed,
            "downside_risk": downside_risk,
            "sector_heat": sector_heat,
            "narrative_temperature": narrative_temperature,
        })
        archetype_biases = WorldStateBuilder._build_archetype_biases({
            "policy_pressure": policy_pressure,
            "retail_herding": retail_herding,
            "institutional_conviction": institutional_conviction,
            "liquidity_temperature": liquidity_temperature,
            "valuation_temperature": valuation_temperature,
            "tape_momentum_seed": tape_momentum_seed,
            "downside_risk": downside_risk,
            "sector_heat": sector_heat,
            "narrative_temperature": narrative_temperature,
        })

        return MarketWorldState(
            current_sentiment=snapshot,
            built_at=_now_iso(),
            scenario_snapshot=scenario.to_dict(),
            seed_inputs={
                "news_items": [item.to_dict() for item in news_items],
                "sentiment_signals": [item.to_dict() for item in sentiment_signals],
                "upload_texts": upload_texts,
                "topics": topics,
            },
            source_health=source_health,
            regime_factors={
                "policy_pressure": round(policy_pressure, 4),
                "retail_herding": round(retail_herding, 4),
                "institutional_conviction": round(institutional_conviction, 4),
                "liquidity_temperature": round(liquidity_temperature, 4),
                "valuation_temperature": round(valuation_temperature, 4),
                "tape_momentum_seed": round(tape_momentum_seed, 4),
                "downside_risk": round(downside_risk, 4),
                "sector_heat": round(sector_heat, 4),
                "narrative_temperature": round(narrative_temperature, 4),
            },
            dominant_narratives=narratives[:5],
            causal_graph=causal_graph,
            archetype_biases=archetype_biases,
            tape_state={
                "price_anchor": round(scenario.starting_price, 4),
                "support_level": round(scenario.starting_price * (1 - max(0.02, downside_risk * 0.035)), 4),
                "resistance_level": round(scenario.starting_price * (1 + max(0.025, max(0.0, retail_herding) * 0.05 + max(0.0, policy_pressure) * 0.04)), 4),
                "initial_drift": round(tape_momentum_seed * 0.012, 5),
                "observed_momentum": snapshot["price_momentum"],
            },
            tick_blueprint=tick_blueprint,
            world_summary={
                "market": scenario.market,
                "ticks_per_day": get_profile(scenario.market).ticks_per_day,
                "dominant_market_style": WorldStateBuilder._dominant_style(policy_pressure, retail_herding, institutional_conviction, valuation_temperature),
                "headline_count": len(news_items),
                "discussion_windows": len(sentiment_signals),
                "topics": topics[:6],
                "top_narrative": narratives[0]["label"] if narratives else scenario.stock_name,
                "sentiment_as_of": snapshot["as_of"],
                "sentiment_source_mode": snapshot["source_mode"],
            },
        )

    @staticmethod
    def _build_narratives(
        scenario: MarketScenario,
        news_items: List[NewsItem],
        sentiment_signals: List[SentimentSignal],
        topics: List[str],
        factors: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        narratives: List[Dict[str, Any]] = []
        for item in sorted(news_items, key=lambda value: abs(value.sentiment) * value.relevance_score, reverse=True)[:4]:
            narratives.append({
                "label": item.title[:48],
                "scope": item.affected_scope,
                "stance": "bullish" if item.sentiment >= 0 else "bearish",
                "intensity": round(_clamp(abs(item.sentiment) * 0.9 + item.relevance_score, 0.15, 1.6), 4),
                "topic_tags": _extract_topics([item.title, item.summary], limit=4) or topics[:3],
                "source": item.source,
            })
        if sentiment_signals:
            dominant_topics = _extract_topics([" ".join(signal.topic_tags) for signal in sentiment_signals], limit=4) or topics[:4]
            narratives.append({
                "label": f"社交情绪主线: {' / '.join(dominant_topics[:2] or [scenario.stock_name])}",
                "scope": "ticker",
                "stance": "bullish" if factors["retail_herding"] >= 0 else "bearish",
                "intensity": round(_clamp(abs(factors["retail_herding"]) * 0.95 + abs(factors["valuation_temperature"]) * 0.25, 0.2, 1.7), 4),
                "topic_tags": dominant_topics,
                "source": "social",
            })
        narratives.append({
            "label": f"{scenario.sector_name} 板块风险偏好",
            "scope": "sector",
            "stance": "bullish" if factors["policy_pressure"] + factors["institutional_conviction"] >= 0 else "bearish",
            "intensity": round(_clamp(abs(factors["policy_pressure"]) * 0.7 + abs(factors["institutional_conviction"]) * 0.55, 0.2, 1.5), 4),
            "topic_tags": topics[:4] or [scenario.sector_name],
            "source": "world_model",
        })
        narratives.sort(key=lambda item: item["intensity"], reverse=True)
        return narratives

    @staticmethod
    def _build_causal_graph(
        scenario: MarketScenario,
        narratives: List[Dict[str, Any]],
        topics: List[str],
        factors: Dict[str, float],
    ) -> Dict[str, Any]:
        nodes = [
            {"id": "stock", "type": "stock", "label": f"{scenario.stock_name}({scenario.ticker})"},
            {"id": "sector", "type": "sector", "label": scenario.sector_name},
            {"id": "retail_mood", "type": "factor", "label": "散户情绪"},
            {"id": "institutional_view", "type": "factor", "label": "机构预期"},
            {"id": "policy_signal", "type": "factor", "label": "政策/宏观信号"},
            {"id": "liquidity", "type": "factor", "label": "流动性温度"},
            {"id": "tape", "type": "factor", "label": "价格带"},
        ]
        for index, narrative in enumerate(narratives[:4], start=1):
            nodes.append({
                "id": f"narrative_{index}",
                "type": "narrative",
                "label": narrative["label"],
                "intensity": narrative["intensity"],
            })
        edges = [
            {"from": "policy_signal", "to": "sector", "weight": round(factors["policy_pressure"], 4)},
            {"from": "sector", "to": "stock", "weight": round(factors["sector_heat"], 4)},
            {"from": "retail_mood", "to": "tape", "weight": round(factors["retail_herding"], 4)},
            {"from": "institutional_view", "to": "stock", "weight": round(factors["institutional_conviction"], 4)},
            {"from": "liquidity", "to": "tape", "weight": round(factors["liquidity_temperature"] - 1, 4)},
        ]
        for index, narrative in enumerate(narratives[:4], start=1):
            edges.append({
                "from": f"narrative_{index}",
                "to": "retail_mood" if narrative["source"] in {"xueqiu", "social"} else "institutional_view",
                "weight": narrative["intensity"] * (1 if narrative["stance"] == "bullish" else -1),
            })
        return {"nodes": nodes, "edges": edges, "topics": topics[:8]}

    @staticmethod
    def _build_tick_blueprint(total_ticks, narratives, factors):
        # Cycle state is inferred from observed conditions and completed rounds.
        return [{
            "name": "adaptive_market", "start_tick": 0, "end_tick": total_ticks,
            "news_multiplier": 1.0, "herding_multiplier": 1.0,
            "institutional_multiplier": 1.0, "value_multiplier": 1.0,
            "liquidity_shift": 0.0, "momentum_shift": 0.0,
            "dominant_narrative": narratives[0]["label"] if narratives else "市场主线",
        }]

    @staticmethod
    def _build_archetype_biases(factors: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        return {
            "fomo_momentum": {
                "world_alignment": round(_clamp(factors["retail_herding"] * 0.8 + factors["tape_momentum_seed"] * 0.6, -1.2, 1.4), 4),
                "activation_boost": round(_clamp((factors["liquidity_temperature"] - 1) * 0.35 + factors["narrative_temperature"] * 0.18, -0.2, 0.45), 4),
            },
            "macro_news": {
                "world_alignment": round(_clamp(factors["policy_pressure"] * 0.95 + factors["sector_heat"] * 0.4, -1.3, 1.4), 4),
                "activation_boost": round(_clamp(abs(factors["policy_pressure"]) * 0.22 + abs(factors["sector_heat"]) * 0.1, 0.0, 0.4), 4),
            },
            "fundamental": {
                "world_alignment": round(_clamp(factors["institutional_conviction"] * 0.7 - factors["valuation_temperature"] * 0.45, -1.3, 1.2), 4),
                "activation_boost": round(_clamp(abs(factors["institutional_conviction"]) * 0.18 + factors["downside_risk"] * 0.08, 0.0, 0.35), 4),
            },
            "mean_reversion": {
                "world_alignment": round(_clamp(factors["downside_risk"] * 0.55 - factors["tape_momentum_seed"] * 0.3, -1.0, 1.1), 4),
                "activation_boost": round(_clamp(factors["valuation_temperature"] * 0.1 + factors["downside_risk"] * 0.18, 0.0, 0.35), 4),
            },
            "passive_retail": {
                "world_alignment": round(_clamp(factors["institutional_conviction"] * 0.25 + factors["retail_herding"] * 0.2, -0.6, 0.8), 4),
                "activation_boost": round(_clamp((factors["liquidity_temperature"] - 1) * 0.12, -0.05, 0.18), 4),
            },
        }

    @staticmethod
    def _dominant_style(policy_pressure: float, retail_herding: float, institutional_conviction: float, valuation_temperature: float) -> str:
        if retail_herding > 0.55 and valuation_temperature > 0.35:
            return "crowd_chasing"
        if institutional_conviction > 0.45 and policy_pressure > 0.25:
            return "policy_trend"
        if institutional_conviction < -0.25 and policy_pressure < -0.2:
            return "risk_off"
        return "balanced_rotation"

