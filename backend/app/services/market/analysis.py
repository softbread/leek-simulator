"""Optional LLM analysis of saved simulation evidence."""
import json
from typing import Any, Dict, List
from market_sim.types import MarketScenario
from ...config import Config
from ...utils.llm_client import LLMClient
from ...utils.logger import get_logger

logger = get_logger("mirofish.market.analysis")

class MarketAnalystService:
    def __init__(self):
        self.enabled = bool(Config.LLM_API_KEY)

    def generate_narrative(self, scenario: MarketScenario, results: Dict[str, Any]) -> str:
        if self.enabled:
            try:
                client = LLMClient()
                prompt = [
                    {"role": "system", "content": "你是市场仿真分析师。识别 scenario.market 的市场类型；US 市场已外部做基本面筛选，不推断估值。只能根据提供的数据生成结论，不要虚构外部事实。输出简洁中文 Markdown。"},
                    {"role": "user", "content": json.dumps({
                        "scenario": scenario.to_dict(),
                        "metrics": results.get("metrics", {}),
                        "current_sentiment": results.get("current_sentiment", {}),
                        "cycle_summary": results.get("cycle_summary", {}),
                        "social_dynamics": results.get("engine_summary", {}),
                        "world_timeline": results.get("world_timeline", [])[::12],
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
        snapshot = results.get("current_sentiment", {})
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
            f"- 起点情绪: {snapshot.get('label', '未提供')}，来源={snapshot.get('source_mode', 'unknown')}，时间={snapshot.get('as_of', 'unknown')}",
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
                    {"role": "system", "content": "你是市场仿真分析师。识别 scenario.market 的市场类型；US 不做基本面分析。只能根据给定仿真结果回答，若数据中没有就明确说明。回答中文，简洁。"},
                    {"role": "user", "content": json.dumps({
                        "scenario": scenario.to_dict(),
                        "metrics": results.get("metrics", {}),
                        "world_summary": results.get("world_state", {}).get("world_summary", {}),
                        "dominant_narratives": results.get("world_state", {}).get("dominant_narratives", [])[:6],
                        "event_markers": results.get("event_markers", [])[:12],
                        "population_summary": results.get("population_summary", {}),
                        "xueqiu_summary": results.get("xueqiu_summary", {}),
                        "question": question,
                        "cycle_summary": results.get("cycle_summary", {}),
                        "current_sentiment": results.get("current_sentiment", {}),
                        "social_dynamics": results.get("engine_summary", {}),
                        "world_timeline": results.get("world_timeline", [])[::12],
                        "history": history[-6:],
                    }, ensure_ascii=False)},
                ]
                return client.chat(messages, temperature=0.2, max_tokens=800)
            except Exception as exc:
                logger.warning("LLM 回答市场问答失败，回退规则问答: %s", exc)

        metrics = results.get("metrics", {})
        lower_question = question.lower()
        if "周期" in question or "涨潮" in question or "退潮" in question:
            cycle = results.get("cycle_summary", {})
            return (f"大盘周期观测：{cycle.get('market', {}).get('label', '证据不足')}。"
                    f"个股模拟各阶段 tick 数：{cycle.get('stock_phase_counts', {})}。"
                    "阶段由市场宽度或模拟资金状态推断，并非固定日历，也不保证反转。")
        if "当前" in question or "起点" in question or "快照" in question:
            snapshot = results.get("current_sentiment", {})
            channels = snapshot.get("channels", {})
            return (f"起点快照时间 {snapshot.get('as_of', '未知')}，情绪 {snapshot.get('label', '未知')}，"
                    f"分数 {snapshot.get('sentiment_score', 0)}，来源 {snapshot.get('source_mode', 'unknown')}。"
                    f"大盘分数 {channels.get('market', {}).get('sentiment_score', '缺失')}，"
                    f"个股分数 {channels.get('stock', {}).get('sentiment_score', '缺失')}，两者来源独立。"
                    f"真实讨论样本 {snapshot.get('discussion_samples', 0)}；之后的价格与情绪曲线均来自模拟。")
        if "回撤" in question:
            return f"本次仿真的最大回撤为 {metrics.get('max_drawdown_pct', 0)}%，主要发生在高情绪时段后的需求回吐。"
        if "波动" in question or "风险" in question:
            return f"本次路径的波动代理值为 {metrics.get('realized_volatility_pct', 0)}%，换手率约 {metrics.get('turnover_ratio', 0)}，属于 {scenario.market_regime} 环境下的 {'高' if metrics.get('realized_volatility_pct', 0) > 20 else '中低'} 波动态。"
        if "雪球" in question or "情绪" in question or "fomo" in lower_question:
            xueqiu = results.get("xueqiu_summary", {})
            social = results.get("engine_summary", {}).get("social_dynamics", {})
            platform = "美股社交" if scenario.market == "us_equity" else "雪球"
            return (f"{platform}情绪均值约 {xueqiu.get('average_sentiment', 0)}，热度均值 {xueqiu.get('average_buzz', 0)}。"
                    f"模拟内群体反馈期末为 {social.get('final_feedback', 0)}，"
                    f"共记录 {social.get('observed_actions', 0)} 次决策；单次路径不能证明因果关系。")
        if "世界" in question or "主线" in question or "叙事" in question:
            world = results.get("world_state", {})
            top = world.get("world_summary", {}).get("top_narrative", "暂无明显主线")
            style = world.get("world_summary", {}).get("dominant_market_style", "balanced_rotation")
            return f"当前 world_state 的主线是“{top}”，市场风格偏 {style}。这会通过散户 herding、机构 conviction 和流动性温度共同影响价格路径。"
        if "谁" in question or "哪些" in question or "主导" in question:
            contribution = results.get("engine_summary", {}).get("archetype_contribution", {})
            top = sorted(contribution.items(), key=lambda item: abs(item[1]), reverse=True)[:3]
            return "按模拟净买卖股数排序: " + "、".join(f"{name}({quantity:+d})" for name, quantity in top)
        return (
            f"{scenario.stock_name} 在本次仿真中的区间收益为 {metrics.get('total_return_pct', 0)}%，"
            f"期末价格 {metrics.get('ending_price', scenario.starting_price)}，"
            f"最大回撤 {metrics.get('max_drawdown_pct', 0)}%。如果你想看情绪、事件或人群贡献，我可以继续拆解。"
        )

