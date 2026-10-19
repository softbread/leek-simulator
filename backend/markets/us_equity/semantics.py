"""Conservative English social scoring with negation and ambiguity handling."""
import re

POSITIVE = {"bullish", "bull", "rally", "breakout", "upgrade", "beat", "beats", "buyback", "growth", "moon", "long"}
NEGATIVE = {"bearish", "bear", "crash", "dump", "downgrade", "miss", "misses", "fraud", "bankruptcy", "dilution", "short"}


def score_text(text):
    words = re.findall(r"[a-z]+", text.lower())
    if re.search(r"(?:^|\s)/s(?:\s|$)|sarcasm", text.lower()):
        return 0.0
    score = 0
    matches = 0
    for index, word in enumerate(words):
        direction = 1 if word in POSITIVE else -1 if word in NEGATIVE else 0
        if not direction:
            continue
        if any(token in {"not", "never", "no"} for token in words[max(0, index - 2):index]):
            direction *= -1
        score += direction
        matches += 1
    return max(-1.0, min(1.0, score / max(matches, 1)))


def mentions_stock(text, ticker, stock_name):
    # Upper-case ticker tokens or full company names reduce common-word ambiguity.
    return bool(re.search(r"\$" + re.escape(ticker) + r"(?![A-Za-z])", text, re.I)
                or (len(ticker) > 2 and re.search(r"(?<![A-Za-z])" + re.escape(ticker) + r"(?![A-Za-z])", text))
                or (len(stock_name) >= 3 and re.search(r"\b" + re.escape(stock_name) + r"\b", text, re.I)))


def social_signals(posts, scenario):
    from market_sim.types import SentimentSignal
    from market_sim.sentiment import parse_time
    from collections import defaultdict
    import math
    groups = defaultdict(list)
    seen = set()
    for post in posts:
        scope = post.get("scope", "ticker")
        if scope not in {"ticker", "sector", "market"}:
            raise ValueError("Social scope must be ticker, sector or market")
        text = str(post.get("text", "")).strip()
        if not text or (scope == "ticker" and not mentions_stock(text, scenario.ticker, scenario.stock_name)):
            continue
        stamp = parse_time(post.get("published_at"), scenario.market)
        signature = (scope, re.sub(r"\W+", "", text.lower()))
        if signature in seen:
            continue
        seen.add(signature)
        groups[(post.get("source", "imported_social"), scope)].append((text, stamp))
    result = []
    for (source, scope), samples in groups.items():
        # Keep timestamps per post; old samples cannot inherit a new post's timestamp.
        for text, stamp in samples:
            result.append(SentimentSignal(source, stamp.isoformat(), stamp.isoformat(), scenario.ticker,
                scenario.sector_name, score_text(text), math.log1p(len(samples)) * 3,
                re.findall(r"\$[A-Z][A-Z0-9.]*", text)[:4],
                {"mode": "social", "scope": scope, "sample_size": 1, "timestamp_basis": "published_at"}))
    return result


def normalize_news(raw, scenario):
    from market_sim.types import NewsItem
    from market_sim.sentiment import parse_time
    import math
    item = dict(raw)
    item.setdefault("summary", "")
    item.setdefault("url", "")
    item.setdefault("sentiment", score_text(item.get("title", "") + " " + item["summary"]))
    item.setdefault("relevance_score", 0.8)
    item["published_at"] = parse_time(item["published_at"], scenario.market).isoformat()
    if item.get("affected_scope") not in {"ticker", "sector", "market"}:
        raise ValueError("US news requires affected_scope=ticker/sector/market")
    for key in ("sentiment", "relevance_score"):
        item[key] = float(item[key])
        if not math.isfinite(item[key]) or not (-1 <= item[key] <= 1 if key == "sentiment" else 0 <= item[key] <= 1):
            raise ValueError(f"Invalid news {key}")
    return NewsItem(**item)
