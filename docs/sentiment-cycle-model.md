# Sentiment cycle model

Reference: [股票高手进阶：超短如何玩转市场情绪周期](https://xueqiu.com/9191166721/176242431),
投机者流火, 2021-04-03. The article discusses capital participation, four recurring
sentiment phases, overnight emotion and breadth observations. We use these as
modelling hypotheses rather than a validated forecasting method or trading rules.

## Implemented mechanics

- Available buying capacity: simulated cohort cash / (cash + marked stock inventory).
- Selling capacity: the complementary stock inventory fraction.
- Profit/loss effects: inventory-weighted unrealized returns against average cost,
  scaled by a model parameter and bounded to [0, 1].
- Flow pressure: signed order quantities / absolute quantities, averaged over the
  latest 12 completed rounds. These are simulated requests, not exchange fund flows.
- Participation change: latest active share relative to recent mean activity.
- Overnight impulse: the prior state and profit/loss effects can amplify opening
  decisions; the impulse fades within the session.

FOMO traders' scores respond to available cash and simulated gain/loss experience.
Fundamental traders can take profit; contrarians can respond to stabilising weak
conditions. Discussion buzz amplifies its observed direction instead of always
adding bullish pressure. All changes affect agent decisions before price impact.

The classifier describes four states: rising, top consolidation, falling and
bottom consolidation. It uses pressure, change and inventory capacity. Weak
evidence stays `undetermined`; no complete cycle or reversal is guaranteed.
The previous pre-scheduled four-segment world blueprint has been replaced with
one neutral segment. Trading state now supplies the phase, independently of time.

## Independent market breadth

Optional `market_snapshot.market_breadth` records contain timestamp, advancers,
decliners, limit-up count, limit-down count, optional promotion rate (0-1), and
source. Use consistent coverage and sampling between records.

The broad-market pressure heuristic weights advance/decline balance at 50%,
limit-up/down balance at 35%, and promotion rate at 15%. If promotion rate is not
provided it contributes zero. It supplements broad-market news/discussions, not
the individual stock channel. Without breadth, broad-market phase is unknown;
the stock population is never used as a replacement for all-market breadth.

Input breadth is historical context, not generated future measurements. With no
new market-wide observations, its cycle label remains a starting prior. Individual
stock phases evolve from actual simulated rounds and can differ from that prior.

## Outputs and limits

World timelines expose phase, capacity, flow, participation change, profit/loss
effects and overnight impulse. Decision contexts record the state that affected a
trader; results summarize the time spent in each phase.

These thresholds, weights and lookback lengths are uncalibrated model parameters.
There is no forced 10-20-day cycle. News still expires after its independently
configured lifetime (default 72 hours), while positions and social feedback remain.
The cohort is a single-stock sample with a synthetic liquidity counterparty, not a
closed reconstruction of all A-share capital or a full order book. Multi-stock
leader rotation and exchange limit-order queuing are outside this implementation.
