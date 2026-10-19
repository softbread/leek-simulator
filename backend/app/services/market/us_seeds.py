"""US-equity news and social ingestion; credentials stay in server configuration."""
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from markets.us_equity.semantics import mentions_stock, social_signals, normalize_news
from market_sim.types import NewsItem, SentimentSignal
from market_sim.sentiment import parse_time
from market_sim.utils import _clean_html_text
from ...config import Config


class USEquitySeedProvider:
    CNBC_RSS = "https://www.cnbc.com/id/100003114/device/rss/rss.html"

    def _read(self, url, token=None):
        headers = {"User-Agent": Config.US_REDDIT_USER_AGENT}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
            return response.read()

    def _news(self, raw, scenario):
        return normalize_news(raw, scenario)

    def _cnbc(self, scenario):
        root = ET.fromstring(self._read(self.CNBC_RSS))
        news = []
        for item in root.findall(".//item")[:40]:
            date = item.findtext("pubDate")
            if not date:
                continue
            title = _clean_html_text(item.findtext("title", ""))
            summary = _clean_html_text(item.findtext("description", ""))
            text = title + " " + summary
            scopes = ["market"]
            if mentions_stock(text, scenario.ticker, scenario.stock_name):
                scopes.append("ticker")
            if scenario.sector_name.lower() in text.lower():
                scopes.append("sector")
            for scope in scopes:
                news.append(self._news({"source": "cnbc", "published_at": parsedate_to_datetime(date).isoformat(),
                    "title": title, "summary": summary, "url": item.findtext("link", ""), "affected_scope": scope}, scenario))
        return news

    def _x(self, query, scope):
        search = f"{query} lang:en -is:retweet"
        url = "https://api.x.com/2/tweets/search/recent?" + urllib.parse.urlencode(
            {"query": search, "max_results": 25, "tweet.fields": "created_at"})
        payload = json.loads(self._read(url, Config.US_X_BEARER_TOKEN))
        return [{"source": "x", "scope": scope, "text": item["text"], "published_at": item["created_at"]}
                for item in payload.get("data", [])]

    def _reddit(self, query, scope):
        url = "https://oauth.reddit.com/search?" + urllib.parse.urlencode(
            {"q": query, "sort": "new", "t": "week", "limit": 25})
        payload = json.loads(self._read(url, Config.US_REDDIT_ACCESS_TOKEN))
        return [{"source": "reddit", "scope": scope,
                 "text": item["data"].get("title", "") + " " + item["data"].get("selftext", ""),
                 "published_at": datetime.fromtimestamp(item["data"]["created_utc"], timezone.utc).isoformat()}
                for item in payload.get("data", {}).get("children", [])]

    def collect(self, scenario):
        seeds = scenario.seed_inputs
        news = [self._news(item, scenario) for item in seeds.get("news_items", [])]
        posts = list(seeds.get("social_posts", []))
        status = {"bloomberg": "imported" if any("bloomberg" in item.source.lower() for item in news) else "not_connected_import_available",
                  "robinhood_social": "imported" if any(item.get("source") == "robinhood_social" for item in posts) else "not_connected_import_available",
                  "cnbc": "disabled", "x": "missing_credentials", "reddit": "missing_credentials"}
        if scenario.data_mode == "live_and_imported":
            try:
                news.extend(self._cnbc(scenario))
                status["cnbc"] = "fetched"
            except Exception as exc:
                status["cnbc"] = f"unavailable:{type(exc).__name__}"
            if Config.US_NEWS_FEED_URL:
                try:
                    payload = json.loads(self._read(Config.US_NEWS_FEED_URL, Config.US_NEWS_FEED_TOKEN))
                    news.extend(self._news(item, scenario) for item in payload.get("news_items", []))
                    status["licensed_news_feed"] = "fetched"
                except Exception as exc:
                    status["licensed_news_feed"] = f"unavailable:{type(exc).__name__}"
            for source, token, fetch in (("x", Config.US_X_BEARER_TOKEN, self._x),
                                          ("reddit", Config.US_REDDIT_ACCESS_TOKEN, self._reddit)):
                if not token:
                    continue
                try:
                    for scope, query in (("ticker", "$" + scenario.ticker if source == "x" else scenario.ticker),
                                          ("sector", scenario.sector_name), ("market", scenario.market_keyword)):
                        posts.extend(fetch(query, scope))
                    status[source] = "fetched"
                except Exception as exc:
                    status[source] = f"unavailable:{type(exc).__name__}"
        else:
            status.update({"x": "disabled", "reddit": "disabled"})
        signals = social_signals(posts, scenario)
        for raw in seeds.get("sentiment_signals", []):
            signal = SentimentSignal(**raw)
            signal.window_start = parse_time(signal.window_start, scenario.market).isoformat()
            signal.window_end = parse_time(signal.window_end, scenario.market).isoformat()
            if signal.metadata.get("scope") not in {"ticker", "sector", "market"}:
                raise ValueError("Imported US sentiment needs metadata.scope")
            if not math.isfinite(signal.sentiment_score) or not -1 <= signal.sentiment_score <= 1 or not math.isfinite(signal.buzz_score) or signal.buzz_score < 0:
                raise ValueError("Invalid imported sentiment scores")
            signals.append(signal)
        return news, signals, {"market": "us_equity", "providers": status,
            "social_posts_received": len(posts), "social_windows": len(signals),
            "fundamentals": "external_filter_only", "data_mode": scenario.data_mode}
