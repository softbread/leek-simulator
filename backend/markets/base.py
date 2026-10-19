"""Market-specific configuration consumed by the shared simulation domain."""
from dataclasses import dataclass


@dataclass(frozen=True)
class MarketProfile:
    key: str
    label: str
    timezone: str
    currency: str
    session_minutes: tuple
    daily_price_limit: float | None
    archetypes: dict
    cash_ranges: dict
    default_keyword: str
    ticker_social_weight: float
    fundamentals_enabled: bool = True
    age_weights: dict | None = None

    @property
    def ticks_per_day(self):
        return len(self.session_minutes)

    def public(self):
        return {"market": self.key, "label": self.label, "timezone": self.timezone,
                "currency": self.currency, "ticks_per_day": self.ticks_per_day,
                "daily_price_limit": self.daily_price_limit, "archetypes": self.archetypes,
                "default_keyword": self.default_keyword, "fundamentals_enabled": self.fundamentals_enabled}
