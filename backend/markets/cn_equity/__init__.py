from ..base import MarketProfile

PROFILE = MarketProfile(
    key="cn_equity", label="A股", timezone="Asia/Shanghai", currency="CNY",
    session_minutes=tuple([575 + 5 * n for n in range(24)] + [785 + 5 * n for n in range(24)]),
    daily_price_limit=0.1,
    archetypes={"fomo_momentum": 0.3, "macro_news": 0.25, "fundamental": 0.2,
                "mean_reversion": 0.15, "passive_retail": 0.1},
    cash_ranges={"starter": (20000, 120000), "accumulator": (120000, 500000),
                 "mid_wealth": (500000, 1500000), "high_wealth": (1500000, 5000000)},
    default_keyword="A股", ticker_social_weight=0.7,
)
