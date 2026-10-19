"""Run a normalized market configuration without starting the web application."""

import argparse
import json
from pathlib import Path

from .adapters import MiroFishMarketAdapter


def main():
    parser = argparse.ArgumentParser(description="Run a market environment for a MiroFish host")
    parser.add_argument("config", type=Path, help="JSON configuration with market_scenario")
    parser.add_argument("--output", required=True, type=Path, help="Destination JSON artifact")
    args = parser.parse_args()
    adapter = MiroFishMarketAdapter.from_config(json.loads(args.config.read_text(encoding="utf-8")))
    adapter.run()
    args.output.write_text(json.dumps(adapter.export(), ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
