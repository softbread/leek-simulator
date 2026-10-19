# Market environment and MiroFish adapter

## Modules

Market-specific business settings live in `backend/markets/cn_equity` and
`backend/markets/us_equity`, selected by `MarketScenario.market`. The shared engine
consumes their session calendar, currency, price-limit and trader-policy settings.
US ingestion is in `app/services/market/us_seeds.py`; English social normalization
is framework independent under `markets/us_equity/semantics.py`.

The simulation domain is `backend/market_sim`. It imports only Python's standard
library and runs without Flask, Playwright, Zep or OASIS.

| Module | Responsibility |
| --- | --- |
| `types.py` | Scenario, seeds, trader profiles, world and tick records |
| `world.py` | Seed normalization into shocks, narratives and world factors |
| `population.py` | Reproducible trader population |
| `memory.py` | Peer observations, episodes and collective feedback |
| `sentiment.py` | Timestamped current mood, data cutoff, price/volume seeds and provenance |
| `dynamics.py` | Capital capacity, profit/loss feedback, overnight impulse and state-based cycle inference |
| `traders.py` | Trader lifecycle and replaceable decision policies |
| `engine.py` | Activation, rounds, price impact and world commits |
| `environment.py` | Reset, observe, step and complete runs |
| `results.py` | Pure metrics and event attribution |
| `adapters/mirofish.py` | Host configuration mapping and action export |

Application integrations live in `backend/app/services/market`: `seeds.py` owns
network/browser ingestion, `analysis.py` owns optional LLM reporting, and `runs.py`
owns persistence and background execution. Existing HTTP endpoints use this layer.
The old `market_simulation.py` and `market_world.py` remain compatibility imports.

## MiroFish host contract

Upstream MiroFish's inspected runner constructs Twitter and Reddit environments
directly; it does not expose a general environment plugin registry. This adapter
provides an explicit Python/subprocess integration point. Installing this repo
does not automatically register a third platform in an upstream MiroFish checkout.

From the `backend` directory, a host can run:

```bash
python -m market_sim examples/market_mirofish.json --output /tmp/market-run.json
```

Or embed it:

```python
import json
from market_sim.adapters import MiroFishMarketAdapter

config = json.load(open("examples/market_mirofish.json", encoding="utf-8"))
market = MiroFishMarketAdapter.from_config(config)
first_round = market.step()
ticks, summary = market.run()  # Completes the remaining rounds.
artifacts = market.export()
market.reset()  # Recreates profiles, memories, peer network and RNG from inputs.
```

Configuration accepts:

- `market_scenario`: existing scenario fields, including horizon and seed.
- `market_scenario.market_snapshot`: optional `as_of` and timestamped `recent_prices`.
- `seed_inputs`: normalized `news_items`, `sentiment_signals`, `upload_texts`.
- `source_health`: source provenance supplied by the host.
- `time_config.minutes_per_round`: must be 5 when provided.
- `agent_configs`: maps `agent_id`, `activity_level` and `influence_weight`.

Agent IDs are the generated market IDs (1 through agent count). The horizon comes
from `market_scenario.horizon_days`; upstream social active hours, scheduled posts
and platform actions are not mapped into market events by this adapter.

`from_prepared(prepared_context)` accepts the existing application's persisted
world, population and shocks directly, without refetching or rebuilding seeds.
The web application executes through this same adapter.

Exports include the timeline, final world, agent memory and action envelopes:
`platform=market`, one-based `round_num`, `agent_id`, `agent_name`, `action_type`
(`BUY`, `SELL`, `HOLD`) and `action_args`. These are market actions, not OASIS
ActionType enum values. A host consuming OASIS actions must route them explicitly
to this market environment. The existing web app persists its original artifacts.

## Trader lifecycle

Each activated trader calls `observe -> decide -> act`. When all trades and the
round price have been resolved, `remember` commits episodes and public messages.
This keeps peer observations on the previous round's state.

`TraderPolicy.decide(profile, observation)` returns a finite directional score
bounded to [-2.8, 2.8]. Policies read inputs without mutating profiles or the world;
`TraderAgent.act` owns portfolio changes. Observations include price, valuation
gap, drawdown, news, sentiment, momentum, world factors and personal memory.

A host may inject policies for selected traders, retaining ABM defaults for others:

```python
class HoldPolicy:
    def decide(self, profile, observation):
        return 0.0

market = MiroFishMarketAdapter.from_config(
    config,
    policy_factory=lambda profile: HoldPolicy() if profile.agent_id == 1 else None,
)
```

An LLM-backed implementation can implement the same policy interface; no LLM
trader implementation or per-tick API calls are added by this refactor.
Policy factories must return fresh state on reset for reproducible custom policies.
`observe(agent_id)` returns a copy so host inspection cannot change live memory.
Reset is an in-memory restart; cross-process checkpoint recovery is not included.

## Verification

`uv run pytest tests` covers the existing HTTP lifecycle, a pre-refactor behavior
digest, step/reset replay, mixed policies, adapter configuration, export contracts,
invalid decisions and imports with site packages disabled.
