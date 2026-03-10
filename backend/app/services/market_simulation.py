"""
A股市场仿真核心服务
"""

import html
import json
import math
import random
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..models.market import MarketRun, MarketRunManager, MarketRunStatus, MarketScenario, MarketUploadManager
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from .xueqiu_browser import XueqiuBrowserAuthService

logger = get_logger("mirofish.market")


POSITIVE_WORDS = {
    "上涨", "增长", "突破", "利好", "增持", "回购", "超预期", "景气", "反弹", "修复",
    "盈利", "扩张", "提价", "强劲", "改善", "龙头", "看多", "加仓", "新高", "爆发",
}
NEGATIVE_WORDS = {
    "下跌", "利空", "减持", "回撤", "亏损", "承压", "风险", "调查", "波动", "放缓",
    "预警", "疲软", "收缩", "卖出", "踩雷", "担忧", "低迷", "跳水", "压力", "高估",
}
TOPIC_STOPWORDS = {
    "公司", "市场", "行业", "今日", "板块", "个股", "投资者", "消息", "方面", "数据",
    "公告", "相关", "表示", "显示", "继续", "可能", "影响", "因为", "以及", "关于",
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _normalize_ticker(ticker: str) -> str:
    cleaned = (ticker or "").strip().upper()
    if cleaned.startswith(("SH", "SZ", "BJ")):
        return cleaned
    if cleaned.startswith("6"):
        return f"SH{cleaned}"
    if cleaned.startswith(("0", "3")):
        return f"SZ{cleaned}"
    return cleaned


def _clean_html_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", "", raw or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _weighted_choice(rng: random.Random, weights: Dict[str, float]) -> str:
    total = sum(max(0.0, value) for value in weights.values())
    pivot = rng.random() * max(total, 1e-9)
    cursor = 0.0
    last_key = next(iter(weights))
    for key, value in weights.items():
        cursor += max(0.0, value)
        if pivot <= cursor:
            return key
        last_key = key
    return last_key


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    clipped = {key: max(0.0, float(value)) for key, value in weights.items()}
    total = sum(clipped.values())
    if total <= 0:
        fallback = 1.0 / max(len(clipped), 1)
        return {key: fallback for key in clipped}
    return {key: value / total for key, value in clipped.items()}


def _score_sentiment(text: str) -> float:
    content = text or ""
    positive = sum(word in content for word in POSITIVE_WORDS)
    negative = sum(word in content for word in NEGATIVE_WORDS)
    if positive == 0 and negative == 0:
        return 0.0
    return _clamp((positive - negative) / max(positive + negative, 1), -1.0, 1.0)


def _extract_topics(texts: List[str], limit: int = 6) -> List[str]:
    counter: Counter[str] = Counter()
    for text in texts:
        for token in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,8}", text or ""):
            if token in TOPIC_STOPWORDS or token.isdigit():
                continue
            counter[token] += 1
    return [token for token, _ in counter.most_common(limit)]


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


class EastmoneyNewsAdapter:
    SEARCH_URL = "https://search-api-web.eastmoney.com/search/jsonp?cb=?"

    def __init__(self):
        self.user_agent = "Mozilla/5.0 (compatible; MiroFishMarket/1.0)"

    def fetch_news(self, keyword: str, affected_scope: str, limit: int = 6) -> List[NewsItem]:
        if not keyword:
            return []
        payload = {
            "uid": "",
            "keyword": keyword,
            "type": ["cmsArticleWebOld"],
            "client": "web",
            "clientType": "web",
            "clientVersion": "curr",
            "param": {
                "cmsArticleWebOld": {
                    "searchScope": "DEFAULT",
                    "sort": "default",
                    "pageIndex": 1,
                    "pageSize": limit,
                    "preTag": "<em>",
                    "postTag": "</em>",
                }
            },
        }
        query = urllib.parse.urlencode({
            "cb": "?",
            "param": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        })
        request_url = f"{self.SEARCH_URL}&{query}"
        req = urllib.request.Request(
            request_url,
            headers={
                "User-Agent": self.user_agent,
                "Referer": "https://so.eastmoney.com/",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                body = response.read().decode("utf-8", "ignore")
        except urllib.error.URLError as exc:
            logger.warning("东方财富资讯抓取失败 keyword=%s error=%s", keyword, exc)
            return []
        body = body.strip()
        if body.startswith("?(") and body.endswith(")"):
            body = body[2:-1]
        payload_json = json.loads(body)
        raw_items = payload_json.get("result", {}).get("cmsArticleWebOld", []) or []
        items: List[NewsItem] = []
        for raw in raw_items:
            title = _clean_html_text(raw.get("title", ""))
            summary = _clean_html_text(raw.get("content", ""))
            published_at = raw.get("date", _now_iso())
            sentiment = _score_sentiment(f"{title} {summary}")
            relevance = 0.55 + 0.35 * abs(sentiment)
            items.append(
                NewsItem(
                    source="eastmoney",
                    published_at=published_at,
                    title=title,
                    summary=summary,
                    sentiment=sentiment,
                    relevance_score=round(_clamp(relevance, 0.1, 1.0), 4),
                    affected_scope=affected_scope,
                    url=raw.get("url", ""),
                    metadata={
                        "media_name": raw.get("mediaName", ""),
                        "code": raw.get("code", ""),
                    },
                )
            )
        return items


class XueqiuSentimentAdapter:
    def fetch_signals(
        self,
        scenario: MarketScenario,
        news_items: List[NewsItem],
    ) -> List[SentimentSignal]:
        browser_live = self._try_browser_fetch(scenario)
        if browser_live:
            return browser_live
        return self._build_fallback_signals(scenario, news_items)

    def _try_browser_fetch(self, scenario: MarketScenario) -> List[SentimentSignal]:
        if not XueqiuBrowserAuthService.is_authenticated():
            return []

        ticker_query = scenario.stock_name or scenario.ticker
        sector_query = scenario.sector_name
        ticker_statuses = XueqiuBrowserAuthService.fetch_search_statuses(ticker_query, count=12)
        sector_statuses = XueqiuBrowserAuthService.fetch_search_statuses(sector_query, count=10)
        stock_page_snippets = XueqiuBrowserAuthService.scrape_stock_page(_normalize_ticker(scenario.ticker), sample_limit=10)

        ticker_texts = self._extract_texts(ticker_statuses) + stock_page_snippets
        sector_texts = self._extract_texts(sector_statuses)

        signals: List[SentimentSignal] = []
        if ticker_texts:
            ticker_topics = _extract_topics(ticker_texts)
            ticker_sentiment = sum(_score_sentiment(text) for text in ticker_texts) / max(len(ticker_texts), 1)
            signals.append(
                SentimentSignal(
                    source="xueqiu",
                    window_start=_now_iso(),
                    window_end=_now_iso(),
                    ticker=_normalize_ticker(scenario.ticker),
                    sector=scenario.sector_name,
                    sentiment_score=round(_clamp(ticker_sentiment, -1.0, 1.0), 4),
                    buzz_score=round(math.log1p(len(ticker_texts)) * 4.2, 4),
                    topic_tags=ticker_topics or [scenario.stock_name],
                    metadata={"mode": "browser", "scope": "ticker", "sample_size": len(ticker_texts)},
                )
            )
        if sector_texts:
            sector_topics = _extract_topics(sector_texts)
            sector_sentiment = sum(_score_sentiment(text) for text in sector_texts) / max(len(sector_texts), 1)
            signals.append(
                SentimentSignal(
                    source="xueqiu",
                    window_start=_now_iso(),
                    window_end=_now_iso(),
                    ticker=_normalize_ticker(scenario.ticker),
                    sector=scenario.sector_name,
                    sentiment_score=round(_clamp(sector_sentiment, -1.0, 1.0), 4),
                    buzz_score=round(math.log1p(len(sector_texts)) * 3.6, 4),
                    topic_tags=sector_topics or [scenario.sector_name],
                    metadata={"mode": "browser", "scope": "sector", "sample_size": len(sector_texts)},
                )
            )
        return signals

    def _extract_texts(self, statuses: List[Dict[str, Any]]) -> List[str]:
        texts = []
        for item in statuses:
            candidate = _clean_html_text(
                item.get("text")
                or item.get("description")
                or item.get("title")
                or item.get("fullText")
                or item.get("status", {}).get("text", "")
            )
            if candidate:
                texts.append(candidate)
        return texts

    def _build_fallback_signals(
        self,
        scenario: MarketScenario,
        news_items: List[NewsItem],
    ) -> List[SentimentSignal]:
        rng = random.Random((scenario.seed or 0) + scenario.agent_count * 17)
        horizon = max(1, scenario.horizon_days)
        windows = horizon * 2
        ticker_news = [item for item in news_items if item.affected_scope == "ticker"]
        sector_news = [item for item in news_items if item.affected_scope == "sector"]
        baseline = 0.0
        if ticker_news:
            baseline += sum(item.sentiment for item in ticker_news) / len(ticker_news) * 0.7
        if sector_news:
            baseline += sum(item.sentiment for item in sector_news) / len(sector_news) * 0.3
        topics = _extract_topics([item.title for item in news_items] + [item.summary for item in news_items], limit=8)
        signals: List[SentimentSignal] = []
        for index in range(windows):
            oscillation = math.sin((index + 1) / max(windows, 1) * math.pi * 1.25) * 0.12
            noise = rng.uniform(-0.09, 0.09)
            sentiment = _clamp(baseline + oscillation + noise, -1.0, 1.0)
            buzz_seed = len(ticker_news) * 1.8 + len(sector_news) * 1.1 + abs(sentiment) * 6 + rng.uniform(0.4, 2.6)
            signals.append(
                SentimentSignal(
                    source="xueqiu",
                    window_start=f"D{index // 2 + 1}-W{index % 2 + 1}",
                    window_end=f"D{index // 2 + 1}-W{index % 2 + 2}",
                    ticker=_normalize_ticker(scenario.ticker),
                    sector=scenario.sector_name,
                    sentiment_score=round(sentiment, 4),
                    buzz_score=round(buzz_seed, 4),
                    topic_tags=topics[:4] or [scenario.stock_name, scenario.sector_name],
                    metadata={"mode": "fallback"},
                )
            )
        return signals


class ShockBuilder:
    @staticmethod
    def build(
        scenario: MarketScenario,
        news_items: List[NewsItem],
        upload_texts: List[str],
    ) -> List[MarketShock]:
        total_ticks = max(1, scenario.horizon_days) * 48
        shocks: List[MarketShock] = []
        for index, item in enumerate(news_items[:12]):
            start_tick = min(total_ticks - 1, int(index * max(total_ticks / max(len(news_items), 1), 1)))
            duration = 6 if item.affected_scope == "ticker" else 10
            strength = round(0.6 + abs(item.sentiment) * 1.6 + item.relevance_score * 0.8, 4)
            shocks.append(
                MarketShock(
                    shock_type="news",
                    start_tick=start_tick,
                    duration_ticks=duration,
                    direction=1.0 if item.sentiment >= 0 else -1.0,
                    strength=strength,
                    affected_scope=item.affected_scope,
                    headline=item.title,
                    source_refs=[item.url] if item.url else [],
                )
            )
        for index, text in enumerate(upload_texts[:4]):
            score = _score_sentiment(text)
            if abs(score) < 0.05:
                continue
            excerpt = re.sub(r"\s+", " ", text)[:80]
            shocks.append(
                MarketShock(
                    shock_type="upload_context",
                    start_tick=min(total_ticks - 1, index * 12),
                    duration_ticks=12,
                    direction=1.0 if score >= 0 else -1.0,
                    strength=round(0.85 + abs(score), 4),
                    affected_scope="ticker",
                    headline=f"上传材料提及: {excerpt}",
                    source_refs=[],
                )
            )
        return shocks


class WorldStateBuilder:
    @staticmethod
    def build(
        scenario: MarketScenario,
        news_items: List[NewsItem],
        sentiment_signals: List[SentimentSignal],
        upload_texts: List[str],
        source_health: Dict[str, Any],
    ) -> MarketWorldState:
        ticker_news = [item for item in news_items if item.affected_scope == "ticker"]
        sector_news = [item for item in news_items if item.affected_scope == "sector"]
        ticker_sentiment = sum(item.sentiment for item in ticker_news) / max(len(ticker_news), 1)
        sector_sentiment = sum(item.sentiment for item in sector_news) / max(len(sector_news), 1)
        crowd_sentiment = sum(item.sentiment_score for item in sentiment_signals) / max(len(sentiment_signals), 1)
        crowd_buzz = sum(item.buzz_score for item in sentiment_signals) / max(len(sentiment_signals), 1)
        upload_sentiment = sum(_score_sentiment(text) for text in upload_texts) / max(len(upload_texts), 1)
        regime_bias = {
            "bullish": 0.22,
            "neutral": 0.0,
            "bearish": -0.22,
            "volatile": 0.04 if crowd_sentiment >= 0 else -0.04,
        }.get(scenario.market_regime, 0.0)
        policy_pressure = _clamp(sector_sentiment * 0.8 + ticker_sentiment * 0.35 + upload_sentiment * 0.15 + regime_bias, -1.4, 1.4)
        retail_herding = _clamp(crowd_sentiment * 0.85 + min(crowd_buzz / 8.5, 1.2) * 0.45, -1.4, 1.6)
        institutional_conviction = _clamp(
            ticker_sentiment * 0.55 + sector_sentiment * 0.28 + upload_sentiment * 0.45 - retail_herding * 0.12,
            -1.2,
            1.2,
        )
        valuation_temperature = _clamp(
            crowd_sentiment * 0.45 + min(crowd_buzz / 10.0, 1.0) * 0.35 - institutional_conviction * 0.2 + regime_bias * 0.4,
            -1.0,
            1.35,
        )
        liquidity_temperature = _clamp(
            0.42 + min(crowd_buzz / 7.5, 1.4) + abs(policy_pressure) * 0.25 + (0.18 if scenario.market_regime == "volatile" else 0.0),
            0.15,
            2.0,
        )
        tape_momentum_seed = _clamp(ticker_sentiment * 0.55 + crowd_sentiment * 0.35 + regime_bias * 0.6, -1.2, 1.2)
        downside_risk = _clamp(
            max(0.0, -policy_pressure) * 0.7
            + max(0.0, -institutional_conviction) * 0.55
            + (0.18 if scenario.market_regime == "bearish" else 0.0),
            0.0,
            1.5,
        )
        sector_heat = _clamp(sector_sentiment * 0.75 + min(crowd_buzz / 11.0, 1.0) * 0.25 + regime_bias * 0.35, -1.2, 1.2)
        narrative_temperature = _clamp((abs(policy_pressure) + abs(retail_herding) + abs(institutional_conviction)) / 3, 0.1, 1.6)

        all_texts = [item.title for item in news_items] + [item.summary for item in news_items] + upload_texts
        topics = _extract_topics(all_texts, limit=10)
        narratives = WorldStateBuilder._build_narratives(
            scenario=scenario,
            news_items=news_items,
            sentiment_signals=sentiment_signals,
            topics=topics,
            factors={
                "policy_pressure": policy_pressure,
                "retail_herding": retail_herding,
                "institutional_conviction": institutional_conviction,
                "valuation_temperature": valuation_temperature,
                "sector_heat": sector_heat,
            },
        )
        causal_graph = WorldStateBuilder._build_causal_graph(scenario, narratives, topics, {
            "policy_pressure": policy_pressure,
            "retail_herding": retail_herding,
            "institutional_conviction": institutional_conviction,
            "liquidity_temperature": liquidity_temperature,
            "valuation_temperature": valuation_temperature,
            "tape_momentum_seed": tape_momentum_seed,
            "downside_risk": downside_risk,
            "sector_heat": sector_heat,
        })
        total_ticks = max(1, scenario.horizon_days) * PriceImpactEngine.TICKS_PER_DAY
        tick_blueprint = WorldStateBuilder._build_tick_blueprint(total_ticks, narratives, {
            "policy_pressure": policy_pressure,
            "retail_herding": retail_herding,
            "institutional_conviction": institutional_conviction,
            "liquidity_temperature": liquidity_temperature,
            "valuation_temperature": valuation_temperature,
            "tape_momentum_seed": tape_momentum_seed,
            "downside_risk": downside_risk,
            "sector_heat": sector_heat,
            "narrative_temperature": narrative_temperature,
        })
        archetype_biases = WorldStateBuilder._build_archetype_biases({
            "policy_pressure": policy_pressure,
            "retail_herding": retail_herding,
            "institutional_conviction": institutional_conviction,
            "liquidity_temperature": liquidity_temperature,
            "valuation_temperature": valuation_temperature,
            "tape_momentum_seed": tape_momentum_seed,
            "downside_risk": downside_risk,
            "sector_heat": sector_heat,
            "narrative_temperature": narrative_temperature,
        })

        return MarketWorldState(
            built_at=_now_iso(),
            scenario_snapshot=scenario.to_dict(),
            seed_inputs={
                "news_items": [item.to_dict() for item in news_items],
                "sentiment_signals": [item.to_dict() for item in sentiment_signals],
                "upload_texts": upload_texts,
                "topics": topics,
            },
            source_health=source_health,
            regime_factors={
                "policy_pressure": round(policy_pressure, 4),
                "retail_herding": round(retail_herding, 4),
                "institutional_conviction": round(institutional_conviction, 4),
                "liquidity_temperature": round(liquidity_temperature, 4),
                "valuation_temperature": round(valuation_temperature, 4),
                "tape_momentum_seed": round(tape_momentum_seed, 4),
                "downside_risk": round(downside_risk, 4),
                "sector_heat": round(sector_heat, 4),
                "narrative_temperature": round(narrative_temperature, 4),
            },
            dominant_narratives=narratives[:5],
            causal_graph=causal_graph,
            archetype_biases=archetype_biases,
            tape_state={
                "price_anchor": round(scenario.starting_price, 4),
                "support_level": round(scenario.starting_price * (1 - max(0.02, downside_risk * 0.035)), 4),
                "resistance_level": round(scenario.starting_price * (1 + max(0.025, max(0.0, retail_herding) * 0.05 + max(0.0, policy_pressure) * 0.04)), 4),
                "initial_drift": round(tape_momentum_seed * 0.012, 5),
            },
            tick_blueprint=tick_blueprint,
            world_summary={
                "dominant_market_style": WorldStateBuilder._dominant_style(policy_pressure, retail_herding, institutional_conviction, valuation_temperature),
                "headline_count": len(news_items),
                "discussion_windows": len(sentiment_signals),
                "topics": topics[:6],
                "top_narrative": narratives[0]["label"] if narratives else scenario.stock_name,
            },
        )

    @staticmethod
    def _build_narratives(
        scenario: MarketScenario,
        news_items: List[NewsItem],
        sentiment_signals: List[SentimentSignal],
        topics: List[str],
        factors: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        narratives: List[Dict[str, Any]] = []
        for item in sorted(news_items, key=lambda value: abs(value.sentiment) * value.relevance_score, reverse=True)[:4]:
            narratives.append({
                "label": item.title[:48],
                "scope": item.affected_scope,
                "stance": "bullish" if item.sentiment >= 0 else "bearish",
                "intensity": round(_clamp(abs(item.sentiment) * 0.9 + item.relevance_score, 0.15, 1.6), 4),
                "topic_tags": _extract_topics([item.title, item.summary], limit=4) or topics[:3],
                "source": item.source,
            })
        if sentiment_signals:
            dominant_topics = _extract_topics([" ".join(signal.topic_tags) for signal in sentiment_signals], limit=4) or topics[:4]
            narratives.append({
                "label": f"雪球情绪主线: {' / '.join(dominant_topics[:2] or [scenario.stock_name])}",
                "scope": "ticker",
                "stance": "bullish" if factors["retail_herding"] >= 0 else "bearish",
                "intensity": round(_clamp(abs(factors["retail_herding"]) * 0.95 + abs(factors["valuation_temperature"]) * 0.25, 0.2, 1.7), 4),
                "topic_tags": dominant_topics,
                "source": "xueqiu",
            })
        narratives.append({
            "label": f"{scenario.sector_name} 板块风险偏好",
            "scope": "sector",
            "stance": "bullish" if factors["policy_pressure"] + factors["institutional_conviction"] >= 0 else "bearish",
            "intensity": round(_clamp(abs(factors["policy_pressure"]) * 0.7 + abs(factors["institutional_conviction"]) * 0.55, 0.2, 1.5), 4),
            "topic_tags": topics[:4] or [scenario.sector_name],
            "source": "world_model",
        })
        narratives.sort(key=lambda item: item["intensity"], reverse=True)
        return narratives

    @staticmethod
    def _build_causal_graph(
        scenario: MarketScenario,
        narratives: List[Dict[str, Any]],
        topics: List[str],
        factors: Dict[str, float],
    ) -> Dict[str, Any]:
        nodes = [
            {"id": "stock", "type": "stock", "label": f"{scenario.stock_name}({scenario.ticker})"},
            {"id": "sector", "type": "sector", "label": scenario.sector_name},
            {"id": "retail_mood", "type": "factor", "label": "散户情绪"},
            {"id": "institutional_view", "type": "factor", "label": "机构预期"},
            {"id": "policy_signal", "type": "factor", "label": "政策/宏观信号"},
            {"id": "liquidity", "type": "factor", "label": "流动性温度"},
            {"id": "tape", "type": "factor", "label": "价格带"},
        ]
        for index, narrative in enumerate(narratives[:4], start=1):
            nodes.append({
                "id": f"narrative_{index}",
                "type": "narrative",
                "label": narrative["label"],
                "intensity": narrative["intensity"],
            })
        edges = [
            {"from": "policy_signal", "to": "sector", "weight": round(factors["policy_pressure"], 4)},
            {"from": "sector", "to": "stock", "weight": round(factors["sector_heat"], 4)},
            {"from": "retail_mood", "to": "tape", "weight": round(factors["retail_herding"], 4)},
            {"from": "institutional_view", "to": "stock", "weight": round(factors["institutional_conviction"], 4)},
            {"from": "liquidity", "to": "tape", "weight": round(factors["liquidity_temperature"] - 1, 4)},
        ]
        for index, narrative in enumerate(narratives[:4], start=1):
            edges.append({
                "from": f"narrative_{index}",
                "to": "retail_mood" if narrative["source"] == "xueqiu" else "institutional_view",
                "weight": narrative["intensity"],
            })
        return {"nodes": nodes, "edges": edges, "topics": topics[:8]}

    @staticmethod
    def _build_tick_blueprint(
        total_ticks: int,
        narratives: List[Dict[str, Any]],
        factors: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        top_labels = [item["label"] for item in narratives[:4]] or ["市场主线"]
        segments = [
            {
                "name": "open_impulse",
                "ratio": 0.22,
                "news_multiplier": 1.18,
                "herding_multiplier": 1.1,
                "institutional_multiplier": 0.92,
                "value_multiplier": 0.88,
                "liquidity_shift": 0.15,
                "momentum_shift": factors["tape_momentum_seed"] * 0.18,
                "dominant_narrative": top_labels[0],
            },
            {
                "name": "crowd_diffusion",
                "ratio": 0.34,
                "news_multiplier": 0.96,
                "herding_multiplier": 1.22,
                "institutional_multiplier": 1.0,
                "value_multiplier": 0.84,
                "liquidity_shift": 0.08,
                "momentum_shift": factors["retail_herding"] * 0.12,
                "dominant_narrative": top_labels[min(1, len(top_labels) - 1)],
            },
            {
                "name": "conviction_test",
                "ratio": 0.24,
                "news_multiplier": 0.82,
                "herding_multiplier": 0.94,
                "institutional_multiplier": 1.15,
                "value_multiplier": 1.08,
                "liquidity_shift": -0.02,
                "momentum_shift": -factors["downside_risk"] * 0.08,
                "dominant_narrative": top_labels[min(2, len(top_labels) - 1)],
            },
            {
                "name": "close_repricing",
                "ratio": 0.20,
                "news_multiplier": 0.72,
                "herding_multiplier": 0.86,
                "institutional_multiplier": 1.08,
                "value_multiplier": 1.16,
                "liquidity_shift": -0.06,
                "momentum_shift": -factors["valuation_temperature"] * 0.1,
                "dominant_narrative": top_labels[min(3, len(top_labels) - 1)],
            },
        ]
        blueprint: List[Dict[str, Any]] = []
        cursor = 0
        for segment in segments:
            span = max(1, int(total_ticks * segment["ratio"]))
            end_tick = min(total_ticks, cursor + span)
            blueprint.append({
                **segment,
                "start_tick": cursor,
                "end_tick": end_tick,
            })
            cursor = end_tick
        if blueprint:
            blueprint[-1]["end_tick"] = total_ticks
        return blueprint

    @staticmethod
    def _build_archetype_biases(factors: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        return {
            "fomo_momentum": {
                "world_alignment": round(_clamp(factors["retail_herding"] * 0.8 + factors["tape_momentum_seed"] * 0.6, -1.2, 1.4), 4),
                "activation_boost": round(_clamp((factors["liquidity_temperature"] - 1) * 0.35 + factors["narrative_temperature"] * 0.18, -0.2, 0.45), 4),
            },
            "macro_news": {
                "world_alignment": round(_clamp(factors["policy_pressure"] * 0.95 + factors["sector_heat"] * 0.4, -1.3, 1.4), 4),
                "activation_boost": round(_clamp(abs(factors["policy_pressure"]) * 0.22 + abs(factors["sector_heat"]) * 0.1, 0.0, 0.4), 4),
            },
            "fundamental": {
                "world_alignment": round(_clamp(factors["institutional_conviction"] * 0.7 - factors["valuation_temperature"] * 0.45, -1.3, 1.2), 4),
                "activation_boost": round(_clamp(abs(factors["institutional_conviction"]) * 0.18 + factors["downside_risk"] * 0.08, 0.0, 0.35), 4),
            },
            "mean_reversion": {
                "world_alignment": round(_clamp(factors["downside_risk"] * 0.55 - factors["tape_momentum_seed"] * 0.3, -1.0, 1.1), 4),
                "activation_boost": round(_clamp(factors["valuation_temperature"] * 0.1 + factors["downside_risk"] * 0.18, 0.0, 0.35), 4),
            },
            "passive_retail": {
                "world_alignment": round(_clamp(factors["institutional_conviction"] * 0.25 + factors["retail_herding"] * 0.2, -0.6, 0.8), 4),
                "activation_boost": round(_clamp((factors["liquidity_temperature"] - 1) * 0.12, -0.05, 0.18), 4),
            },
        }

    @staticmethod
    def _dominant_style(policy_pressure: float, retail_herding: float, institutional_conviction: float, valuation_temperature: float) -> str:
        if retail_herding > 0.55 and valuation_temperature > 0.35:
            return "crowd_chasing"
        if institutional_conviction > 0.45 and policy_pressure > 0.25:
            return "policy_trend"
        if institutional_conviction < -0.25 and policy_pressure < -0.2:
            return "risk_off"
        return "balanced_rotation"


class PopulationBuilder:
    ARCHETYPE_WEIGHTS = {
        "fomo_momentum": 0.30,
        "macro_news": 0.25,
        "fundamental": 0.20,
        "mean_reversion": 0.15,
        "passive_retail": 0.10,
    }
    AGE_WEIGHTS = {
        "18-24": 0.12,
        "25-34": 0.28,
        "35-44": 0.30,
        "45-54": 0.20,
        "55+": 0.10,
    }
    RISK_WEIGHTS = {"high": 0.30, "medium": 0.50, "low": 0.20}
    WEALTH_WEIGHTS = {
        "starter": 0.35,
        "accumulator": 0.40,
        "mid_wealth": 0.18,
        "high_wealth": 0.07,
    }
    CASH_RANGES = {
        "starter": (20000, 120000),
        "accumulator": (120000, 500000),
        "mid_wealth": (500000, 1500000),
        "high_wealth": (1500000, 5000000),
    }
    HOLDING_FRACTIONS = {
        "starter": (0.0, 0.35),
        "accumulator": (0.1, 0.55),
        "mid_wealth": (0.2, 0.65),
        "high_wealth": (0.25, 0.75),
    }

    @classmethod
    def build_population(cls, scenario: MarketScenario, world_state: Optional[Dict[str, Any]] = None) -> List[AgentProfile]:
        seed = scenario.seed if scenario.seed is not None else sum(ord(char) for char in scenario.ticker) + scenario.agent_count
        rng = random.Random(seed)
        archetype_weights = cls.ARCHETYPE_WEIGHTS.copy()
        for key, value in scenario.trader_mix_overrides.items():
            if key in archetype_weights:
                archetype_weights[key] = max(0.0, float(value))
        archetype_weights = _normalize_weights(archetype_weights)
        regime_factors = (world_state or {}).get("regime_factors", {})
        archetype_biases = (world_state or {}).get("archetype_biases", {})
        retail_herding = float(regime_factors.get("retail_herding", 0.0))
        institutional_conviction = float(regime_factors.get("institutional_conviction", 0.0))
        downside_risk = float(regime_factors.get("downside_risk", 0.0))

        agents: List[AgentProfile] = []
        for agent_id in range(1, scenario.agent_count + 1):
            archetype = _weighted_choice(rng, archetype_weights)
            age_band = _weighted_choice(rng, cls.AGE_WEIGHTS)
            risk_appetite = _weighted_choice(rng, cls.RISK_WEIGHTS)
            wealth_stage = _weighted_choice(rng, cls.WEALTH_WEIGHTS)
            cash_low, cash_high = cls.CASH_RANGES[wealth_stage]
            cash = rng.uniform(cash_low, cash_high)
            holding_low, holding_high = cls.HOLDING_FRACTIONS[wealth_stage]
            holding_fraction = rng.uniform(holding_low, holding_high)
            holdings = int((cash * holding_fraction) / max(scenario.starting_price, 1))
            cash = max(1000.0, cash - holdings * scenario.starting_price)
            conviction = rng.uniform(0.35, 0.85)
            risk_factor = {"high": 1.0, "medium": 0.75, "low": 0.5}[risk_appetite]
            activation_boost = float(archetype_biases.get(archetype, {}).get("activation_boost", 0.0))
            trade_frequency = _clamp(rng.uniform(0.08, 0.22) * risk_factor + activation_boost * 0.07, 0.03, 0.32)
            stop_loss = _clamp(rng.uniform(0.15, 0.45) * (1.1 if risk_appetite == "low" else 0.85), 0.08, 0.5)
            dip_buy = _clamp(rng.uniform(0.1, 0.55) + (0.08 if archetype == "mean_reversion" else 0.0), 0.05, 0.7)
            news_sensitivity = _clamp(rng.uniform(0.3, 1.0) + (0.3 if archetype == "macro_news" else 0.0) + max(0.0, institutional_conviction) * 0.08, 0.2, 1.5)
            herd_sensitivity = _clamp(rng.uniform(0.15, 1.0) + (0.35 if archetype == "fomo_momentum" else 0.0) + max(0.0, retail_herding) * 0.1, 0.1, 1.6)
            momentum_bias = _clamp(rng.uniform(-0.3, 1.0) + (0.55 if archetype == "fomo_momentum" else 0.0) + retail_herding * 0.08, -0.6, 1.7)
            fundamental_bias = _clamp(rng.uniform(0.1, 1.0) + (0.7 if archetype == "fundamental" else 0.0) + abs(downside_risk) * 0.05, 0.05, 1.85)
            anchor_shift = rng.uniform(-0.18, 0.18)
            if scenario.market_regime == "bullish":
                anchor_shift += 0.03
            elif scenario.market_regime == "bearish":
                anchor_shift -= 0.03
            anchor_shift += institutional_conviction * 0.04
            fundamental_anchor = max(0.5, scenario.starting_price * (1 + anchor_shift))
            influence = round(rng.uniform(0.4, 1.6) * (1.15 if wealth_stage in {"mid_wealth", "high_wealth"} else 1.0), 4)
            display_name = f"{age_band}/{archetype}/{wealth_stage}"
            agents.append(
                AgentProfile(
                    agent_id=agent_id,
                    archetype=archetype,
                    age_band=age_band,
                    risk_appetite=risk_appetite,
                    wealth_stage=wealth_stage,
                    cash=round(cash, 2),
                    holdings=holdings,
                    average_cost=round(scenario.starting_price, 4),
                    conviction=round(conviction, 4),
                    trade_frequency=round(trade_frequency, 4),
                    stop_loss_tendency=round(stop_loss, 4),
                    dip_buy_tendency=round(dip_buy, 4),
                    news_sensitivity=round(news_sensitivity, 4),
                    herd_sensitivity=round(herd_sensitivity, 4),
                    momentum_bias=round(momentum_bias, 4),
                    fundamental_bias=round(fundamental_bias, 4),
                    fundamental_anchor=round(fundamental_anchor, 4),
                    influence_weight=influence,
                    display_name=display_name,
                )
            )
        return agents

    @staticmethod
    def summarize_population(agents: List[AgentProfile]) -> Dict[str, Any]:
        def count_by(field_name: str) -> Dict[str, int]:
            counts: Dict[str, int] = defaultdict(int)
            for agent in agents:
                counts[getattr(agent, field_name)] += 1
            return dict(sorted(counts.items(), key=lambda item: item[0]))

        return {
            "agent_count": len(agents),
            "archetypes": count_by("archetype"),
            "age_bands": count_by("age_band"),
            "risk_appetite": count_by("risk_appetite"),
            "wealth_stage": count_by("wealth_stage"),
            "average_cash": round(sum(agent.cash for agent in agents) / max(len(agents), 1), 2),
            "average_holdings": round(sum(agent.holdings for agent in agents) / max(len(agents), 1), 2),
        }


class PriceImpactEngine:
    TICKS_PER_DAY = 48

    def __init__(
        self,
        scenario: MarketScenario,
        agents: List[AgentProfile],
        shocks: List[MarketShock],
        sentiment_signals: List[SentimentSignal],
        world_state: Optional[Dict[str, Any]] = None,
    ):
        self.scenario = scenario
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
        self.archetype_biases = self.world_state.get("archetype_biases", {})

    def _resolve_float_reference(self, band: str) -> float:
        mapping = {
            "small": 8_000_000,
            "mid": 25_000_000,
            "large": 90_000_000,
            "mega": 240_000_000,
        }
        return mapping.get((band or "").lower(), 25_000_000)

    def run(self, progress_callback=None) -> Tuple[List[SimulationTick], Dict[str, Any]]:
        price = max(0.5, self.scenario.starting_price)
        day_open = price
        recent_peak = price
        ticks: List[SimulationTick] = []
        action_totals = Counter()
        archetype_contribution = Counter()

        for tick_index in range(self.total_ticks):
            if tick_index % self.TICKS_PER_DAY == 0:
                day_open = price
            trading_day = tick_index // self.TICKS_PER_DAY + 1
            intraday_slot = tick_index % self.TICKS_PER_DAY
            shock_bias, sector_bias, dominant_headline = self._shock_state(tick_index)
            crowd_sentiment, crowd_buzz = self._sentiment_state(tick_index)
            momentum = 0.0 if not ticks else sum(item.return_pct for item in ticks[-3:]) / max(len(ticks[-3:]), 1)
            recent_peak = max(recent_peak, price)
            world_context = self._world_state_at(tick_index)
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
            intraday_limit = 0.1
            proposed_price = max(0.5, price * (1 + _clamp(raw_return, -0.035, 0.035)))
            day_upper = day_open * (1 + intraday_limit)
            day_lower = day_open * (1 - intraday_limit)
            new_price = _clamp(proposed_price, day_lower, day_upper)
            tick_return = (new_price - price) / max(price, 1e-6)
            price = round(new_price, 4)

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

        summary = {
            "action_totals": dict(action_totals),
            "archetype_contribution": dict(archetype_contribution),
        }
        return ticks, summary

    def _shock_state(self, tick_index: int) -> Tuple[float, float, str]:
        ticker_bias = 0.0
        sector_bias = 0.0
        dominant_headline = ""
        dominant_strength = 0.0
        for shock in self.shocks:
            if not (shock.start_tick <= tick_index < shock.start_tick + shock.duration_ticks):
                continue
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
        if not self.sentiment_signals:
            return 0.0, 0.0
        index = min(len(self.sentiment_signals) - 1, int(tick_index / max(self.total_ticks / len(self.sentiment_signals), 1)))
        signal = self.sentiment_signals[index]
        return signal.sentiment_score, signal.buzz_score

    def _session_factor(self, slot: int) -> float:
        if slot < 6:
            return 1.18
        if slot < 18:
            return 0.95
        if slot < 30:
            return 0.82
        if slot < 40:
            return 0.9
        return 1.12

    def _world_state_at(self, tick_index: int) -> Dict[str, Any]:
        defaults = {
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
        self,
        price: float,
        slot: int,
        momentum: float,
        shock_bias: float,
        sector_bias: float,
        crowd_sentiment: float,
        crowd_buzz: float,
        recent_peak: float,
        world_context: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], int, int]:
        actions: List[Dict[str, Any]] = []
        net_demand = 0
        volume = 0
        session_factor = self._session_factor(slot) * world_context["activation_temperature"]
        for agent in self.agents:
            archetype_activation = float(self.archetype_biases.get(agent.archetype, {}).get("activation_boost", 0.0))
            if self.rng.random() > agent.trade_frequency * session_factor * (1 + archetype_activation):
                continue
            valuation_gap = (agent.fundamental_anchor - price) / max(price, 1e-6)
            drawdown = (recent_peak - price) / max(recent_peak, 1e-6)
            score = self._decision_score(
                agent=agent,
                momentum=momentum,
                valuation_gap=valuation_gap,
                shock_bias=shock_bias,
                sector_bias=sector_bias,
                crowd_sentiment=crowd_sentiment,
                crowd_buzz=crowd_buzz,
                drawdown=drawdown,
                world_context=world_context,
            )
            threshold = 0.16 + (0.08 if agent.risk_appetite == "low" else 0.0)
            action = "hold"
            signed_quantity = 0
            cash_fraction = _clamp(agent.conviction * 0.18 + abs(score) * 0.15, 0.05, 0.42)
            if score > threshold and agent.cash > price * 100:
                budget = agent.cash * cash_fraction
                quantity = max(0, int(budget / max(price, 1)))
                if quantity > 0:
                    cost = quantity * price
                    previous_value = agent.average_cost * agent.holdings
                    agent.cash -= cost
                    agent.holdings += quantity
                    agent.average_cost = (previous_value + cost) / max(agent.holdings, 1)
                    action = "buy"
                    signed_quantity = quantity
            elif score < -threshold and agent.holdings > 0:
                quantity = max(0, int(agent.holdings * _clamp(abs(score) * 0.55, 0.08, 0.45)))
                if quantity > 0:
                    proceeds = quantity * price
                    agent.cash += proceeds
                    agent.holdings -= quantity
                    action = "sell"
                    signed_quantity = -quantity
            agent.conviction = _clamp(agent.conviction * 0.992 + score * 0.028, 0.08, 1.15)
            if action != "hold" or self.rng.random() < 0.16:
                actions.append(
                    {
                        "agent_id": agent.agent_id,
                        "agent_name": agent.display_name,
                        "archetype": agent.archetype,
                        "action": action,
                        "signed_quantity": signed_quantity,
                        "cash": round(agent.cash, 2),
                        "holdings": agent.holdings,
                        "world_narrative": world_context["dominant_narrative"],
                    }
                )
            net_demand += signed_quantity
            volume += abs(signed_quantity)
        return actions, net_demand, volume

    def _decision_score(
        self,
        agent: AgentProfile,
        momentum: float,
        valuation_gap: float,
        shock_bias: float,
        sector_bias: float,
        crowd_sentiment: float,
        crowd_buzz: float,
        drawdown: float,
        world_context: Dict[str, Any],
    ) -> float:
        news_component = shock_bias * agent.news_sensitivity
        herd_component = crowd_sentiment * agent.herd_sensitivity + min(crowd_buzz / 10, 1.8) * 0.08
        momentum_component = momentum * agent.momentum_bias
        value_component = valuation_gap * agent.fundamental_bias
        archetype_world_bias = float(self.archetype_biases.get(agent.archetype, {}).get("world_alignment", 0.0))
        world_news = world_context["policy_pressure"] * agent.news_sensitivity * 0.55
        world_herd = world_context["retail_herding"] * agent.herd_sensitivity * 0.7
        world_institutional = world_context["institutional_conviction"] * 0.55
        world_value = -world_context["valuation_temperature"] * 0.4
        world_tape = world_context["tape_momentum_bias"] * 0.45
        score = 0.0
        if agent.archetype == "fomo_momentum":
            score = momentum_component * 1.8 + herd_component * 1.5 + news_component * 0.85 + sector_bias * 0.4 + world_herd * 1.1 + world_tape * 0.9
        elif agent.archetype == "macro_news":
            score = news_component * 1.65 + sector_bias * 0.95 + herd_component * 0.55 + momentum_component * 0.4 + world_news * 1.15 + world_institutional * 0.45
        elif agent.archetype == "fundamental":
            score = value_component * 1.75 + news_component * 0.55 - herd_component * 0.25 + world_institutional * 0.7 + world_value * 0.9
        elif agent.archetype == "mean_reversion":
            score = -momentum_component * 1.15 + drawdown * (0.7 + agent.dip_buy_tendency) + value_component * 0.9 + news_component * 0.2 - world_tape * 0.45 + world_value * 0.55
        else:
            score = value_component * 0.75 + news_component * 0.35 + herd_component * 0.2 + world_institutional * 0.25
        score += archetype_world_bias * 0.35
        if drawdown > agent.stop_loss_tendency and agent.holdings > 0:
            score -= drawdown * (1.1 if agent.risk_appetite == "low" else 0.85)
        score -= world_context["downside_risk"] * (0.15 if agent.archetype == "mean_reversion" else 0.28)
        return _clamp(score, -2.8, 2.8)


class MarketAnalystService:
    def __init__(self):
        self.enabled = bool(Config.LLM_API_KEY)

    def generate_narrative(self, scenario: MarketScenario, results: Dict[str, Any]) -> str:
        if self.enabled:
            try:
                client = LLMClient()
                prompt = [
                    {"role": "system", "content": "你是A股市场仿真分析师。只能根据提供的数据生成结论，不要虚构外部事实。输出简洁中文 Markdown。"},
                    {"role": "user", "content": json.dumps({
                        "scenario": scenario.to_dict(),
                        "metrics": results.get("metrics", {}),
                        "world_summary": results.get("world_state", {}).get("world_summary", {}),
                        "dominant_narratives": results.get("world_state", {}).get("dominant_narratives", [])[:5],
                        "event_markers": results.get("event_markers", []),
                        "population_summary": results.get("population_summary", {}),
                        "xueqiu_summary": results.get("xueqiu_summary", {}),
                    }, ensure_ascii=False)},
                ]
                return client.chat(prompt, temperature=0.35, max_tokens=1200)
            except Exception as exc:
                logger.warning("LLM 生成市场报告失败，回退规则摘要: %s", exc)
        metrics = results.get("metrics", {})
        events = results.get("event_markers", [])[:3]
        archetypes = results.get("population_summary", {}).get("archetypes", {})
        world_summary = results.get("world_state", {}).get("world_summary", {})
        top_narrative = world_summary.get("top_narrative", "市场主线")
        strongest = max(archetypes.items(), key=lambda item: item[1])[0] if archetypes else "fomo_momentum"
        lines = [
            f"# {scenario.stock_name} 仿真简报",
            "",
            f"- 标的: `{scenario.ticker}` / {scenario.sector_name}",
            f"- 市场设定: {scenario.market_regime}，{scenario.horizon_days} 个交易日，{scenario.agent_count} 个代理人",
            f"- 区间收益: {metrics.get('total_return_pct', 0)}%",
            f"- 最大回撤: {metrics.get('max_drawdown_pct', 0)}%",
            f"- 年化波动代理值: {metrics.get('realized_volatility_pct', 0)}%",
            f"- 主导人群: {strongest}",
            f"- 平行市场主线: {top_narrative}",
            "",
            "## 走势解读",
            f"本轮路径主要由{'情绪扩散' if abs(results.get('xueqiu_summary', {}).get('average_sentiment', 0)) > 0.15 else '新闻脉冲'}驱动，"
            f"在{scenario.market_regime}环境下，价格与成交量形成了{'同步放大' if metrics.get('turnover_ratio', 0) > 1.1 else '偏谨慎'}的特征。",
        ]
        if events:
            lines.append("")
            lines.append("## 关键事件")
            for event in events:
                lines.append(
                    f"- T{event.get('tick_index')} {event.get('label')} | "
                    f"影响={event.get('impact_score')} | 价格={event.get('price')}"
                )
        return "\n".join(lines)

    def answer_question(self, question: str, scenario: MarketScenario, results: Dict[str, Any], history: List[Dict[str, str]]) -> str:
        if self.enabled:
            try:
                client = LLMClient()
                messages = [
                    {"role": "system", "content": "你是A股市场仿真分析师。只能根据给定仿真结果回答，若数据中没有就明确说明。回答中文，简洁。"},
                    {"role": "user", "content": json.dumps({
                        "scenario": scenario.to_dict(),
                        "metrics": results.get("metrics", {}),
                        "world_summary": results.get("world_state", {}).get("world_summary", {}),
                        "dominant_narratives": results.get("world_state", {}).get("dominant_narratives", [])[:6],
                        "event_markers": results.get("event_markers", [])[:12],
                        "population_summary": results.get("population_summary", {}),
                        "xueqiu_summary": results.get("xueqiu_summary", {}),
                        "question": question,
                        "history": history[-6:],
                    }, ensure_ascii=False)},
                ]
                return client.chat(messages, temperature=0.2, max_tokens=800)
            except Exception as exc:
                logger.warning("LLM 回答市场问答失败，回退规则问答: %s", exc)

        metrics = results.get("metrics", {})
        lower_question = question.lower()
        if "回撤" in question:
            return f"本次仿真的最大回撤为 {metrics.get('max_drawdown_pct', 0)}%，主要发生在高情绪时段后的需求回吐。"
        if "波动" in question or "风险" in question:
            return f"本次路径的波动代理值为 {metrics.get('realized_volatility_pct', 0)}%，换手率约 {metrics.get('turnover_ratio', 0)}，属于 {scenario.market_regime} 环境下的 {'高' if metrics.get('realized_volatility_pct', 0) > 20 else '中低'} 波动态。"
        if "雪球" in question or "情绪" in question or "fomo" in lower_question:
            xueqiu = results.get("xueqiu_summary", {})
            return f"雪球情绪均值约 {xueqiu.get('average_sentiment', 0)}，热度均值 {xueqiu.get('average_buzz', 0)}。情绪抬升阶段与价格加速段基本重合，FOMO 群体放大了成交和斜率。"
        if "世界" in question or "主线" in question or "叙事" in question:
            world = results.get("world_state", {})
            top = world.get("world_summary", {}).get("top_narrative", "暂无明显主线")
            style = world.get("world_summary", {}).get("dominant_market_style", "balanced_rotation")
            return f"当前 world_state 的主线是“{top}”，市场风格偏 {style}。这会通过散户 herding、机构 conviction 和流动性温度共同影响价格路径。"
        if "谁" in question or "哪些" in question or "主导" in question:
            archetypes = results.get("population_summary", {}).get("archetypes", {})
            top = sorted(archetypes.items(), key=lambda item: item[1], reverse=True)[:3]
            return "本次人群构成最多的是: " + "、".join(f"{name}({count})" for name, count in top)
        return (
            f"{scenario.stock_name} 在本次仿真中的区间收益为 {metrics.get('total_return_pct', 0)}%，"
            f"期末价格 {metrics.get('ending_price', scenario.starting_price)}，"
            f"最大回撤 {metrics.get('max_drawdown_pct', 0)}%。如果你想看情绪、事件或人群贡献，我可以继续拆解。"
        )


class MarketSimulationService:
    _threads: Dict[str, threading.Thread] = {}
    _lock = threading.Lock()

    def __init__(self):
        self.eastmoney = EastmoneyNewsAdapter()
        self.xueqiu = XueqiuSentimentAdapter()
        self.analyst = MarketAnalystService()

    def build_world_state(self, run_id: str) -> MarketRun:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        run.status = MarketRunStatus.BUILDING_WORLD
        run.current_phase = "building_world_state"
        run.error = None
        MarketRunManager.save_run(run)

        uploads = self._load_uploads(run.scenario.optional_upload_ids)
        upload_texts = [upload.extracted_text for upload in uploads]
        deduped_news, sentiment_signals, source_health = self._collect_market_seeds(run.scenario, upload_texts)
        world_state = WorldStateBuilder.build(
            scenario=run.scenario,
            news_items=deduped_news,
            sentiment_signals=sentiment_signals,
            upload_texts=upload_texts,
            source_health=source_health,
        )
        MarketRunManager.write_json(run_id, "world_state.json", world_state.to_dict())
        run.status = MarketRunStatus.WORLD_READY
        run.current_phase = "world_state_ready"
        run.world_summary = world_state.world_summary
        MarketRunManager.save_run(run)
        return run

    def prepare_run(self, run_id: str) -> MarketRun:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        world_state = MarketRunManager.read_json(run_id, "world_state.json")
        if not world_state:
            run = self.build_world_state(run_id)
            world_state = MarketRunManager.read_json(run_id, "world_state.json", {})
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        run.status = MarketRunStatus.PREPARING
        run.current_phase = "preparing_simulation_inputs"
        run.error = None
        MarketRunManager.save_run(run)

        uploads = self._load_uploads(run.scenario.optional_upload_ids)
        upload_texts = [upload.extracted_text for upload in uploads]
        deduped_news = [NewsItem(**item) for item in world_state.get("seed_inputs", {}).get("news_items", [])]
        sentiment_signals = [SentimentSignal(**signal) for signal in world_state.get("seed_inputs", {}).get("sentiment_signals", [])]
        shocks = ShockBuilder.build(run.scenario, deduped_news, upload_texts)
        population = PopulationBuilder.build_population(run.scenario, world_state=world_state)
        population_summary = PopulationBuilder.summarize_population(population)

        preparation_payload = {
            "scenario": run.scenario.to_dict(),
            "world_state": world_state,
            "news_items": [item.to_dict() for item in deduped_news],
            "sentiment_signals": [signal.to_dict() for signal in sentiment_signals],
            "market_shocks": [shock.to_dict() for shock in shocks],
            "population": [agent.to_dict() for agent in population],
            "population_summary": population_summary,
            "upload_summaries": [
                {
                    "upload_id": upload.upload_id,
                    "filename": upload.filename,
                    "summary": re.sub(r"\s+", " ", upload.extracted_text)[:240],
                    "sentiment": _score_sentiment(upload.extracted_text),
                }
                for upload in uploads
            ],
            "source_health": {
                **world_state.get("source_health", {}),
                "eastmoney_news_count": len(deduped_news),
                "xueqiu_mode": sentiment_signals[0].metadata.get("mode", "live") if sentiment_signals else world_state.get("source_health", {}).get("xueqiu_mode", "fallback"),
                "xueqiu_authenticated": XueqiuBrowserAuthService.is_authenticated(),
            },
            "world_summary": world_state.get("world_summary", {}),
        }
        MarketRunManager.write_json(run_id, "prepared_context.json", preparation_payload)
        run.status = MarketRunStatus.READY
        run.current_phase = "ready_for_simulation"
        run.world_summary = world_state.get("world_summary", {})
        run.preparation_summary = {
            "news_count": len(deduped_news),
            "shock_count": len(shocks),
            "sentiment_windows": len(sentiment_signals),
            "population_summary": population_summary,
            "source_health": preparation_payload["source_health"],
            "world_summary": world_state.get("world_summary", {}),
        }
        MarketRunManager.save_run(run)
        return run

    def start_run(self, run_id: str) -> MarketRun:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        prepared = MarketRunManager.read_json(run_id, "prepared_context.json")
        if not prepared:
            raise ValueError("请先准备仿真环境")
        with self._lock:
            thread = self._threads.get(run_id)
            if thread and thread.is_alive():
                return run
            run.status = MarketRunStatus.RUNNING
            run.current_phase = "simulation_running"
            run.error = None
            run.simulation_summary = {
                "current_tick": 0,
                "total_ticks": max(1, run.scenario.horizon_days) * PriceImpactEngine.TICKS_PER_DAY,
                "progress_percent": 0,
                "live_series": [],
                "recent_events": [],
            }
            MarketRunManager.save_run(run)
            thread = threading.Thread(target=self._run_in_background, args=(run_id,), daemon=True)
            self._threads[run_id] = thread
            thread.start()
        return run

    def _run_in_background(self, run_id: str) -> None:
        run = MarketRunManager.get_run(run_id)
        prepared = MarketRunManager.read_json(run_id, "prepared_context.json")
        if not run or not prepared:
            return
        try:
            agents = [AgentProfile(**agent) for agent in prepared["population"]]
            shocks = [
                MarketShock(
                    shock_type=item["type"],
                    start_tick=item["start_tick"],
                    duration_ticks=item["duration_ticks"],
                    direction=item["direction"],
                    strength=item["strength"],
                    affected_scope=item["affected_scope"],
                    headline=item["headline"],
                    source_refs=item.get("source_refs", []),
                )
                for item in prepared["market_shocks"]
            ]
            sentiment_signals = [SentimentSignal(**signal) for signal in prepared["sentiment_signals"]]
            engine = PriceImpactEngine(
                run.scenario,
                agents,
                shocks,
                sentiment_signals,
                world_state=prepared.get("world_state", {}),
            )

            def on_progress(current_tick: int, total_ticks: int, preview_ticks: List[SimulationTick]) -> None:
                live_series = [tick.to_dict() for tick in preview_ticks]
                run_state = MarketRunManager.get_run(run_id)
                if not run_state:
                    return
                run_state.simulation_summary = {
                    "current_tick": current_tick,
                    "total_ticks": total_ticks,
                    "progress_percent": round(current_tick / max(total_ticks, 1) * 100, 2),
                    "live_series": live_series,
                    "recent_events": [tick["top_actions"][:4] for tick in live_series[-3:]],
                    "current_price": live_series[-1]["price"] if live_series else run.scenario.starting_price,
                }
                MarketRunManager.save_run(run_state)

            ticks, engine_summary = engine.run(progress_callback=on_progress)
            results = self._build_results(run, prepared, ticks, engine_summary)
            MarketRunManager.write_json(run_id, "results.json", results)
            run = MarketRunManager.get_run(run_id)
            if not run:
                return
            run.status = MarketRunStatus.COMPLETED
            run.current_phase = "results_ready"
            run.simulation_summary = {
                "current_tick": len(ticks),
                "total_ticks": len(ticks),
                "progress_percent": 100,
                "live_series": [tick.to_dict() for tick in ticks[-12:]],
                "recent_events": results["event_markers"][:6],
                "current_price": results["metrics"]["ending_price"],
            }
            run.result_summary = {
                "metrics": results["metrics"],
                "event_markers": results["event_markers"][:6],
            }
            MarketRunManager.save_run(run)
        except Exception as exc:
            logger.exception("市场仿真执行失败 run=%s", run_id)
            run = MarketRunManager.get_run(run_id)
            if run:
                run.status = MarketRunStatus.FAILED
                run.current_phase = "simulation_failed"
                run.error = str(exc)
                MarketRunManager.save_run(run)

    def get_run_status(self, run_id: str) -> Dict[str, Any]:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        return run.to_dict()

    def get_results(self, run_id: str) -> Dict[str, Any]:
        results = MarketRunManager.read_json(run_id, "results.json")
        if not results:
            raise ValueError("结果尚未生成")
        return results

    def chat(self, run_id: str, message: str) -> Dict[str, Any]:
        run = MarketRunManager.get_run(run_id)
        results = self.get_results(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        answer = self.analyst.answer_question(message, run.scenario, results, run.chat_history)
        run.chat_history.append({"role": "user", "content": message})
        run.chat_history.append({"role": "assistant", "content": answer})
        MarketRunManager.save_run(run)
        return {
            "answer": answer,
            "chat_history": run.chat_history[-10:],
        }

    def _dedupe_news(self, news_items: List[NewsItem]) -> List[NewsItem]:
        seen = set()
        deduped: List[NewsItem] = []
        for item in news_items:
            key = (item.title, item.url)
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    def _load_uploads(self, upload_ids: List[str]) -> List[Any]:
        uploads = [MarketUploadManager.get_upload(upload_id) for upload_id in upload_ids]
        return [upload for upload in uploads if upload]

    def _collect_market_seeds(
        self,
        scenario: MarketScenario,
        upload_texts: List[str],
    ) -> Tuple[List[NewsItem], List[SentimentSignal], Dict[str, Any]]:
        ticker_keyword = scenario.stock_name or scenario.ticker
        sector_keyword = scenario.sector_name
        ticker_news = self.eastmoney.fetch_news(ticker_keyword, "ticker", limit=8)
        sector_news = self.eastmoney.fetch_news(sector_keyword, "sector", limit=6)
        deduped_news = self._dedupe_news(ticker_news + sector_news)
        sentiment_signals = self.xueqiu.fetch_signals(scenario, deduped_news)
        return deduped_news, sentiment_signals, {
            "eastmoney_news_count": len(deduped_news),
            "xueqiu_mode": sentiment_signals[0].metadata.get("mode", "live") if sentiment_signals else "fallback",
            "xueqiu_authenticated": XueqiuBrowserAuthService.is_authenticated(),
            "upload_context_count": len(upload_texts),
        }

    def _build_results(
        self,
        run: MarketRun,
        prepared: Dict[str, Any],
        ticks: List[SimulationTick],
        engine_summary: Dict[str, Any],
    ) -> Dict[str, Any]:
        series = [tick.to_dict() for tick in ticks]
        prices = [tick.price for tick in ticks] or [run.scenario.starting_price]
        volumes = [tick.volume for tick in ticks] or [0]
        sentiments = [tick.market_sentiment for tick in ticks] or [0.0]
        buzz = [tick.xueqiu_buzz for tick in ticks] or [0.0]
        peak = prices[0]
        max_drawdown = 0.0
        for price in prices:
            peak = max(peak, price)
            drawdown = (peak - price) / max(peak, 1e-6)
            max_drawdown = max(max_drawdown, drawdown)
        returns = [tick.return_pct for tick in ticks]
        realized_vol = math.sqrt(sum(value * value for value in returns) / max(len(returns), 1)) * math.sqrt(48 * 20) * 100
        total_return = (prices[-1] - prices[0]) / max(prices[0], 1e-6) * 100
        turnover_ratio = sum(volumes) / max(run.scenario.agent_count * 400, 1)
        event_markers = self._extract_event_markers(
            ticks,
            prepared.get("market_shocks", []),
            prepared.get("world_state", {}),
        )
        results = {
            "scenario": run.scenario.to_dict(),
            "world_state": prepared.get("world_state", {}),
            "series": series,
            "metrics": {
                "starting_price": round(prices[0], 4),
                "ending_price": round(prices[-1], 4),
                "total_return_pct": round(total_return, 2),
                "max_drawdown_pct": round(max_drawdown * 100, 2),
                "realized_volatility_pct": round(realized_vol, 2),
                "turnover_ratio": round(turnover_ratio, 2),
                "average_volume": round(sum(volumes) / max(len(volumes), 1), 2),
            },
            "population_summary": prepared.get("population_summary", {}),
            "news_items": prepared.get("news_items", []),
            "xueqiu_summary": {
                "average_sentiment": round(sum(signal["sentiment_score"] for signal in prepared.get("sentiment_signals", [])) / max(len(prepared.get("sentiment_signals", [])), 1), 4),
                "average_buzz": round(sum(signal["buzz_score"] for signal in prepared.get("sentiment_signals", [])) / max(len(prepared.get("sentiment_signals", [])), 1), 4),
                "signals": prepared.get("sentiment_signals", []),
            },
            "event_markers": event_markers,
            "engine_summary": engine_summary,
        }
        results["narrative_report"] = self.analyst.generate_narrative(run.scenario, results)
        return results

    def _extract_event_markers(
        self,
        ticks: List[SimulationTick],
        shocks: List[Dict[str, Any]],
        world_state: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        markers: List[Dict[str, Any]] = []
        for shock in shocks[:10]:
            tick_index = min(max(0, shock.get("start_tick", 0)), max(len(ticks) - 1, 0))
            price = ticks[tick_index].price if ticks else 0
            markers.append(
                {
                    "tick_index": tick_index,
                    "label": shock.get("headline", "市场事件"),
                    "impact_score": round(shock.get("direction", 0) * shock.get("strength", 0), 4),
                    "price": price,
                    "scope": shock.get("affected_scope", "ticker"),
                }
            )
        largest_moves = sorted(ticks, key=lambda item: abs(item.return_pct), reverse=True)[:4]
        for tick in largest_moves:
            markers.append(
                {
                    "tick_index": tick.tick_index,
                    "label": "盘中大幅波动",
                    "impact_score": round(tick.return_pct, 4),
                    "price": tick.price,
                    "scope": "ticker",
                }
            )
        for segment in world_state.get("tick_blueprint", [])[:4]:
            tick_index = min(max(0, segment.get("start_tick", 0)), max(len(ticks) - 1, 0))
            price = ticks[tick_index].price if ticks else 0
            markers.append(
                {
                    "tick_index": tick_index,
                    "label": f"世界状态切换: {segment.get('dominant_narrative', segment.get('name', '市场主线'))}",
                    "impact_score": round(segment.get("herding_multiplier", 1.0) - segment.get("value_multiplier", 1.0), 4),
                    "price": price,
                    "scope": "world",
                }
            )
        markers.sort(key=lambda item: (item["tick_index"], -abs(item["impact_score"])))
        deduped: List[Dict[str, Any]] = []
        seen = set()
        for marker in markers:
            key = (marker["tick_index"], marker["label"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(marker)
        return deduped[:12]
