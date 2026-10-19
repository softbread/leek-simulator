"""Run lifecycle and filesystem persistence orchestration."""
import os
import re
import threading
from collections import defaultdict
from functools import wraps
from typing import Any, Dict, List, Tuple
from market_sim.types import MarketScenario, NewsItem, SentimentSignal, SimulationTick
from market_sim.world import ShockBuilder, WorldStateBuilder
from market_sim.population import PopulationBuilder
from market_sim.engine import PriceImpactEngine
from market_sim.adapters import MiroFishMarketAdapter
from market_sim.results import build_results
from market_sim.utils import _score_sentiment
from ...models.market import MarketRun, MarketRunManager, MarketRunStatus, MarketUploadManager
from ...utils.logger import get_logger
from ..xueqiu_browser import XueqiuBrowserAuthService
from .seeds import EastmoneyNewsAdapter, XueqiuSentimentAdapter
from .analysis import MarketAnalystService
from .us_seeds import USEquitySeedProvider
from markets import get_profile

logger = get_logger("mirofish.market.runs")

def serialized_market_operation(method):
    @wraps(method)
    def operation(self, run_id):
        with self._operation_locks[run_id]:
            try:
                return method(self, run_id)
            except ValueError:
                raise
            except Exception as exc:
                run = MarketRunManager.get_run(run_id)
                if run:
                    run.status = MarketRunStatus.FAILED
                    run.current_phase = f"{method.__name__}_failed"
                    run.error = str(exc)
                    MarketRunManager.save_run(run)
                raise
    return operation

class MarketSimulationService:
    _threads: Dict[str, threading.Thread] = {}
    _lock = threading.Lock()
    _operation_locks = defaultdict(threading.RLock)

    def __init__(self, eastmoney=None, xueqiu=None, analyst=None, us_sources=None):
        self.eastmoney = eastmoney if eastmoney is not None else EastmoneyNewsAdapter()
        self.xueqiu = xueqiu if xueqiu is not None else XueqiuSentimentAdapter()
        self.analyst = analyst if analyst is not None else MarketAnalystService()
        self.us_sources = us_sources if us_sources is not None else USEquitySeedProvider()

    @serialized_market_operation
    def build_world_state(self, run_id: str) -> MarketRun:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        if run.status == MarketRunStatus.RUNNING:
            raise ValueError("运行期间不能重建市场世界")
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
        MarketRunManager.write_json(run_id, "sentiment_snapshot.json", world_state.current_sentiment)
        for name in ("prepared_context.json", "results.json", "world_timeline.json",
                     "agent_states.json", "action_ledger.json", "world_final.json"):
            path = MarketRunManager.get_artifact_path(run_id, name)
            if os.path.exists(path):
                os.remove(path)
        run.preparation_summary = {}
        run.simulation_summary = {}
        run.result_summary = {}
        run.chat_history = []
        run.status = MarketRunStatus.WORLD_READY
        run.current_phase = "world_state_ready"
        run.world_summary = world_state.world_summary
        MarketRunManager.save_run(run)
        return run

    @serialized_market_operation
    def prepare_run(self, run_id: str) -> MarketRun:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        if run.status in {MarketRunStatus.RUNNING, MarketRunStatus.COMPLETED}:
            raise ValueError("请重建市场世界后再准备新的仿真")
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
            },
            "world_summary": world_state.get("world_summary", {}),
        }
        if run.scenario.market == "cn_equity":
            preparation_payload["source_health"].update({
                "eastmoney_news_count": len(deduped_news),
                "xueqiu_mode": sentiment_signals[0].metadata.get("mode", "fallback") if sentiment_signals else "fallback",
                "xueqiu_authenticated": XueqiuBrowserAuthService.is_authenticated(),
            })
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

    @serialized_market_operation
    def start_run(self, run_id: str) -> MarketRun:
        run = MarketRunManager.get_run(run_id)
        if not run:
            raise ValueError(f"市场仿真不存在: {run_id}")
        if run.status == MarketRunStatus.COMPLETED:
            return run
        prepared = MarketRunManager.read_json(run_id, "prepared_context.json")
        if not prepared:
            raise ValueError("请先准备仿真环境")
        world = MarketRunManager.read_json(run_id, "world_state.json", {})
        if not world or prepared.get("world_state", {}).get("built_at") != world.get("built_at"):
            raise ValueError("市场世界已变化，请重新准备仿真环境")
        with self._lock:
            thread = self._threads.get(run_id)
            if thread and thread.is_alive():
                return run
            if run.status != MarketRunStatus.READY:
                raise ValueError("请重新准备仿真环境后启动")
            run.status = MarketRunStatus.RUNNING
            run.current_phase = "simulation_running"
            run.error = None
            run.simulation_summary = {
                "current_tick": 0,
                "total_ticks": max(1, run.scenario.horizon_days) * get_profile(run.scenario.market).ticks_per_day,
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
            engine = MiroFishMarketAdapter.from_prepared(prepared)

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
            MarketRunManager.write_json(run_id, "world_timeline.json", engine.world.timeline)
            MarketRunManager.write_json(run_id, "agent_states.json", engine.world.agent_states())
            MarketRunManager.write_json(run_id, "action_ledger.json", engine.world.ledger)
            MarketRunManager.write_json(run_id, "world_final.json", engine.world.snapshot())
            engine_summary["social_dynamics"] = {
                "final_feedback": round(engine.world.feedback, 5),
                "observed_actions": len(engine.world.ledger),
                "remembering_agents": sum(memory["observations"] > 0 for memory in engine.world.memories.values()),
            }
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
            key = (item.title, item.url, item.affected_scope)
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
        if scenario.market == "us_equity":
            news, signals, health = self.us_sources.collect(scenario)
            return self._dedupe_news(news), signals, health
        ticker_keyword = scenario.stock_name or scenario.ticker
        sector_keyword = scenario.sector_name
        ticker_news = self.eastmoney.fetch_news(ticker_keyword, "ticker", limit=8)
        sector_news = self.eastmoney.fetch_news(sector_keyword, "sector", limit=6)
        market_news = self.eastmoney.fetch_news(scenario.market_keyword, "market", limit=8)
        deduped_news = self._dedupe_news(ticker_news + sector_news + market_news)
        sentiment_signals = self.xueqiu.fetch_signals(scenario, deduped_news)
        return deduped_news, sentiment_signals, {
            "eastmoney_news_count": len(deduped_news),
            "xueqiu_mode": sentiment_signals[0].metadata.get("mode", "live") if sentiment_signals else "fallback",
            "xueqiu_authenticated": XueqiuBrowserAuthService.is_authenticated(),
            "upload_context_count": len(upload_texts),
            "market_keyword": scenario.market_keyword,
            "news_by_scope": {scope: sum(item.affected_scope == scope for item in deduped_news)
                              for scope in ("market", "sector", "ticker")},
        }

    def _build_results(self, run, prepared, ticks, engine_summary):
        results = build_results(
            run.scenario, prepared, ticks, engine_summary,
            MarketRunManager.read_json(run.run_id, "world_timeline.json", []),
        )
        results["narrative_report"] = self.analyst.generate_narrative(run.scenario, results)
        return results

