"""Compatibility imports; implementation lives in market_sim and services.market."""
import time
import urllib.request

from market_sim.types import (
    MarketScenario, NewsItem, SentimentSignal, MarketShock, MarketWorldState,
    AgentProfile, SimulationTick,
)
from market_sim.world import ShockBuilder, WorldStateBuilder
from market_sim.population import PopulationBuilder
from market_sim.engine import PriceImpactEngine
from .market.seeds import EastmoneyNewsAdapter, XueqiuSentimentAdapter
from .market.analysis import MarketAnalystService
from .market.runs import MarketSimulationService
from .xueqiu_browser import XueqiuBrowserAuthService
