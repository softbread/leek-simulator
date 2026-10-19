"""Small controlled experiment for population beliefs; no LLM or live scraping."""

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from market_sim.adapters import MiroFishMarketAdapter
from market_sim.population import PopulationBuilder
from market_sim.types import MarketScenario, NewsItem, SentimentSignal
from market_sim.world import ShockBuilder, WorldStateBuilder


def measure(adapter, label):
    def checkpoint(name):
        memory = adapter.world.memories
        beliefs = [item["belief"] for item in memory.values()]
        groups = defaultdict(list)
        for key, agent in adapter.world.agents.items():
            groups[agent.archetype].append(memory[key]["belief"])
        return {
            "checkpoint": name, "price": adapter.observe()["price"],
            "mean_belief": round(sum(beliefs) / len(beliefs), 6),
            "bullish_agents": sum(value > 0.1 for value in beliefs),
            "bearish_agents": sum(value < -0.1 for value in beliefs),
            "neutral_agents": sum(-0.1 <= value <= 0.1 for value in beliefs),
            "cohort_beliefs": {key: round(sum(values) / len(values), 6) for key, values in groups.items()},
        }
    rows = [checkpoint("initial")]
    while not adapter.environment.done:
        adapter.step()
        if len(adapter.environment.ticks) % 48 == 0:
            rows.append(checkpoint(f"day_{len(adapter.environment.ticks) // 48}"))
    ledger = adapter.world.ledger
    return {
        "label": label, "checkpoints": rows, "decisions": len(ledger),
        "actions": dict(Counter(item["action"] for item in ledger)),
        "agents_with_memory": sum(item["observations"] > 0 for item in adapter.world.memories.values()),
        "decisions_observing_peers": sum(item["decision_context"]["observed_peers"] > 0 for item in ledger),
        "valid_portfolios": all(agent.cash >= 0 and agent.holdings >= 0 for agent in adapter.world.agents.values()),
        "phases": dict(Counter(item["cycle_phase"] for item in adapter.world.timeline)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents", type=int, default=1000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    scenario = MarketScenario("SIMULATED", "synthetic_stock", "synthetic_sector", 100,
        "mid", "neutral", 5, agent_count=args.agents, seed=42,
        market_snapshot={"as_of": "2026-03-10T15:00:00+08:00"})
    population = [agent.to_dict() for agent in PopulationBuilder.build_population(scenario)]
    start = time.perf_counter()
    prepared_cases = {}
    for label, score in (("positive", 0.6), ("neutral", 0.0), ("negative", -0.6)):
        news = [NewsItem("synthetic_test", "2026-03-10T14:50:00+08:00", "controlled catalyst", "",
                         score, 1, "ticker", "")]
        signals = [SentimentSignal("synthetic_test", "2026-03-10T14:59:00+08:00",
            "2026-03-10T14:59:00+08:00", "SIMULATED", "synthetic_sector", score, 5, [],
            {"mode": "synthetic_test", "scope": "ticker", "sample_size": 100})]
        world = WorldStateBuilder.build(scenario, news, signals, [], {}).to_dict()
        prepared_cases[label] = {"scenario": scenario.to_dict(), "population": population,
            "world_state": world, "sentiment_signals": [signal.to_dict() for signal in signals],
            "market_shocks": [shock.to_dict() for shock in ShockBuilder.build(scenario, news, [])]}
    results = []
    for label, prepared in prepared_cases.items():
        results.append(measure(MiroFishMarketAdapter.from_prepared(deepcopy(prepared)), label))
    no_peers = MiroFishMarketAdapter.from_prepared(deepcopy(prepared_cases["positive"]))
    no_peers.world.following = {key: [] for key in no_peers.world.following}
    results.append(measure(no_peers, "positive_without_peers"))
    replay = measure(MiroFishMarketAdapter.from_prepared(deepcopy(prepared_cases["positive"])), "positive")
    by_label = {item["label"]: item for item in results}
    final = lambda label: by_label[label]["checkpoints"][-1]["mean_belief"]
    report = {
        "mode": "deterministic_ABM_policies_not_LLM_agents", "agents": args.agents,
        "seed": 42, "trading_days": 5, "rounds_per_run": 240,
        "controls": "Identical initial trader profiles, cash, holdings, macro regime and seed; only stock news/discussion direction changes.",
        "results": results,
        "checks": {
            "positive_replay_identical": replay == by_label["positive"],
            "all_portfolios_valid": all(item["valid_portfolios"] for item in results),
            "final_beliefs_directionally_ordered": final("positive") > final("neutral") > final("negative"),
            "peer_network_changes_outcome": by_label["positive"]["checkpoints"] != by_label["positive_without_peers"]["checkpoints"],
        },
        "elapsed_seconds": round(time.perf_counter() - start, 3),
    }
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
