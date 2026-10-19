"""Replaceable trader policies and the observe/decide/act/remember lifecycle."""

import math
from typing import Any, Dict, Protocol

from .types import AgentProfile
from .utils import _clamp


class TraderPolicy(Protocol):
    def decide(self, agent: AgentProfile, observation: Dict[str, Any]) -> float:
        """Return a finite directional score; execution owns cash and holdings."""
        ...


class ABMTraderPolicy:
    def __init__(self, archetype_biases=None):
        self.archetype_biases = archetype_biases or {}

    def decide(self, agent, observation):
        score = self._decision_score(agent=agent, **observation["signals"])
        memory = observation["memory"]
        context = observation["signals"]["world_context"]
        if "buying_capacity" in context:
            capacity = context["buying_capacity"]
            if agent.archetype == "fomo_momentum":
                # Positive mood loses buying power as available cash is consumed.
                score = score * (0.5 + capacity) + context["profit_effect"] * 0.25 - context["loss_effect"] * 0.55
                score -= max(0, 0.3 - capacity) * 1.5
            elif agent.archetype == "fundamental":
                score -= context["profit_effect"] * (1 - capacity) * 0.25
            elif agent.archetype == "mean_reversion" and context["cycle_phase"] == "bottom_consolidation":
                score += context["loss_effect"] * 0.2
            if agent.archetype in {"fomo_momentum", "macro_news"}:
                score += context["overnight_impulse"] * agent.herd_sensitivity
        return _clamp(score + memory["belief"] * 0.3
                      + memory["peer_signal"] * agent.herd_sensitivity * 0.15
                      + memory["experience"] * 0.1, -2.8, 2.8)

    def _decision_score(
        self,
        agent: AgentProfile,
        momentum: float,
        valuation_gap: float,
        shock_bias: float,
        sector_bias: float,
        crowd_sentiment: float,
        crowd_buzz: float,
        drawdown: float,
        world_context: Dict[str, Any],
    ) -> float:
        news_component = shock_bias * agent.news_sensitivity
        herd_component = crowd_sentiment * agent.herd_sensitivity + min(crowd_buzz / 10, 1.8) * 0.08
        if "buying_capacity" in world_context:
            herd_component = crowd_sentiment * agent.herd_sensitivity
            herd_component += (1 if crowd_sentiment > 0 else -1 if crowd_sentiment < 0 else 0) * min(crowd_buzz / 10, 1.8) * 0.08
        momentum_component = momentum * agent.momentum_bias
        value_component = valuation_gap * agent.fundamental_bias if world_context.get("fundamentals_enabled", True) else 0.0
        archetype_world_bias = float(self.archetype_biases.get(agent.archetype, {}).get("world_alignment", 0.0))
        world_news = world_context["policy_pressure"] * agent.news_sensitivity * 0.55
        world_herd = world_context["retail_herding"] * agent.herd_sensitivity * 0.7
        world_institutional = world_context["institutional_conviction"] * 0.55
        world_value = -world_context["valuation_temperature"] * 0.4 if world_context.get("fundamentals_enabled", True) else 0.0
        world_tape = world_context["tape_momentum_bias"] * 0.45
        score = 0.0
        if agent.archetype == "fomo_momentum":
            score = momentum_component * 1.8 + herd_component * 1.5 + news_component * 0.85 + sector_bias * 0.4 + world_herd * 1.1 + world_tape * 0.9
        elif agent.archetype == "macro_news":
            score = news_component * 1.65 + sector_bias * 0.95 + herd_component * 0.55 + momentum_component * 0.4 + world_news * 1.15 + world_institutional * 0.45
        elif agent.archetype == "fundamental":
            score = value_component * 1.75 + news_component * 0.55 - herd_component * 0.25 + world_institutional * 0.7 + world_value * 0.9
        elif agent.archetype == "mean_reversion":
            score = -momentum_component * 1.15 + drawdown * (0.7 + agent.dip_buy_tendency) + value_component * 0.9 + news_component * 0.2 - world_tape * 0.45 + world_value * 0.55
        elif agent.archetype == "social_contrarian":
            score = -herd_component * 0.8 - momentum_component * 0.6 + news_component * 0.3
        else:
            score = value_component * 0.75 + news_component * 0.35 + herd_component * 0.2 + world_institutional * 0.25
        score += archetype_world_bias * 0.35
        if drawdown > agent.stop_loss_tendency and agent.holdings > 0:
            score -= drawdown * (1.1 if agent.risk_appetite == "low" else 0.85)
        score -= world_context["downside_risk"] * (0.15 if agent.archetype == "mean_reversion" else 0.28)
        return _clamp(score, -2.8, 2.8)


class TraderAgent:
    def __init__(self, profile, world, policy):
        self.profile = profile
        self.world = world
        self.policy = policy

    def observe(self, price, recent_peak, **signals):
        memory = self.world.observe(self.profile, signals["world_context"],
                                    signals["shock_bias"], signals["crowd_sentiment"], signals["momentum"])
        return {"price": price, "memory": memory, "signals": {
            **signals,
            "valuation_gap": (self.profile.fundamental_anchor - price) / max(price, 1e-6) if signals["world_context"].get("fundamentals_enabled", True) else 0.0,
            "drawdown": (recent_peak - price) / max(recent_peak, 1e-6),
        }}

    def decide(self, observation):
        score = float(self.policy.decide(self.profile, observation))
        if not math.isfinite(score):
            raise ValueError("Trader policy must return a finite decision score")
        return _clamp(score, -2.8, 2.8)

    def act(self, score, observation):
        agent = self.profile
        price = observation["price"]
        threshold = 0.16 + (0.08 if agent.risk_appetite == "low" else 0.0)
        action = "hold"
        signed_quantity = 0
        cash_fraction = _clamp(agent.conviction * 0.18 + abs(score) * 0.15, 0.05, 0.42)
        if score > threshold and agent.cash > price * observation["signals"]["world_context"].get("minimum_cash_shares", 100):
            budget = agent.cash * cash_fraction
            quantity = max(0, int(budget / max(price, 1)))
            if quantity > 0:
                cost = quantity * price
                previous_value = agent.average_cost * agent.holdings
                agent.cash -= cost
                agent.holdings += quantity
                agent.average_cost = (previous_value + cost) / max(agent.holdings, 1)
                action = "buy"
                signed_quantity = quantity
        elif score < -threshold and agent.holdings > 0:
            quantity = max(0, int(agent.holdings * _clamp(abs(score) * 0.55, 0.08, 0.45)))
            if quantity > 0:
                agent.cash += quantity * price
                agent.holdings -= quantity
                action = "sell"
                signed_quantity = -quantity
        agent.conviction = _clamp(agent.conviction * 0.992 + score * 0.028, 0.08, 1.15)
        return {
            "agent_id": agent.agent_id, "agent_name": agent.display_name,
            "archetype": agent.archetype, "action": action, "signed_quantity": signed_quantity,
            "cash": round(agent.cash, 2), "holdings": agent.holdings,
            "world_narrative": observation["signals"]["world_context"]["dominant_narrative"],
            "decision_context": {**observation["memory"], "score": round(score, 5),
                **{key: observation["signals"]["world_context"][key] for key in (
                    "cycle_phase", "market_cycle_phase", "buying_capacity", "profit_effect", "loss_effect", "overnight_impulse"
                ) if key in observation["signals"]["world_context"]}},
        }

    def remember(self, tick_index, price, action, context):
        self.world.remember(self.profile.agent_id, tick_index, price, action, context)
