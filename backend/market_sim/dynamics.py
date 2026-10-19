"""Descriptive sentiment cycles driven by breadth, participation and inventories."""

from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

from .utils import _clamp


PHASE_LABELS = {
    "rising": "涨潮期", "top_consolidation": "顶部震荡期",
    "falling": "退潮期", "bottom_consolidation": "底部震荡期",
    "undetermined": "证据不足",
}


def classify_phase(pressure, change, buying_capacity=1.0, selling_capacity=1.0):
    if pressure > 0.12:
        return "top_consolidation" if change < -0.08 or buying_capacity < 0.18 else "rising"
    if pressure < -0.12:
        return "bottom_consolidation" if change > 0.08 or selling_capacity < 0.18 else "falling"
    return "undetermined"


def market_cycle(history, market="cn_equity"):
    if not history:
        return {"phase": "undetermined", "label": PHASE_LABELS["undetermined"],
                "source": "missing_breadth", "pressure": 0.0, "change": 0.0}
    def pressure(item):
        breadth = (item["advancers"] - item["decliners"]) / max(item["advancers"] + item["decliners"], 1)
        if market == "us_equity":
            return breadth
        limits = (item["limit_up"] - item["limit_down"]) / max(item["limit_up"] + item["limit_down"], 1)
        promotion = (item.get("promotion_rate", 0.5) - 0.5) * 2
        return _clamp(breadth * 0.5 + limits * 0.35 + promotion * 0.15, -1, 1)
    score = pressure(history[-1])
    change = score - pressure(history[-2]) if len(history) > 1 else 0.0
    phase = classify_phase(score, change)
    return {"phase": phase, "label": PHASE_LABELS[phase], "source": "market_breadth",
            "pressure": round(score, 5), "change": round(change, 5),
            "observations": len(history), "as_of": history[-1]["timestamp"]}


class CycleDynamics:
    """Stock-specific state uses only completed rounds, never future actions."""

    def __init__(self, agents, snapshot, starting_price):
        self.agents = agents
        self.price = starting_price
        self.returns = deque(maxlen=12)
        self.flows = deque(maxlen=12)
        self.participation = deque(maxlen=12)
        self.previous_pressure = None
        self.overnight_impulse = 0.0
        self.last_date = datetime.fromisoformat(snapshot["as_of"]).astimezone(ZoneInfo(snapshot.get("timezone", "Asia/Shanghai"))).date().isoformat()
        self.market = snapshot.get("market_cycle", market_cycle([]))

    def observe(self, context):
        cash = sum(agent.cash for agent in self.agents)
        inventory = sum(agent.holdings * self.price for agent in self.agents)
        buying_capacity = cash / max(cash + inventory, 1)
        selling_capacity = 1 - buying_capacity
        pnl = [((self.price - agent.average_cost) / max(agent.average_cost, 1e-9), agent.holdings * self.price)
               for agent in self.agents if agent.holdings > 0]
        profit = sum(max(0, value) * weight for value, weight in pnl) / max(inventory, 1)
        loss = sum(max(0, -value) * weight for value, weight in pnl) / max(inventory, 1)
        profit_effect, loss_effect = min(profit / 0.12, 1), min(loss / 0.12, 1)
        flow = sum(self.flows) / max(len(self.flows), 1)
        momentum = sum(self.returns) / max(len(self.returns), 1)
        pressure = _clamp(context.get("stock_sentiment", 0) * 0.5 + flow * 0.3 + momentum * 20, -1, 1)
        change = pressure - self.previous_pressure if self.previous_pressure is not None else 0
        phase = classify_phase(pressure, change, buying_capacity, selling_capacity)
        current_date = context.get("simulated_at", "").split("T")[0]
        if current_date and current_date != self.last_date:
            self.overnight_impulse = _clamp(pressure * 0.3 + (profit_effect - loss_effect) * 0.2, -0.5, 0.5)
            self.last_date = current_date
        participation_change = (self.participation[-1] - sum(self.participation) / len(self.participation)) if self.participation else 0
        return {
            "cycle_phase": phase, "cycle_label": PHASE_LABELS[phase],
            "market_cycle_phase": self.market["phase"], "market_cycle_source": self.market["source"],
            "buying_capacity": round(buying_capacity, 5), "selling_capacity": round(selling_capacity, 5),
            "profit_effect": round(profit_effect, 5), "loss_effect": round(loss_effect, 5),
            "flow_pressure": round(flow, 5), "cycle_pressure": round(pressure, 5),
            "participation_change": round(participation_change, 5),
            "overnight_impulse": round(self.overnight_impulse, 5),
        }

    def commit(self, price, tick_return, actions, context):
        self.price = price
        self.returns.append(tick_return)
        volume = sum(abs(item["signed_quantity"]) for item in actions)
        self.flows.append(sum(item["signed_quantity"] for item in actions) / max(volume, 1))
        self.participation.append(len(actions) / max(len(self.agents), 1))
        self.previous_pressure = context.get("cycle_pressure", 0)
        self.overnight_impulse *= 0.65
