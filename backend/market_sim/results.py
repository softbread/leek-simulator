"""Pure metrics and event attribution from a completed market path."""
import math
from collections import Counter
from typing import Any, Dict, List
from .types import MarketScenario, SimulationTick
from markets import get_profile

def build_results(
    scenario: MarketScenario,
    prepared: Dict[str, Any],
    ticks: List[SimulationTick],
    engine_summary: Dict[str, Any],
    world_timeline: List[Dict[str, Any]],
) -> Dict[str, Any]:
    series = [tick.to_dict() for tick in ticks]
    prices = [tick.price for tick in ticks] or [scenario.starting_price]
    volumes = [tick.volume for tick in ticks] or [0]
    peak = scenario.starting_price
    max_drawdown = 0.0
    for price in prices:
        peak = max(peak, price)
        drawdown = (peak - price) / max(peak, 1e-6)
        max_drawdown = max(max_drawdown, drawdown)
    returns = [tick.return_pct for tick in ticks]
    realized_vol = math.sqrt(sum(value * value for value in returns) / max(len(returns), 1)) * math.sqrt(get_profile(scenario.market).ticks_per_day * 20) * 100
    total_return = (prices[-1] - scenario.starting_price) / max(scenario.starting_price, 1e-6) * 100
    turnover_ratio = sum(volumes) / max(scenario.agent_count * 400, 1)
    event_markers = extract_event_markers(
        ticks,
        prepared.get("market_shocks", []),
        prepared.get("world_state", {}),
    )
    results = {
        "scenario": scenario.to_dict(),
        "market_profile": get_profile(scenario.market).public(),
        "world_state": prepared.get("world_state", {}),
        "current_sentiment": prepared.get("world_state", {}).get("current_sentiment", {}),
        "world_timeline": world_timeline,
        "cycle_summary": {
            "market": prepared.get("world_state", {}).get("current_sentiment", {}).get("market_cycle", {}),
            "stock_phase_counts": dict(Counter(item.get("cycle_phase", "undetermined") for item in world_timeline)),
            "basis": "heuristic_state_inference_not_a_fixed_schedule",
        },
        "series": series,
        "metrics": {
            "starting_price": round(scenario.starting_price, 4),
            "ending_price": round(prices[-1], 4),
            "total_return_pct": round(total_return, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "realized_volatility_pct": round(realized_vol, 2),
            "turnover_ratio": round(turnover_ratio, 2),
            "average_volume": round(sum(volumes) / max(len(volumes), 1), 2),
        },
        "population_summary": prepared.get("population_summary", {}),
        "news_items": prepared.get("news_items", []),
        "xueqiu_summary": {
            "average_sentiment": round(sum(signal["sentiment_score"] for signal in prepared.get("sentiment_signals", [])) / max(len(prepared.get("sentiment_signals", [])), 1), 4),
            "average_buzz": round(sum(signal["buzz_score"] for signal in prepared.get("sentiment_signals", [])) / max(len(prepared.get("sentiment_signals", [])), 1), 4),
            "signals": prepared.get("sentiment_signals", []),
        },
        "event_markers": event_markers,
        "engine_summary": engine_summary,
    }
    results["social_summary"] = results["xueqiu_summary"]
    return results

def extract_event_markers(
    ticks: List[SimulationTick],
    shocks: List[Dict[str, Any]],
    world_state: Dict[str, Any],
) -> List[Dict[str, Any]]:
    markers: List[Dict[str, Any]] = []
    for shock in shocks[:10]:
        tick_index = min(max(0, shock.get("start_tick", 0)), max(len(ticks) - 1, 0))
        price = ticks[tick_index].price if ticks else 0
        markers.append(
            {
                "tick_index": tick_index,
                "label": shock.get("headline", "市场事件"),
                "impact_score": round(shock.get("direction", 0) * shock.get("strength", 0), 4),
                "price": price,
                "scope": shock.get("affected_scope", "ticker"),
            }
        )
    largest_moves = sorted(ticks, key=lambda item: abs(item.return_pct), reverse=True)[:4]
    for tick in largest_moves:
        markers.append(
            {
                "tick_index": tick.tick_index,
                "label": "盘中大幅波动",
                "impact_score": round(tick.return_pct, 4),
                "price": tick.price,
                "scope": "ticker",
            }
        )
    for segment in world_state.get("tick_blueprint", [])[:4]:
        tick_index = min(max(0, segment.get("start_tick", 0)), max(len(ticks) - 1, 0))
        price = ticks[tick_index].price if ticks else 0
        markers.append(
            {
                "tick_index": tick_index,
                "label": f"世界状态切换: {segment.get('dominant_narrative', segment.get('name', '市场主线'))}",
                "impact_score": round(segment.get("herding_multiplier", 1.0) - segment.get("value_multiplier", 1.0), 4),
                "price": price,
                "scope": "world",
            }
        )
    markers.sort(key=lambda item: (item["tick_index"], -abs(item["impact_score"])))
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for marker in markers:
        key = (marker["tick_index"], marker["label"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(marker)
    return deduped[:12]
