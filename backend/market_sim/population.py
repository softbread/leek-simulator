"""Deterministic trader population generation."""
import random
from collections import defaultdict
from typing import Any, Dict, List, Optional
from .utils import _clamp, _normalize_weights, _weighted_choice
from .types import MarketScenario, AgentProfile
from markets import get_profile

class PopulationBuilder:
    ARCHETYPE_WEIGHTS = {
        "fomo_momentum": 0.30,
        "macro_news": 0.25,
        "fundamental": 0.20,
        "mean_reversion": 0.15,
        "passive_retail": 0.10,
    }
    AGE_WEIGHTS = {
        "18-24": 0.12,
        "25-34": 0.28,
        "35-44": 0.30,
        "45-54": 0.20,
        "55+": 0.10,
    }
    RISK_WEIGHTS = {"high": 0.30, "medium": 0.50, "low": 0.20}
    WEALTH_WEIGHTS = {
        "starter": 0.35,
        "accumulator": 0.40,
        "mid_wealth": 0.18,
        "high_wealth": 0.07,
    }
    CASH_RANGES = {
        "starter": (20000, 120000),
        "accumulator": (120000, 500000),
        "mid_wealth": (500000, 1500000),
        "high_wealth": (1500000, 5000000),
    }
    HOLDING_FRACTIONS = {
        "starter": (0.0, 0.35),
        "accumulator": (0.1, 0.55),
        "mid_wealth": (0.2, 0.65),
        "high_wealth": (0.25, 0.75),
    }

    @classmethod
    def build_population(cls, scenario: MarketScenario, world_state: Optional[Dict[str, Any]] = None) -> List[AgentProfile]:
        seed = scenario.seed if scenario.seed is not None else sum(ord(char) for char in scenario.ticker) + scenario.agent_count
        rng = random.Random(seed)
        profile = get_profile(scenario.market)
        archetype_weights = profile.archetypes.copy()
        for key, value in scenario.trader_mix_overrides.items():
            if key in archetype_weights:
                archetype_weights[key] = max(0.0, float(value))
        archetype_weights = _normalize_weights(archetype_weights)
        regime_factors = (world_state or {}).get("regime_factors", {})
        archetype_biases = (world_state or {}).get("archetype_biases", {})
        retail_herding = float(regime_factors.get("retail_herding", 0.0))
        institutional_conviction = float(regime_factors.get("institutional_conviction", 0.0))
        downside_risk = float(regime_factors.get("downside_risk", 0.0))

        agents: List[AgentProfile] = []
        for agent_id in range(1, scenario.agent_count + 1):
            archetype = _weighted_choice(rng, archetype_weights)
            age_band = _weighted_choice(rng, profile.age_weights or cls.AGE_WEIGHTS)
            risk_appetite = _weighted_choice(rng, cls.RISK_WEIGHTS)
            wealth_stage = _weighted_choice(rng, cls.WEALTH_WEIGHTS)
            cash_low, cash_high = profile.cash_ranges[wealth_stage]
            cash = rng.uniform(cash_low, cash_high)
            holding_low, holding_high = cls.HOLDING_FRACTIONS[wealth_stage]
            holding_fraction = rng.uniform(holding_low, holding_high)
            holdings = int((cash * holding_fraction) / max(scenario.starting_price, 1))
            cash = max(1000.0, cash - holdings * scenario.starting_price)
            conviction = rng.uniform(0.35, 0.85)
            risk_factor = {"high": 1.0, "medium": 0.75, "low": 0.5}[risk_appetite]
            activation_boost = float(archetype_biases.get(archetype, {}).get("activation_boost", 0.0))
            trade_frequency = _clamp(rng.uniform(0.08, 0.22) * risk_factor + activation_boost * 0.07, 0.03, 0.32)
            stop_loss = _clamp(rng.uniform(0.15, 0.45) * (1.1 if risk_appetite == "low" else 0.85), 0.08, 0.5)
            dip_buy = _clamp(rng.uniform(0.1, 0.55) + (0.08 if archetype == "mean_reversion" else 0.0), 0.05, 0.7)
            news_sensitivity = _clamp(rng.uniform(0.3, 1.0) + (0.3 if archetype == "macro_news" else 0.0) + max(0.0, institutional_conviction) * 0.08, 0.2, 1.5)
            herd_sensitivity = _clamp(rng.uniform(0.15, 1.0) + (0.35 if archetype == "fomo_momentum" else 0.0) + max(0.0, retail_herding) * 0.1, 0.1, 1.6)
            momentum_bias = _clamp(rng.uniform(-0.3, 1.0) + (0.55 if archetype == "fomo_momentum" else 0.0) + retail_herding * 0.08, -0.6, 1.7)
            fundamental_bias = _clamp(rng.uniform(0.1, 1.0) + (0.7 if archetype == "fundamental" else 0.0) + abs(downside_risk) * 0.05, 0.05, 1.85)
            anchor_shift = rng.uniform(-0.18, 0.18)
            if scenario.market_regime == "bullish":
                anchor_shift += 0.03
            elif scenario.market_regime == "bearish":
                anchor_shift -= 0.03
            anchor_shift += institutional_conviction * 0.04
            fundamental_anchor = max(0.5, scenario.starting_price * (1 + anchor_shift))
            if not profile.fundamentals_enabled:
                fundamental_bias = 0.0
                fundamental_anchor = scenario.starting_price
            influence = round(rng.uniform(0.4, 1.6) * (1.15 if wealth_stage in {"mid_wealth", "high_wealth"} else 1.0), 4)
            display_name = f"{age_band}/{archetype}/{wealth_stage}"
            agents.append(
                AgentProfile(
                    agent_id=agent_id,
                    archetype=archetype,
                    age_band=age_band,
                    risk_appetite=risk_appetite,
                    wealth_stage=wealth_stage,
                    cash=round(cash, 2),
                    holdings=holdings,
                    average_cost=round(scenario.starting_price, 4),
                    conviction=round(conviction, 4),
                    trade_frequency=round(trade_frequency, 4),
                    stop_loss_tendency=round(stop_loss, 4),
                    dip_buy_tendency=round(dip_buy, 4),
                    news_sensitivity=round(news_sensitivity, 4),
                    herd_sensitivity=round(herd_sensitivity, 4),
                    momentum_bias=round(momentum_bias, 4),
                    fundamental_bias=round(fundamental_bias, 4),
                    fundamental_anchor=round(fundamental_anchor, 4),
                    influence_weight=influence,
                    display_name=display_name,
                )
            )
        return agents

    @staticmethod
    def summarize_population(agents: List[AgentProfile]) -> Dict[str, Any]:
        def count_by(field_name: str) -> Dict[str, int]:
            counts: Dict[str, int] = defaultdict(int)
            for agent in agents:
                counts[getattr(agent, field_name)] += 1
            return dict(sorted(counts.items(), key=lambda item: item[0]))

        return {
            "agent_count": len(agents),
            "archetypes": count_by("archetype"),
            "age_bands": count_by("age_band"),
            "risk_appetite": count_by("risk_appetite"),
            "wealth_stage": count_by("wealth_stage"),
            "average_cash": round(sum(agent.cash for agent in agents) / max(len(agents), 1), 2),
            "average_holdings": round(sum(agent.holdings for agent in agents) / max(len(agents), 1), 2),
        }

