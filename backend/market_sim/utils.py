"""Pure normalization and sampling helpers."""
import html
import random
import re
from collections import Counter
from datetime import datetime
from typing import Dict, List

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


