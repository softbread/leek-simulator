# MiroFish upstream comparison

Reviewed on 2026-10-19 against upstream `main` at
[`7657031ac01184afe2cb220f5ee3545573b5e843`](https://github.com/666ghj/MiroFish/commit/7657031ac01184afe2cb220f5ee3545573b5e843)
(commit date 2026-10-02). The source was cloned separately; this is a selective
market adaptation, not an upstream merge.

## Patterns inspected and adapted

| Upstream source | Market adaptation |
| --- | --- |
| `backend/app/services/simulation_config_generator.py`: agent activity, stance, influence, initial posts | Existing strategy/activity profiles now observe persistent beliefs and influence-weighted peer signals; collected news is available from tick zero. |
| `backend/scripts/run_parallel_simulation.py`: round activation and social actions | Market rounds retain every activated buy/sell/hold decision. Peers observe the previous round, avoiding within-round ordering effects. |
| `backend/app/services/zep_graph_memory_updater.py`: timestamped activities written to memory | Each agent retains its latest 24 decision episodes; a complete run action ledger and world timeline preserve the full history. |
| `backend/app/services/report_agent.py`: retrieve evidence before explaining outcomes | Analyst inputs include measured strategy contributions, social dynamics and sampled world history. The UI exposes saved trader memories. |

## Runtime behavior

`news / discussions / uploads / scenario -> world_state -> population -> rounds`

Each round observes the current world and prior peer messages, updates agent
beliefs, executes the ABM decisions, then commits the round together. Weighted
public beliefs and price returns update feedback for the next round. Holding
exposure and returns accumulate experience even when an agent is inactive.
The existing world phase blueprint remains a prior; runtime feedback modifies it.

Artifacts per run:

- `world_state.json`: immutable seed world for this run.
- `world_final.json`: seed world plus final runtime feedback.
- `world_timeline.json`: per-tick beliefs, feedback and activity.
- `agent_states.json`: final portfolios, memories and deterministic peer network.
- `action_ledger.json`: all activated decisions, including scores and observations.

Rebuilding the world clears downstream artifacts; completed starts are idempotent.
Operations on a run are serialized within the backend process. Multi-worker job
coordination and restart checkpoints are not implemented.

## Boundaries

This uses deterministic rules for trader cognition, not upstream OASIS LLM actions
or Zep storage. Agent memory is retained within a run and saved for inspection;
it is not automatically carried into another scenario. The peer network is
synthetic and does not claim to reconstruct actual Xueqiu relationships.

Starting price remains user supplied. Historical price/volume ingestion,
through manual timestamped inputs is supported; automatic history fetching,
calibration, forecast ensembles and predictive validation remain separate work.
An individual generated path is a simulation scenario, not a calibrated forecast.
