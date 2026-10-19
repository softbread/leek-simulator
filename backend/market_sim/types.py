"""Serializable market domain types."""
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

TICKS_PER_DAY = 48

@dataclass
class MarketScenario:
    ticker: str
    stock_name: str
    sector_name: str
    starting_price: float
    float_shares_band: str
    market_regime: str
    horizon_days: int
    agent_count: int = 1000
    optional_upload_ids: List[str] = field(default_factory=list)
    trader_mix_overrides: Dict[str, float] = field(default_factory=dict)
    notes: str = ""
    seed: Optional[int] = None
    market_snapshot: Dict[str, Any] = field(default_factory=dict)
    market_keyword: str = "A股"
    market: str = "cn_equity"
    seed_inputs: Dict[str, Any] = field(default_factory=dict)
    data_mode: str = "live_and_imported"

    def __post_init__(self):
        from .sentiment import validate_snapshot
        from markets import get_profile
        profile = get_profile(self.market)
        if self.data_mode not in {"live_and_imported", "import_only"}:
            raise ValueError("data_mode must be live_and_imported or import_only")
        if not profile.fundamentals_enabled and self.trader_mix_overrides.get("fundamental", 0):
            raise ValueError("US fundamentals are externally filtered; fundamental agents are disabled")
        if self.market == "us_equity" and self.market_keyword == "A股":
            self.market_keyword = profile.default_keyword
        if not isinstance(self.seed_inputs, dict):
            raise ValueError("seed_inputs must be an object")
        for name in ("news_items", "sentiment_signals", "social_posts"):
            items = self.seed_inputs.get(name, [])
            if not isinstance(items, list) or len(items) > 2000:
                raise ValueError(f"{name} must be an array of at most 2000 items")
        validate_snapshot(self.market_snapshot, self.market)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "stock_name": self.stock_name,
            "sector_name": self.sector_name,
            "starting_price": self.starting_price,
            "float_shares_band": self.float_shares_band,
            "market_regime": self.market_regime,
            "horizon_days": self.horizon_days,
            "agent_count": self.agent_count,
            "optional_upload_ids": self.optional_upload_ids,
            "trader_mix_overrides": self.trader_mix_overrides,
            "notes": self.notes,
            "seed": self.seed,
            "market_snapshot": self.market_snapshot,
            "market_keyword": self.market_keyword,
            "market": self.market,
            "seed_inputs": self.seed_inputs,
            "data_mode": self.data_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketScenario":
        return cls(
            ticker=data["ticker"],
            stock_name=data["stock_name"],
            sector_name=data["sector_name"],
            starting_price=float(data["starting_price"]),
            float_shares_band=data["float_shares_band"],
            market_regime=data["market_regime"],
            horizon_days=int(data["horizon_days"]),
            agent_count=int(data.get("agent_count", 1000)),
            optional_upload_ids=data.get("optional_upload_ids", []),
            trader_mix_overrides=data.get("trader_mix_overrides", {}),
            notes=data.get("notes", ""),
            seed=data.get("seed"),
            market_snapshot=data.get("market_snapshot", {}),
            market_keyword=data.get("market_keyword", "A股"),
            market=data.get("market", "cn_equity"),
            seed_inputs=data.get("seed_inputs", {}),
            data_mode=data.get("data_mode", "live_and_imported"),
        )

@dataclass
class NewsItem:
    source: str
    published_at: str
    title: str
    summary: str
    sentiment: float
    relevance_score: float
    affected_scope: str
    url: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class SentimentSignal:
    source: str
    window_start: str
    window_end: str
    ticker: str
    sector: str
    sentiment_score: float
    buzz_score: float
    topic_tags: List[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class MarketShock:
    shock_type: str
    start_tick: int
    duration_ticks: int
    direction: float
    strength: float
    affected_scope: str
    headline: str
    source_refs: List[str] = field(default_factory=list)
    published_at: Optional[str] = None
    decay_hours: float = 72.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.shock_type,
            "start_tick": self.start_tick,
            "duration_ticks": self.duration_ticks,
            "direction": self.direction,
            "strength": self.strength,
            "affected_scope": self.affected_scope,
            "headline": self.headline,
            "source_refs": self.source_refs,
            "published_at": self.published_at,
            "decay_hours": self.decay_hours,
        }

@dataclass
class MarketWorldState:
    built_at: str
    scenario_snapshot: Dict[str, Any]
    seed_inputs: Dict[str, Any]
    source_health: Dict[str, Any]
    regime_factors: Dict[str, float]
    dominant_narratives: List[Dict[str, Any]]
    causal_graph: Dict[str, Any]
    archetype_biases: Dict[str, Dict[str, float]]
    tape_state: Dict[str, Any]
    tick_blueprint: List[Dict[str, Any]]
    world_summary: Dict[str, Any]
    current_sentiment: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class AgentProfile:
    agent_id: int
    archetype: str
    age_band: str
    risk_appetite: str
    wealth_stage: str
    cash: float
    holdings: int
    average_cost: float
    conviction: float
    trade_frequency: float
    stop_loss_tendency: float
    dip_buy_tendency: float
    news_sensitivity: float
    herd_sensitivity: float
    momentum_bias: float
    fundamental_bias: float
    fundamental_anchor: float
    influence_weight: float
    display_name: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

@dataclass
class SimulationTick:
    tick_index: int
    trading_day: int
    intraday_slot: int
    price: float
    return_pct: float
    volume: int
    net_demand: int
    market_sentiment: float
    xueqiu_buzz: float
    sector_pressure: float
    active_agents: int
    buy_count: int
    sell_count: int
    hold_count: int
    top_actions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

