"""Explicit bridge from MiroFish-style configuration to a market environment.

This is an embeddable runner adapter, not an upstream plugin registration or an
OASIS ActionType extension. It has no dependency on either host framework.
"""

import math
from copy import deepcopy

from ..environment import MarketEnvironment
from ..population import PopulationBuilder
from ..types import AgentProfile, MarketScenario, MarketShock, NewsItem, SentimentSignal
from ..world import ShockBuilder, WorldStateBuilder


class MiroFishMarketAdapter:
    def __init__(self, environment):
        self.environment = environment

    @classmethod
    def from_prepared(cls, prepared, policy_factory=None):
        scenario = MarketScenario.from_dict(prepared["scenario"])
        shocks = [MarketShock(shock_type=item["type"], **{
            key: value for key, value in item.items() if key != "type"
        }) for item in prepared.get("market_shocks", [])]
        return cls(MarketEnvironment(
            scenario, [AgentProfile(**item) for item in prepared["population"]],
            shocks, [SentimentSignal(**item) for item in prepared.get("sentiment_signals", [])],
            prepared.get("world_state", {}), policy_factory,
        ))

    @classmethod
    def from_config(cls, config, policy_factory=None):
        """Accept a market_scenario plus normalized seeds and upstream agent configs."""
        if config.get("time_config", {}).get("minutes_per_round", 5) != 5:
            raise ValueError("Market rounds require minutes_per_round=5")
        scenario = MarketScenario.from_dict(config["market_scenario"])
        seeds = config.get("seed_inputs", scenario.seed_inputs)
        news = [] if scenario.market == "us_equity" else [NewsItem(**item) for item in seeds.get("news_items", [])]
        signals = [SentimentSignal(**item) for item in seeds.get("sentiment_signals", [])]
        if scenario.market == "us_equity":
            from markets.us_equity.semantics import social_signals, normalize_news
            news = [normalize_news(item, scenario) for item in seeds.get("news_items", [])]
            signals.extend(social_signals(seeds.get("social_posts", []), scenario))
        uploads = seeds.get("upload_texts", [])
        world = WorldStateBuilder.build(scenario, news, signals, uploads,
                                        config.get("source_health", {})).to_dict()
        agents = PopulationBuilder.build_population(scenario, world)
        by_id = {agent.agent_id: agent for agent in agents}
        for entry in config.get("agent_configs", []):
            agent = by_id.get(entry["agent_id"])
            if agent is None:
                raise ValueError(f"Unknown market agent: {entry['agent_id']}")
            for field, target, low, high in (
                ("activity_level", "trade_frequency", 0.0, 1.0),
                ("influence_weight", "influence_weight", 0.0, float("inf")),
            ):
                if field in entry:
                    value = float(entry[field])
                    if not math.isfinite(value) or not low <= value <= high:
                        raise ValueError(f"Invalid {field}")
                    setattr(agent, target, value)
        news = [NewsItem(**item) for item in world["seed_inputs"]["news_items"]]
        signals = [SentimentSignal(**item) for item in world["seed_inputs"]["sentiment_signals"]]
        shocks = ShockBuilder.build(scenario, news, uploads)
        return cls(MarketEnvironment(scenario, agents, shocks, signals, world, policy_factory))

    @property
    def world(self):
        return self.environment.world

    def reset(self):
        return self.environment.reset()

    def step(self):
        return self.environment.step().to_dict()

    def observe(self, agent_id=None):
        return self.environment.observe(agent_id)

    def run(self, progress_callback=None):
        return self.environment.run(progress_callback)

    def export(self):
        """Return serializable timeline, memory and MiroFish-style action envelopes."""
        return deepcopy({
            "platform": "market", "completed": self.environment.done,
            "timeline": self.world.timeline, "agents": self.world.agent_states(),
            "world_state": self.world.snapshot(),
            "summary": self.environment.engine.summary,
            "actions": [{
                "platform": "market", "round_num": item["tick_index"] + 1,
                "agent_id": item["agent_id"], "agent_name": item["agent_name"],
                "action_type": item["action"].upper(),
                "action_args": {"quantity": item["signed_quantity"], "price": item["price"],
                                "narrative": item["world_narrative"],
                                "decision_context": item["decision_context"]},
            } for item in self.world.ledger],
        })
