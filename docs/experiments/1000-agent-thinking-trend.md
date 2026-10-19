# 1,000-agent belief trend smoke test

## Setup

- 1,000 synthetic trader profiles, identical cash and holdings across scenarios.
- Five trading days, 240 rounds, fixed random seed 42, starting price 100.
- Synthetic stock news and discussion sentiment: +0.6, 0, or -0.6.
- Market regime fixed at neutral; no live scraping or LLM calls.
- A positive scenario without peer links tests whether social observations matter.
- Repeating the positive scenario tests deterministic replay.
- Synthetic forecast boundary: 2026-03-10 15:00 Asia/Shanghai. No historical
  forecast accuracy is being evaluated.

## Measured population beliefs

Belief is an internal model score in [-1, 1], not a probability. A score above
0.1 is classified as bullish; below -0.1 as bearish for this experiment.

| Scenario | Initial mean | Day 1 | Day 3 | Day 5 | Final price |
| --- | ---: | ---: | ---: | ---: | ---: |
| Positive | 0.400888 | 0.263682 | 0.032343 | 0.001573 | 108.7643 |
| Neutral | 0.000000 | -0.000209 | 0.000071 | -0.000107 | 100.8470 |
| Negative | -0.400888 | -0.273107 | -0.042712 | -0.003122 | 93.6396 |
| Positive, no peers | 0.400888 | 0.238168 | 0.026507 | 0.001144 | 108.8352 |

The positive scenario retained 861 bullish agents on day two, versus 736 without
peer links. Its day-two mean belief was 0.137019, versus 0.120337 without peers.
This verifies that peers affect persistence rather than merely appearing in logs.
Peer influence did not increase the final price in this example; the price and
belief relationship is mediated by portfolios and decision policies.

## Execution checks

- Positive, neutral and negative runs recorded 33,253, 30,164 and 27,063 decisions.
- Every agent accumulated observations and saved memory in each run.
- Positive replay matched its checkpoint statistics and action counts exactly.
- All final cash balances and holdings were nonnegative.
- Positive, neutral and negative final mean beliefs were ordered accordingly.
- Four measured scenarios plus the replay completed in 11.85 seconds on this host.

## Interpretation and limits

The implementation can simulate an evolving population belief trend and its
relationship with trading under its rules. It currently uses deterministic ABM
policies, not 1,000 independent LLM reasoning agents.

The strong uniform seed made all agents initially share the same belief sign.
Consequently, this experiment does not establish realistic initial disagreement.
The positive scenario also reached the model's first-day upper price boundary.
One synthetic stock and one seed do not validate real A-share sentiment, price
forecast accuracy, demographic calibration or robust emergent intelligence.

## Reproduce

From `backend/`:

```bash
python3 scripts/check_thinking_trend.py --agents 1000 --output /tmp/leek-1000-thinking-trend.json
```

The JSON includes daily beliefs by strategy, decision counts, peer observations,
phase counts and checks. Only execution time should differ on identical inputs.
