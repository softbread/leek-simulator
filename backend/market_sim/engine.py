"""Market rounds and price-impact execution."""
import math
import random
import time
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple
from .utils import _clamp
from .types import MarketScenario, AgentProfile, MarketShock, SentimentSignal, SimulationTick, NewsItem
from .memory import MarketWorldRuntime
from .traders import ABMTraderPolicy, TraderAgent
from .sentiment import forecast_time, news_weight
from .world import WorldStateBuilder
from markets import get_profile

class PriceImpactEngine:
    TICKS_PER_DAY = 48

    def __init__(
        self,
        scenario: MarketScenario,
        agents: List[AgentProfile],
        shocks: List[MarketShock],
        sentiment_signals: List[SentimentSignal],
        world_state: Optional[Dict[str, Any]] = None,
        policy_factory=None,
    ):
        self.scenario = scenario
        self.profile = get_profile(scenario.market)
        self.TICKS_PER_DAY = self.profile.ticks_per_day
        self.agents = agents
        self.shocks = shocks
        self.sentiment_signals = sentiment_signals
        self.world_state = world_state or {}
        seed = scenario.seed if scenario.seed is not None else sum(ord(char) for char in scenario.ticker) * 17 + scenario.agent_count
        self.rng = random.Random(seed)
        self.total_ticks = max(1, scenario.horizon_days) * self.TICKS_PER_DAY
        self.float_reference = self._resolve_float_reference(scenario.float_shares_band)
        self.regime_factors = self.world_state.get("regime_factors", {})
        self.tick_blueprint = self.world_state.get("tick_blueprint", [])
        self.archetype_biases = dict(self.world_state.get("archetype_biases", {}))
        self.live_snapshot = self.world_state.get("current_sentiment", {})
        self._live_tick = None
        self.world = MarketWorldRuntime(agents, self.world_state, seed)
        self.traders = {
            agent.agent_id: TraderAgent(agent, self.world,
                (policy_factory(agent) if policy_factory else None) or ABMTraderPolicy(self.archetype_biases))
            for agent in agents
        }
        self.summary = {"action_totals": {}, "archetype_contribution": {}}

    def _resolve_float_reference(self, band: str) -> float:
        mapping = {
            "small": 8_000_000,
            "mid": 25_000_000,
            "large": 90_000_000,
            "mega": 240_000_000,
        }
        return mapping.get((band or "").lower(), 25_000_000)

    def run(self, progress_callback=None) -> Tuple[List[SimulationTick], Dict[str, Any]]:
        ticks = list(self.iter_ticks(progress_callback))
        return ticks, self.summary

    def iter_ticks(self, progress_callback=None):
        price = max(0.01 if self.scenario.market == "us_equity" else 0.5, self.scenario.starting_price)
        day_open = price
        recent_peak = price
        ticks: List[SimulationTick] = []
        action_totals = Counter()
        archetype_contribution = Counter()
        previous_date = None
        session_day = 0

        for tick_index in range(self.total_ticks):
            if not self.live_snapshot and tick_index % self.TICKS_PER_DAY == 0:
                day_open = price
            trading_day = tick_index // self.TICKS_PER_DAY + 1
            intraday_slot = tick_index % self.TICKS_PER_DAY
            self._refresh_world(tick_index)
            if self.live_snapshot:
                stamp = forecast_time(self.world_state["current_sentiment"]["as_of"], tick_index, self.scenario.market)
                if stamp.date() != previous_date:
                    day_open = price
                    session_day += 1
                previous_date = stamp.date()
                trading_day = session_day
                intraday_slot = self.profile.session_minutes.index(stamp.hour * 60 + stamp.minute)
            shock_bias, sector_bias, dominant_headline = self._shock_state(tick_index)
            crowd_sentiment, crowd_buzz = self._sentiment_state(tick_index)
            momentum = 0.0 if not ticks else sum(item.return_pct for item in ticks[-3:]) / max(len(ticks[-3:]), 1)
            recent_peak = max(recent_peak, price)
            world_context = self.world.context(self._world_state_at(tick_index))
            actions, net_demand, volume = self._agent_actions(
                price=price,
                slot=intraday_slot,
                momentum=momentum,
                shock_bias=shock_bias,
                sector_bias=sector_bias,
                crowd_sentiment=crowd_sentiment,
                crowd_buzz=crowd_buzz,
                recent_peak=recent_peak,
                world_context=world_context,
            )
            for action in actions:
                action_totals[action["action"]] += 1
                archetype_contribution[action["archetype"]] += action.get("signed_quantity", 0)
            imbalance = net_demand / max(self.float_reference, 1)
            base_noise = self.rng.uniform(-0.0009, 0.0009)
            world_risk_bias = (
                world_context["policy_pressure"]
                + world_context["retail_herding"]
                + world_context["institutional_conviction"]
                + world_context["sector_heat"]
                - world_context["downside_risk"]
            ) / 5
            raw_return = (
                shock_bias * 0.0032
                + sector_bias * 0.0017
                + crowd_sentiment * 0.0015
                + world_context["tape_momentum_bias"] * 0.0019
                + world_risk_bias * 0.0014
                + math.tanh(imbalance * 180) * 0.0085
                + momentum * 0.18
                + base_noise
            )
            if self.world_state.get("current_sentiment"):
                raw_return = math.tanh(imbalance * 180) * 0.0085 + momentum * 0.18 + base_noise
            intraday_limit = self.profile.daily_price_limit
            proposed_price = max(0.01 if self.scenario.market == "us_equity" else 0.5,
                                 price * (1 + _clamp(raw_return, -0.035, 0.035)))
            new_price = proposed_price if intraday_limit is None else _clamp(
                proposed_price, day_open * (1 - intraday_limit), day_open * (1 + intraday_limit))
            tick_return = (new_price - price) / max(price, 1e-6)
            price = round(new_price, 4)
            self.world.commit(tick_index, price, tick_return, actions, world_context,
                              remember=self._remember)

            buy_count = sum(1 for action in actions if action["action"] == "buy")
            sell_count = sum(1 for action in actions if action["action"] == "sell")
            hold_count = len(actions) - buy_count - sell_count
            tick = SimulationTick(
                tick_index=tick_index,
                trading_day=trading_day,
                intraday_slot=intraday_slot,
                price=price,
                return_pct=round(tick_return, 5),
                volume=volume,
                net_demand=net_demand,
                market_sentiment=round((shock_bias + crowd_sentiment + world_risk_bias) / 3, 4),
                xueqiu_buzz=round(crowd_buzz, 4),
                sector_pressure=round((sector_bias + world_context["sector_heat"]) / 2, 4),
                active_agents=len(actions),
                buy_count=buy_count,
                sell_count=sell_count,
                hold_count=hold_count,
                top_actions=sorted(actions, key=lambda item: abs(item.get("signed_quantity", 0)), reverse=True)[:8],
            )
            if dominant_headline:
                tick.top_actions.append({
                    "action": "headline",
                    "agent_id": 0,
                    "agent_name": dominant_headline,
                    "signed_quantity": 0,
                    "archetype": "market",
                })
            if world_context["dominant_narrative"]:
                tick.top_actions.append({
                    "action": "world_state",
                    "agent_id": -1,
                    "agent_name": world_context["dominant_narrative"],
                    "signed_quantity": 0,
                    "archetype": "world",
                })
            ticks.append(tick)
            if progress_callback and (tick_index == self.total_ticks - 1 or tick_index % 4 == 0):
                progress_callback(tick_index + 1, self.total_ticks, ticks[-12:])
            time.sleep(0.005)
            self.summary = {
                "action_totals": dict(action_totals),
                "archetype_contribution": dict(archetype_contribution),
            }
            yield tick

    def _remember(self, agent_id, tick_index, price, action, context):
        self.traders[agent_id].remember(tick_index, price, action, context)

    def _shock_state(self, tick_index: int) -> Tuple[float, float, str]:
        ticker_bias = 0.0
        sector_bias = 0.0
        dominant_headline = ""
        dominant_strength = 0.0
        for shock in self.shocks:
            if not (shock.start_tick <= tick_index < shock.start_tick + shock.duration_ticks):
                continue
            if shock.published_at and self.world_state.get("current_sentiment"):
                remaining = news_weight(shock.published_at,
                    forecast_time(self.world_state["current_sentiment"]["as_of"], tick_index, self.scenario.market), shock.decay_hours, self.scenario.market)
            else:
                remaining = 1 - ((tick_index - shock.start_tick) / max(shock.duration_ticks, 1))
            impact = shock.direction * shock.strength * remaining
            if shock.affected_scope == "ticker":
                ticker_bias += impact
            else:
                sector_bias += impact
            if abs(impact) > dominant_strength:
                dominant_strength = abs(impact)
                dominant_headline = shock.headline
        regime_map = {
            "bullish": (0.12, 0.18),
            "neutral": (0.0, 0.0),
            "bearish": (-0.12, -0.18),
            "volatile": (0.0, 0.08 if tick_index % 7 < 3 else -0.08),
        }
        ticker_regime, sector_regime = regime_map.get(self.scenario.market_regime, (0.0, 0.0))
        return ticker_bias + ticker_regime, sector_bias + sector_regime, dominant_headline

    def _sentiment_state(self, tick_index: int) -> Tuple[float, float]:
        self._refresh_world(tick_index)
        snapshot = self.live_snapshot
        if snapshot:
            # Observations seed t=0. Later emotion evolves through agent feedback.
            return (snapshot.get("channels", {}).get("stock", {}).get("sentiment_score", snapshot["sentiment_score"]),
                    snapshot["buzz_score"] * math.exp(-tick_index / (2 * self.TICKS_PER_DAY)))
        if not self.sentiment_signals:
            return 0.0, 0.0
        index = min(len(self.sentiment_signals) - 1, int(tick_index / max(self.total_ticks / len(self.sentiment_signals), 1)))
        signal = self.sentiment_signals[index]
        return signal.sentiment_score, signal.buzz_score

    def _session_factor(self, slot: int) -> float:
        slot = slot * 48 / self.TICKS_PER_DAY
        if slot < 6:
            return 1.18
        if slot < 18:
            return 0.95
        if slot < 30:
            return 0.82
        if slot < 40:
            return 0.9
        return 1.12

    def _refresh_world(self, tick_index):
        initial = self.world_state.get("current_sentiment")
        if not initial or self._live_tick == tick_index:
            return
        seed = self.world_state.get("seed_inputs", {})
        stamp = forecast_time(initial["as_of"], tick_index, self.scenario.market)
        uploads = seed.get("upload_texts", [])
        upload_weight = news_weight(initial["as_of"], stamp, market=self.scenario.market)
        live = WorldStateBuilder.build(
            self.scenario, [NewsItem(**item) for item in seed.get("news_items", [])],
            [SentimentSignal(**item) for item in seed.get("sentiment_signals", [])],
            uploads if upload_weight > 0 else [], self.world_state.get("source_health", {}),
            as_of=stamp, upload_decay=upload_weight,
        )
        self.live_snapshot = live.current_sentiment
        self.regime_factors = live.regime_factors
        self.tick_blueprint = live.tick_blueprint
        self.archetype_biases.clear()
        self.archetype_biases.update(live.archetype_biases)
        self._live_tick = tick_index

    def _world_state_at(self, tick_index: int) -> Dict[str, Any]:
        self._refresh_world(tick_index)
        channels = self.live_snapshot.get("channels", {})
        defaults = {
            "fundamentals_enabled": self.profile.fundamentals_enabled,
            "market": self.scenario.market,
            "minimum_cash_shares": 1 if self.scenario.market == "us_equity" else 100,
            "market_sentiment": channels.get("market", {}).get("sentiment_score", 0.0),
            "stock_sentiment": channels.get("stock", {}).get("sentiment_score", 0.0),
            "sector_sentiment": channels.get("sector", {}).get("sentiment_score", 0.0),
            "simulated_at": forecast_time(self.world_state["current_sentiment"]["as_of"], tick_index, self.scenario.market).isoformat() if self.live_snapshot else "",
            "policy_pressure": float(self.regime_factors.get("policy_pressure", 0.0)),
            "retail_herding": float(self.regime_factors.get("retail_herding", 0.0)),
            "institutional_conviction": float(self.regime_factors.get("institutional_conviction", 0.0)),
            "liquidity_temperature": float(self.regime_factors.get("liquidity_temperature", 1.0)),
            "valuation_temperature": float(self.regime_factors.get("valuation_temperature", 0.0)),
            "tape_momentum_bias": float(self.regime_factors.get("tape_momentum_seed", 0.0)),
            "downside_risk": float(self.regime_factors.get("downside_risk", 0.0)),
            "sector_heat": float(self.regime_factors.get("sector_heat", 0.0)),
            "narrative_temperature": float(self.regime_factors.get("narrative_temperature", 0.2)),
            "activation_temperature": 1.0,
            "dominant_narrative": "",
        }
        if not self.tick_blueprint:
            return defaults
        segment = self.tick_blueprint[-1]
        for candidate in self.tick_blueprint:
            if candidate["start_tick"] <= tick_index < candidate["end_tick"]:
                segment = candidate
                break
        activation_temperature = _clamp(
            1
            + (defaults["liquidity_temperature"] - 1) * 0.18
            + defaults["narrative_temperature"] * 0.12
            + segment.get("herding_multiplier", 1.0) * 0.05,
            0.75,
            1.45,
        )
        return {
            **defaults,
            "policy_pressure": _clamp(defaults["policy_pressure"] * segment.get("news_multiplier", 1.0), -1.6, 1.6),
            "retail_herding": _clamp(defaults["retail_herding"] * segment.get("herding_multiplier", 1.0), -1.8, 1.8),
            "institutional_conviction": _clamp(defaults["institutional_conviction"] * segment.get("institutional_multiplier", 1.0), -1.5, 1.5),
            "liquidity_temperature": _clamp(defaults["liquidity_temperature"] + segment.get("liquidity_shift", 0.0), 0.15, 2.1),
            "valuation_temperature": _clamp(defaults["valuation_temperature"] * segment.get("value_multiplier", 1.0), -1.3, 1.5),
            "tape_momentum_bias": _clamp(defaults["tape_momentum_bias"] + segment.get("momentum_shift", 0.0), -1.5, 1.5),
            "downside_risk": defaults["downside_risk"],
            "sector_heat": defaults["sector_heat"],
            "narrative_temperature": defaults["narrative_temperature"],
            "activation_temperature": activation_temperature,
            "dominant_narrative": segment.get("dominant_narrative", ""),
        }

    def _agent_actions(
        self, price, slot, momentum, shock_bias, sector_bias,
        crowd_sentiment, crowd_buzz, recent_peak, world_context,
    ):
        actions = []
        net_demand = 0
        volume = 0
        session_factor = self._session_factor(slot) * world_context["activation_temperature"]
        if "profit_effect" in world_context:
            session_factor *= _clamp(1 + world_context["profit_effect"] * 0.2
                                     - world_context["loss_effect"] * 0.25
                                     + abs(world_context["overnight_impulse"]) * 0.3, 0.65, 1.5)
        for agent in self.agents:
            activation = float(self.archetype_biases.get(agent.archetype, {}).get("activation_boost", 0.0))
            if self.rng.random() > agent.trade_frequency * session_factor * (1 + activation):
                continue
            trader = self.traders[agent.agent_id]
            observation = trader.observe(
                price=price, recent_peak=recent_peak, momentum=momentum,
                shock_bias=shock_bias, sector_bias=sector_bias,
                crowd_sentiment=crowd_sentiment, crowd_buzz=crowd_buzz,
                world_context=world_context,
            )
            action = trader.act(trader.decide(observation), observation)
            actions.append(action)
            net_demand += action["signed_quantity"]
            volume += abs(action["signed_quantity"])
        return actions, net_demand, volume

