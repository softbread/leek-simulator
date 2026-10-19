# US equity sentiment simulation

US equities are a separate business module selected with `market="us_equity"`.
Fundamental screening is assumed to happen before ticker selection. The US module
does not calculate valuations or generate fundamental traders. The A-share module
retains its previous behavior and defaults.

## Start from the UI

1. Start the application as described in the README.
2. On the home page choose **US Equities**.
3. Enter your prefiltered ticker, company name, sector and starting USD price.
4. Choose a market keyword, such as `S&P 500`, independently of the ticker.
5. Select `import_only` for reproducible local data, or `live_and_imported` to
   enable available backend connectors as well.
6. Paste your news/social seed object. Review timestamps and source provenance.
7. Build the world, review sentiment and source status, prepare and run.

Changing the market resets the stock inputs and trader mix to prevent accidental
reuse of a Chinese stock or fundamental-agent weighting in the US module.

## Source support

| Source | Current integration |
| --- | --- |
| CNBC | Top News RSS, best effort; missing dates are skipped; stock/sector references are matched separately |
| X | Recent search using `US_X_BEARER_TOKEN`; ticker cashtag, sector and broad-market queries |
| Reddit | OAuth search using `US_REDDIT_ACCESS_TOKEN`; ticker, sector and market searches |
| Bloomberg | Import normalized news or connect your authorized feed through `US_NEWS_FEED_URL` |
| Robinhood Social | Import posts from an available authorized export/source; no claimed public API connector |

Provider errors and missing credentials are recorded in `source_health.providers`.
They do not produce invented social posts or synthetic observed sentiment.
`import_only` performs no data-provider network calls.

Configure optional tokens in the root `.env` using the names in `.env.example`.
The application uses existing access tokens; obtaining access and refreshing expired
tokens remain external setup steps. A configured news feed must return a JSON
object containing `news_items` already relevant to the stock, sector or market.
The optional bearer token is supplied only to that configured feed.

The CNBC general feed does not guarantee coverage of every ticker. X/Reddit
availability depends on your authorized account access and the provider response.
Live requests have not been validated with private credentials by the test suite.

## Imported seed format

The UI accepts an object like this (illustrative data, not a real event):

```json
{
  "news_items": [{
    "source": "bloomberg_import",
    "title": "Illustrative NVDA product launch",
    "summary": "Example of a bullish announcement",
    "published_at": "2026-03-10T15:45:00-04:00",
    "affected_scope": "ticker",
    "url": "",
    "sentiment": 0.6,
    "relevance_score": 0.9
  }],
  "social_posts": [{
    "source": "reddit",
    "scope": "ticker",
    "text": "$NVDA bullish breakout",
    "published_at": "2026-03-10T15:50:00-04:00"
  }]
}
```

Use `market`, `sector` or `ticker` scopes consistently. News needs a source,
title, publication time and scope. Explicit news sentiment (-1 to 1) and relevance
(0 to 1) are optional; absent sentiment uses the English heuristic. Supply actual
timestamps with UTC offsets. Missing or expired observations cannot be made
current by importing them again.

Social posts are normalized and exact-content duplicates are removed across
providers within each scope. Ticker posts must mention the ticker or company;
short ambiguous symbols require a cashtag unless the company name matches.
Negation is handled for a small English lexicon, while explicit `/s` sarcasm is
neutralized. This is not full semantic understanding, robust bot detection or an
LLM sentiment classifier. Ambiguous options language is not interpreted as an
actual derivative position.

At the ticker level, observed social sentiment currently receives an experimental
85% weight and news 15%. Other US scopes use 55% social and 45% news. These are
configurable-in-code hypotheses, not measured facts about every US stock.
Missing social data is marked as a news proxy rather than fabricated.

## Shared engine, different market behavior

- Regular US sessions use New York timezone and DST, 78 five-minute completed-bar
  slots from 09:35 through 16:00, without an A-share lunch break.
- The US simulation has no fixed A-share 10% daily price cap. The engine's per-tick
  numerical return bound remains; it does not reproduce exchange halt rules.
- Starting balances are synthetic USD budgets; the trader mix is 40% FOMO,
  20% macro/news, 15% social contrarian, 15% mean reversion and 10% passive.
- There are no fundamental agents or valuation-gap contributions in US decisions.
- Three-day news expiry, separate market/stock/sector channels, peer memory and
  capital-capacity dynamics remain shared.
- Weekends are skipped; exchange holidays, early closes, pre/postmarket, options,
  borrowing/shorting and settlement restrictions are not modeled in this version.
- Demographic and strategy defaults are synthetic, not calibrated US population data.

## API and standalone adapter

`GET /api/market/profiles` returns public market settings. Existing market-run
endpoints accept `market`, `data_mode` and `seed_inputs` with the scenario.
Omitting `market` keeps old runs on the A-share profile.

The standalone adapter consumes normalized seeds and never fetches live sources:

```bash
cd backend
python -m market_sim examples/us_equity.json --output /tmp/us-equity-result.json
```

The example runs 1,000 traders for three full regular sessions (234 ticks), using
synthetic historical inputs. Its prices are scenario outputs, not a forecast for NVDA.

## Source references

- [NYSE regular sessions](https://www.nyse.com/trade/hours-calendars)
- [X official recent-search example](https://github.com/xdevplatform/samples/blob/main/python/posts/search_recent.py)
- [Reddit API documentation](https://www.reddit.com/dev/api/)
- [Bloomberg data delivery](https://professional.bloomberg.com/products/data/data-license/)
- [Robinhood Social](https://robinhood.com/us/en/support/articles/robinhood-social/)
