from ..base import MarketProfile

PROFILE = MarketProfile(
    key="us_equity", label="US Equities", timezone="America/New_York", currency="USD",
    session_minutes=tuple(575 + 5 * n for n in range(78)), daily_price_limit=None,
    archetypes={"fomo_momentum": 0.4, "macro_news": 0.2, "social_contrarian": 0.15,
                "mean_reversion": 0.15, "passive_retail": 0.1},
    cash_ranges={"starter": (1000, 20000), "accumulator": (20000, 100000),
                 "mid_wealth": (100000, 500000), "high_wealth": (500000, 2000000)},
    default_keyword="S&P 500", ticker_social_weight=0.85, fundamentals_enabled=False,
    age_weights={"18-24": 0.15, "25-34": 0.3, "35-44": 0.25, "45-54": 0.2, "55+": 0.1},
)
