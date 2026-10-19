"""Reusable market environment with explicit round control."""

import math
from copy import deepcopy

from .engine import PriceImpactEngine


class MarketEnvironment:
    def __init__(self, scenario, agents, shocks=(), sentiment_signals=(), world_state=None,
                 policy_factory=None):
        if not 500 <= scenario.agent_count <= 2000 or len(agents) != scenario.agent_count:
            raise ValueError("Expected 500-2000 agents matching scenario.agent_count")
        if not 1 <= scenario.horizon_days <= 5:
            raise ValueError("Expected 1-5 trading days")
        if not math.isfinite(scenario.starting_price) or scenario.starting_price <= 0:
            raise ValueError("Expected a finite positive starting price")
        if len({agent.agent_id for agent in agents}) != len(agents):
            raise ValueError("Agent IDs must be unique")
        self._inputs = deepcopy((scenario, agents, list(shocks), list(sentiment_signals), world_state or {}))
        self.policy_factory = policy_factory
        self.reset()

    def reset(self):
        scenario, agents, shocks, signals, world = deepcopy(self._inputs)
        self.engine = PriceImpactEngine(scenario, agents, shocks, signals, world,
                                        policy_factory=self.policy_factory)
        self._rounds = self.engine.iter_ticks()
        self.ticks = []
        self.done = False
        return self.observe()

    @property
    def world(self):
        return self.engine.world

    def observe(self, agent_id=None):
        if agent_id is not None:
            if agent_id not in self.world.agents:
                raise ValueError(f"Unknown agent: {agent_id}")
            return deepcopy({"profile": self.world.agents[agent_id].to_dict(),
                             "memory": self.world.memories[agent_id],
                             "following": self.world.following[agent_id]})
        return {"tick_index": len(self.ticks) - 1, "done": self.done,
                "price": self.ticks[-1].price if self.ticks else self.engine.scenario.starting_price,
                "world": deepcopy(self.world.snapshot())}

    def step(self):
        if self.done:
            raise RuntimeError("Simulation completed; reset before stepping again")
        tick = next(self._rounds)
        self.ticks.append(tick)
        self.done = len(self.ticks) == self.engine.total_ticks
        return tick

    def run(self, progress_callback=None):
        while not self.done:
            self.step()
            count = len(self.ticks)
            if progress_callback and (self.done or (count - 1) % 4 == 0):
                progress_callback(count, self.engine.total_ticks, self.ticks[-12:])
        return list(self.ticks), deepcopy(self.engine.summary)
