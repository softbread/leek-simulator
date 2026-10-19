
"""Deterministic social observations and episodic memory for market agents."""

import random
from collections import defaultdict
from copy import deepcopy
from .dynamics import CycleDynamics


def bounded(value, low=-1.0, high=1.0):
    return max(low, min(high, value))


class MarketWorldRuntime:
    """Read prior-round peers, then commit the round together to avoid order bias."""

    def __init__(self, agents, world_state, seed):
        self.state = deepcopy(world_state)
        self.agents = {agent.agent_id: agent for agent in agents}
        self.memories = {agent.agent_id: {
            "belief": bounded(world_state.get("current_sentiment", {}).get("sentiment_score", 0)
                              * (0.5 + agent.herd_sensitivity * 0.25)),
            "experience": 0.0, "observations": 0, "episodes": [],
        } for agent in agents}
        rng = random.Random(seed)
        groups = defaultdict(list)
        for agent in agents:
            groups[agent.archetype].append(agent.agent_id)
        ids = sorted(self.agents)
        self.following = {}
        for agent in agents:
            local = [key for key in groups[agent.archetype] if key != agent.agent_id]
            peers = rng.sample(local, min(3, len(local)))
            others = [key for key in ids if key != agent.agent_id and key not in peers]
            peers += rng.sample(others, min(2, len(others)))
            self.following[agent.agent_id] = peers
        self.messages = {}
        self.feedback = 0.0
        self.timeline = []
        self.ledger = []
        snapshot = world_state.get("current_sentiment")
        self.dynamics = CycleDynamics(agents, snapshot, world_state.get("tape_state", {}).get("price_anchor", 1)) if snapshot else None

    def context(self, base):
        context = dict(base)
        context["retail_herding"] = bounded(base["retail_herding"] + self.feedback * 0.45, -1.8, 1.8)
        context["tape_momentum_bias"] = bounded(base["tape_momentum_bias"] + self.feedback * 0.3, -1.5, 1.5)
        if "stock_sentiment" in base:
            context["stock_sentiment"] = bounded(base["stock_sentiment"] + self.feedback * 0.45)
        if self.dynamics:
            context.update(self.dynamics.observe(context))
        return context

    def observe(self, agent, context, shock, sentiment, momentum):
        memory = self.memories[agent.agent_id]
        peers = [self.messages[key] for key in self.following[agent.agent_id] if key in self.messages]
        weight = sum(item["influence"] for item in peers)
        peer_signal = sum(item["belief"] * item["influence"] for item in peers) / max(weight, 1e-9)
        evidence = bounded(shock * agent.news_sensitivity * 0.25 + sentiment * 0.2
                           + context["policy_pressure"] * 0.15
                           + context["retail_herding"] * 0.15 + momentum * 5)
        belief = bounded(memory["belief"] * 0.65 + evidence * 0.25
                         + peer_signal * agent.herd_sensitivity * 0.1)
        return {"belief": belief, "peer_signal": peer_signal,
                "experience": memory["experience"], "observed_peers": len(peers)}

    def remember(self, agent_id, tick_index, price, action, context):
        memory = self.memories[agent_id]
        belief = action["decision_context"]["belief"]
        memory["belief"] = belief
        memory["observations"] += 1
        episode = {"tick_index": tick_index, "price": price,
                   "action": action["action"], "signed_quantity": action["signed_quantity"],
                   "belief": round(belief, 5), "narrative": context["dominant_narrative"]}
        memory["episodes"] = (memory["episodes"] + [episode])[-24:]

    def commit(self, tick_index, price, tick_return, actions, context, remember=None):
        messages = {}
        for agent_id, agent in self.agents.items():
            memory = self.memories[agent_id]
            position = agent.holdings * price / max(agent.cash + agent.holdings * price, 1)
            memory["experience"] = bounded(memory["experience"] * 0.98
                                            + memory.get("last_position", position) * tick_return * 10)
            memory["last_position"] = position
        for action in actions:
            agent_id = action["agent_id"]
            agent = self.agents[agent_id]
            belief = action["decision_context"]["belief"]
            (remember or self.remember)(agent_id, tick_index, price, action, context)
            messages[agent_id] = {"belief": belief, "influence": agent.influence_weight}
            self.ledger.append({"tick_index": tick_index, "price": price, **action})
        # Public signals last one round, so absent peers do not broadcast forever.
        self.messages = messages
        total_weight = sum(item["influence"] for item in messages.values())
        public_belief = sum(item["belief"] * item["influence"] for item in messages.values()) / max(total_weight, 1e-9)
        self.feedback = bounded(self.feedback * 0.75 + public_belief * 0.2 + tick_return * 2)
        if self.dynamics:
            self.dynamics.commit(price, tick_return, actions, context)
        self.timeline.append({
            "tick_index": tick_index, "price": price,
            "dominant_narrative": context["dominant_narrative"],
            "retail_herding": round(context["retail_herding"], 5),
            "public_belief": round(public_belief, 5), "feedback": round(self.feedback, 5),
            "active_agents": len(actions),
            "market_sentiment": context.get("market_sentiment", 0.0),
            "stock_sentiment": context.get("stock_sentiment", 0.0),
            "sector_sentiment": context.get("sector_sentiment", 0.0),
            "simulated_at": context.get("simulated_at", ""),
            **{key: context[key] for key in ("cycle_phase", "cycle_label", "market_cycle_phase",
                "market_cycle_source", "buying_capacity", "selling_capacity", "profit_effect", "loss_effect",
                "flow_pressure", "cycle_pressure", "participation_change", "overnight_impulse") if key in context},
        })

    def snapshot(self):
        return {**self.state, "runtime": {
            "tick_index": self.timeline[-1]["tick_index"] if self.timeline else -1,
            "feedback": self.feedback, "public_messages": len(self.messages),
            "cycle": {key: self.timeline[-1][key] for key in ("cycle_phase", "buying_capacity", "profit_effect", "loss_effect")
                      if self.timeline and key in self.timeline[-1]},
        }}

    def agent_states(self):
        return [{"profile": agent.to_dict(), "memory": self.memories[key],
                 "following": self.following[key]}
                for key, agent in self.agents.items()]
