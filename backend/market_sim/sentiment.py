"""Capture a point-in-time sentiment seed, distinct from simulated future mood."""

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .utils import _clamp
from .dynamics import market_cycle
from markets import get_profile

NEWS_LIFETIME_HOURS = 72.0
SESSION_MINUTES = [9 * 60 + 35 + 5 * n for n in range(24)] + [13 * 60 + 5 + 5 * n for n in range(24)]


def news_lifetime_hours(item):
    lifetime = float(item.metadata.get("sentiment_lifetime_hours", NEWS_LIFETIME_HOURS))
    if not math.isfinite(lifetime) or not 0 < lifetime <= 720:
        raise ValueError("sentiment_lifetime_hours 必须在 0 到 720 小时之间")
    return lifetime


def news_weight(published_at, as_of, lifetime_hours=NEWS_LIFETIME_HOURS, market="cn_equity"):
    age = (as_of - parse_time(published_at, market)).total_seconds() / 3600
    return max(0.0, 1 - age / lifetime_hours) if age >= 0 else 0.0


def forecast_time(as_of, tick_index, market="cn_equity"):
    """Market regular sessions, skipping weekends; no holiday calendar yet."""
    profile = get_profile(market)
    cutoff = parse_time(as_of, market).astimezone(ZoneInfo(profile.timezone))
    day = cutoff.replace(hour=0, minute=0, second=0, microsecond=0)
    index = tick_index
    while True:
        if day.weekday() < 5:
            for minute in profile.session_minutes:
                stamp = day + timedelta(minutes=minute)
                if stamp <= cutoff:
                    continue
                if index == 0:
                    return stamp
                index -= 1
        day += timedelta(days=1)


def parse_time(value, market="cn_equity"):
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        raise ValueError("时间必须是 ISO 日期时间，例如 2026-10-19T15:00:00+08:00") from None
    return stamp.replace(tzinfo=ZoneInfo(get_profile(market).timezone)) if stamp.tzinfo is None else stamp


def validate_snapshot(value, market="cn_equity"):
    if not isinstance(value, dict):
        raise ValueError("market_snapshot 必须是对象")
    cutoff = parse_time(value["as_of"], market) if value.get("as_of") else datetime.now(timezone.utc)
    if cutoff > datetime.now(timezone.utc) + timedelta(minutes=1):
        raise ValueError("行情快照时间不能在未来")
    bars = value.get("recent_prices", [])
    if not isinstance(bars, list) or len(bars) > 500:
        raise ValueError("recent_prices 必须是最多 500 条记录的数组")
    previous = None
    for bar in bars:
        if not isinstance(bar, dict):
            raise ValueError("行情记录必须包含 timestamp、close 和 volume")
        stamp = parse_time(bar.get("timestamp"), market)
        if stamp > cutoff or (previous is not None and stamp <= previous):
            raise ValueError("行情必须按时间递增，且不能晚于快照时间")
        for key in ("close", "volume"):
            try:
                number = float(bar[key])
            except (KeyError, ValueError, TypeError):
                raise ValueError(f"行情缺少有效的 {key}") from None
            if not math.isfinite(number) or number < 0 or (key == "close" and number == 0):
                raise ValueError(f"行情 {key} 无效")
        previous = stamp
    breadth = value.get("market_breadth", [])
    if not isinstance(breadth, list) or len(breadth) > 250:
        raise ValueError("market_breadth 必须是最多 250 条记录的数组")
    previous = None
    for item in breadth:
        if not isinstance(item, dict):
            raise ValueError("market_breadth 记录必须是对象")
        if "source" in item and (not isinstance(item["source"], str) or not item["source"].strip()):
            raise ValueError("市场宽度 source 必须是非空字符串")
        stamp = parse_time(item.get("timestamp"), market)
        if stamp > cutoff or (previous is not None and stamp <= previous):
            raise ValueError("市场宽度数据必须按时间递增且不晚于快照")
        for key in (("advancers", "decliners") if market == "us_equity" else ("advancers", "decliners", "limit_up", "limit_down")):
            number = item.get(key)
            if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number) or number < 0 or int(number) != number:
                raise ValueError(f"市场宽度 {key} 必须为非负整数")
        promotion = item.get("promotion_rate", 0.5)
        if not isinstance(promotion, (int, float)) or not math.isfinite(promotion) or not 0 <= promotion <= 1:
            raise ValueError("promotion_rate 必须在 0 到 1 之间")
        previous = stamp
    return value


def current_seeds(scenario, news, signals, as_of=None):
    cutoff = as_of or (parse_time(scenario.market_snapshot.get("as_of"), scenario.market) if scenario.market_snapshot.get("as_of") else datetime.now(timezone.utc))
    earliest = cutoff - timedelta(days=7)
    accepted_news, accepted_signals = [], []
    excluded = 0
    for item in news:
        try:
            stamp = parse_time(item.published_at, scenario.market)
        except ValueError:
            excluded += 1
            continue
        if 0 < news_weight(item.published_at, cutoff, news_lifetime_hours(item), scenario.market):
            accepted_news.append(item)
        else:
            excluded += 1
    for signal in signals:
        if signal.metadata.get("mode") == "fallback":
            accepted_signals.append(signal)
            continue
        try:
            start, end = parse_time(signal.window_start, scenario.market), parse_time(signal.window_end, scenario.market)
        except ValueError:
            excluded += 1
            continue
        if earliest <= start <= end <= cutoff:
            accepted_signals.append(signal)
        else:
            excluded += 1
    return cutoff, accepted_news, accepted_signals, excluded


def build_snapshot(scenario, news, signals, cutoff, excluded=0):
    observed = [signal for signal in signals if signal.metadata.get("mode") != "fallback"]
    proxy = [signal for signal in signals if signal.metadata.get("mode") == "fallback"]
    def weighted_news(scope=None):
        items = [item for item in news if scope is None or item.affected_scope == scope]
        weights = [news_weight(item.published_at, cutoff, news_lifetime_hours(item), scenario.market)
                   * max(0, item.relevance_score) for item in items]
        return sum(item.sentiment * weight for item, weight in zip(items, weights)) / max(sum(max(0, item.relevance_score) for item in items), 1)
    def discussion(scope):
        items = [signal for signal in observed if signal.metadata.get("scope", "ticker") == scope]
        weights = [math.exp(-(cutoff - parse_time(item.window_end, scenario.market)).total_seconds() / (24 * 3600)) for item in items]
        return sum(item.sentiment_score * weight for item, weight in zip(items, weights)) / max(sum(weights), 1)
    stock, sector, market = discussion("ticker"), discussion("sector"), discussion("market")
    channels = {}
    for name, scope in (("market", "market"), ("stock", "ticker"), ("sector", "sector")):
        channel_news = [item for item in news if item.affected_scope == scope]
        samples = [item for item in observed if item.metadata.get("scope", "ticker") == scope]
        news_score = weighted_news(scope)
        social_weight = get_profile(scenario.market).ticker_social_weight if scope == "ticker" else (0.55 if scenario.market == "us_equity" else 0.7)
        score = social_weight * discussion(scope) + (1 - social_weight) * news_score if samples else news_score
        channels[name] = {
            "sentiment_score": round(_clamp(score, -1, 1), 5),
            "discussion_sentiment": round(discussion(scope), 5), "news_sentiment": round(news_score, 5),
            "source_mode": "observed" if samples else "news_proxy" if channel_news else "insufficient",
            "discussion_samples": sum(item.metadata.get("sample_size", 0) for item in samples),
            "sources": sorted({item.source for item in samples + channel_news}),
            "news_items": [{"title": item.title, "url": item.url, "published_at": item.published_at,
                            "sentiment_lifetime_hours": news_lifetime_hours(item)} for item in channel_news],
            "discussion_queries": sorted({item.metadata.get("query", scope) for item in samples}),
        }
    breadth = scenario.market_snapshot.get("market_breadth", [])
    cycle = market_cycle(breadth, scenario.market)
    if breadth:
        broad = channels["market"]
        score = cycle["pressure"]
        broad["sentiment_score"] = round(score if broad["source_mode"] == "insufficient" else broad["sentiment_score"] * 0.7 + score * 0.3, 5)
        if broad["source_mode"] == "insufficient":
            broad["source_mode"] = "market_breadth"
        broad["sources"] = sorted(set(broad["sources"] + [item.get("source", "manual_market_breadth") for item in breadth]))
        broad["breadth_pressure"] = score
    news_score = weighted_news()
    weights = {"stock": 0.6, "market": 0.25, "sector": 0.15}
    available = [name for name in weights if channels[name]["source_mode"] != "insufficient"]
    score = sum(channels[name]["sentiment_score"] * weights[name] for name in available) / max(sum(weights[name] for name in available), 1e-9)
    bars = scenario.market_snapshot.get("recent_prices", [])
    momentum = float(bars[-1]["close"]) / float(bars[0]["close"]) - 1 if len(bars) > 1 else 0
    prior_volume = sum(float(bar["volume"]) for bar in bars[:-1]) / max(len(bars) - 1, 1)
    volume_ratio = float(bars[-1]["volume"]) / prior_volume if len(bars) > 1 and prior_volume > 0 else 1.0
    warnings = []
    if not observed:
        warnings.append("没有有效的真实讨论样本；情绪依据新闻或盘面指标代理，不能视作全市场真实情绪。")
    if any(item.metadata.get("timestamp_basis") == "captured_at" for item in observed):
        warnings.append("讨论窗口采用抓取时间，未逐条验证原帖发布时间，请复核内容时效。")
    if len(bars) < 2:
        warnings.append("未提供足够的近期行情，价格动量未参与初始化。")
    elif abs(float(bars[-1]["close"]) / scenario.starting_price - 1) > 0.02:
        warnings.append("最新行情与初始价格相差超过 2%，请检查快照时间和价格口径。")
    if bars and (cutoff - parse_time(bars[-1]["timestamp"], scenario.market)).total_seconds() > 72 * 3600:
        warnings.append("最近一条行情距快照超过 72 小时，请确认是否停牌、休市或数据过期。")
    if excluded:
        warnings.append(f"已排除 {excluded} 条新闻影响已到期（默认 72 小时）、讨论超过 7 天、晚于快照或时间无效的输入。")
    for name, label in (("market", "大盘"), ("stock", "个股")):
        if channels[name]["source_mode"] == "insufficient":
            warnings.append(f"缺少{label}情绪来源；不会用其他层级数据冒充。")
    if breadth and (cutoff - parse_time(breadth[-1]["timestamp"], scenario.market)).total_seconds() > 72 * 3600:
        warnings.append("市场宽度观测已超过 72 小时，周期标签可能过期；没有自动补全未来大盘数据。")
    buzz = sum(item.buzz_score for item in observed) / max(len(observed), 1)
    if not observed and proxy:
        buzz = sum(item.buzz_score for item in proxy) / len(proxy)
    return {
        "as_of": cutoff.isoformat(), "sentiment_score": round(_clamp(score, -1, 1), 5),
        "label": "数据不足" if not observed and not news and not breadth else "偏多" if score > 0.15 else "偏空" if score < -0.15 else "中性/分歧",
        "source_mode": "observed" if observed else "news_proxy" if news else "market_breadth" if breadth else "insufficient",
        "stock_discussion_sentiment": round(stock, 5), "sector_discussion_sentiment": round(sector, 5),
        "market_discussion_sentiment": round(market, 5), "channels": channels,
        "market_news_sentiment": round(weighted_news("market"), 5),
        "news_sentiment": round(news_score, 5), "buzz_score": round(buzz, 5),
        "ticker_news_sentiment": round(weighted_news("ticker"), 5),
        "sector_news_sentiment": round(weighted_news("sector"), 5),
        "discussion_samples": sum(item.metadata.get("sample_size", 0) for item in observed),
        "observed_windows": len(observed), "news_count": len(news),
        "price_momentum": round(momentum, 5), "price_points": len(bars),
        "volume_ratio": round(volume_ratio, 5),
        "recent_prices": bars, "warnings": warnings,
        "method": "scoped_keywords_v2", "lookback_days": 7, "news_lifetime_hours": NEWS_LIFETIME_HOURS,
        "market_cycle": cycle, "market_breadth": breadth,
        "market": scenario.market, "timezone": get_profile(scenario.market).timezone,
    }
