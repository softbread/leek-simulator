"""Network seed providers for the market application."""
import json
import math
from datetime import datetime, timezone
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List
from market_sim.utils import _clean_html_text, _clamp, _extract_topics, _normalize_ticker, _now_iso, _score_sentiment
from market_sim.types import MarketScenario, NewsItem, SentimentSignal
from ..xueqiu_browser import XueqiuBrowserAuthService
from ...utils.logger import get_logger

logger = get_logger("mirofish.market.seeds")

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
        market_statuses = XueqiuBrowserAuthService.fetch_search_statuses(scenario.market_keyword, count=12)
        stock_page_snippets = XueqiuBrowserAuthService.scrape_stock_page(_normalize_ticker(scenario.ticker), sample_limit=10)

        ticker_texts = list(dict.fromkeys(self._extract_texts(ticker_statuses) + stock_page_snippets))
        sector_texts = list(dict.fromkeys(self._extract_texts(sector_statuses)))
        market_texts = list(dict.fromkeys(self._extract_texts(market_statuses)))

        signals: List[SentimentSignal] = []
        if ticker_texts:
            ticker_topics = _extract_topics(ticker_texts)
            ticker_sentiment = sum(_score_sentiment(text) for text in ticker_texts) / max(len(ticker_texts), 1)
            signals.append(
                SentimentSignal(
                    source="xueqiu",
                    window_start=datetime.now(timezone.utc).isoformat(),
                    window_end=datetime.now(timezone.utc).isoformat(),
                    ticker=_normalize_ticker(scenario.ticker),
                    sector=scenario.sector_name,
                    sentiment_score=round(_clamp(ticker_sentiment, -1.0, 1.0), 4),
                    buzz_score=round(math.log1p(len(ticker_texts)) * 4.2, 4),
                    topic_tags=ticker_topics or [scenario.stock_name],
                    metadata={"mode": "browser", "scope": "ticker", "sample_size": len(ticker_texts), "timestamp_basis": "captured_at"},
                )
            )
        if sector_texts:
            sector_topics = _extract_topics(sector_texts)
            sector_sentiment = sum(_score_sentiment(text) for text in sector_texts) / max(len(sector_texts), 1)
            signals.append(
                SentimentSignal(
                    source="xueqiu",
                    window_start=datetime.now(timezone.utc).isoformat(),
                    window_end=datetime.now(timezone.utc).isoformat(),
                    ticker=_normalize_ticker(scenario.ticker),
                    sector=scenario.sector_name,
                    sentiment_score=round(_clamp(sector_sentiment, -1.0, 1.0), 4),
                    buzz_score=round(math.log1p(len(sector_texts)) * 3.6, 4),
                    topic_tags=sector_topics or [scenario.sector_name],
                    metadata={"mode": "browser", "scope": "sector", "sample_size": len(sector_texts), "timestamp_basis": "captured_at"},
                )
            )
        if market_texts:
            stamp = datetime.now(timezone.utc).isoformat()
            signals.append(SentimentSignal(
                source="xueqiu", window_start=stamp, window_end=stamp,
                ticker="", sector="", sentiment_score=round(sum(_score_sentiment(text) for text in market_texts) / len(market_texts), 4),
                buzz_score=round(math.log1p(len(market_texts)) * 4.2, 4),
                topic_tags=_extract_topics(market_texts),
                metadata={"mode": "browser", "scope": "market", "sample_size": len(market_texts),
                          "query": scenario.market_keyword, "timestamp_basis": "captured_at"},
            ))
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

    def _build_fallback_signals(self, scenario, news_items):
        # A news-derived proxy is one starting observation, not a future mood path.
        baseline = sum(item.sentiment for item in news_items) / max(len(news_items), 1)
        stamp = _now_iso()
        return [SentimentSignal(
            source="news_proxy", window_start=stamp, window_end=stamp,
            ticker=_normalize_ticker(scenario.ticker), sector=scenario.sector_name,
            sentiment_score=round(baseline, 4), buzz_score=0.0,
            topic_tags=_extract_topics([item.title for item in news_items], limit=4),
            metadata={"mode": "fallback", "sample_size": 0, "scope": "ticker"},
        )]

