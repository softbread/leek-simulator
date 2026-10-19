"""
A股市场仿真 API
"""

import os
import math
import re
import traceback
from flask import jsonify, request

from . import market_bp
from ..config import Config
from ..models.market import MarketRunManager, MarketScenario, MarketUploadManager
from ..services.market.runs import MarketSimulationService
from ..services.xueqiu_browser import XueqiuBrowserAuthService
from ..utils.logger import get_logger
from markets import PROFILES, get_profile

logger = get_logger("mirofish.api.market")


def allowed_file(filename: str) -> bool:
    if not filename or "." not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    return ext in Config.ALLOWED_EXTENSIONS


def _parse_scenario(payload):
    market = payload.get("market", "cn_equity")
    profile = get_profile(market)
    ticker = payload.get("ticker", "").strip().upper()
    stock_name = payload.get("stock_name", "").strip()
    sector_name = payload.get("sector_name", "").strip()
    starting_price = float(payload.get("starting_price", 0))
    float_shares_band = payload.get("float_shares_band", "mid").strip().lower()
    market_regime = payload.get("market_regime", "neutral").strip().lower()
    horizon_days = int(payload.get("horizon_days", 3))
    agent_count = int(payload.get("agent_count", 1000))
    trader_mix_overrides = payload.get("trader_mix_overrides", {}) or {}
    notes = payload.get("notes", "")
    optional_upload_ids = payload.get("optional_upload_ids", []) or []
    seed = payload.get("seed")

    if not ticker or not stock_name or not sector_name:
        raise ValueError("ticker、stock_name、sector_name 为必填字段")
    if not math.isfinite(starting_price) or starting_price <= 0:
        raise ValueError("starting_price 必须大于 0")
    if float_shares_band not in {"small", "mid", "large", "mega"}:
        raise ValueError("float_shares_band 必须是 small / mid / large / mega")
    if market_regime not in {"bullish", "neutral", "bearish", "volatile"}:
        raise ValueError("market_regime 必须是 bullish / neutral / bearish / volatile")
    if horizon_days < 1 or horizon_days > 5:
        raise ValueError("horizon_days 必须在 1 到 5 之间")
    if agent_count < 500 or agent_count > 2000:
        raise ValueError("agent_count 必须在 500 到 2000 之间")
    if seed is not None:
        seed = int(seed)
    if market == "us_equity" and not re.fullmatch(r"[A-Z][A-Z0-9]*(?:[.-][A-Z0-9]+)?", ticker):
        raise ValueError("US ticker must be a symbol such as NVDA or BRK.B")

    return MarketScenario(
        ticker=ticker,
        stock_name=stock_name,
        sector_name=sector_name,
        starting_price=starting_price,
        float_shares_band=float_shares_band,
        market_regime=market_regime,
        horizon_days=horizon_days,
        agent_count=agent_count,
        optional_upload_ids=optional_upload_ids,
        trader_mix_overrides=trader_mix_overrides,
        notes=notes,
        seed=seed,
        market_snapshot=payload.get("market_snapshot", {}),
        market_keyword=payload.get("market_keyword", profile.default_keyword).strip() or profile.default_keyword,
        market=market,
        seed_inputs=payload.get("seed_inputs", {}),
        data_mode=payload.get("data_mode", "live_and_imported"),
    )


@market_bp.route("/profiles", methods=["GET"])
def get_market_profiles():
    return jsonify({"success": True, "data": [profile.public() for profile in PROFILES.values()]})


@market_bp.route("/uploads", methods=["POST"])
def upload_market_documents():
    try:
        files = request.files.getlist("files")
        if not files or all(not file.filename for file in files):
            return jsonify({"success": False, "error": "请至少上传一个文件"}), 400

        uploads = []
        for file in files:
            if not file or not file.filename:
                continue
            if not allowed_file(file.filename):
                return jsonify({"success": False, "error": f"不支持的文件类型: {file.filename}"}), 400
            upload = MarketUploadManager.save_upload(file)
            uploads.append({
                "upload_id": upload.upload_id,
                "filename": upload.filename,
                "size": upload.size,
                "preview": upload.extracted_text[:180],
            })

        return jsonify({"success": True, "data": uploads, "count": len(uploads)})
    except Exception as exc:
        logger.error("上传市场文件失败: %s", exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }), 500


@market_bp.route("/xueqiu/auth/status", methods=["GET"])
def get_xueqiu_auth_status():
    return jsonify({"success": True, "data": XueqiuBrowserAuthService.get_status()})


@market_bp.route("/xueqiu/auth/start", methods=["POST"])
def start_xueqiu_auth():
    try:
        status = XueqiuBrowserAuthService.start_login()
        return jsonify({
            "success": True,
            "data": {
                **status,
                "message": "已打开雪球登录浏览器，请在弹出的窗口中完成登录，然后点击“我已完成登录”。",
            },
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@market_bp.route("/xueqiu/auth/complete", methods=["POST"])
def complete_xueqiu_auth():
    try:
        status = XueqiuBrowserAuthService.complete_login()
        return jsonify({
            "success": True,
            "data": {
                **status,
                "message": "雪球登录态已更新。",
            },
        })
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@market_bp.route("/xueqiu/auth/logout", methods=["POST"])
def logout_xueqiu_auth():
    status = XueqiuBrowserAuthService.logout()
    return jsonify({"success": True, "data": status})


@market_bp.route("/runs", methods=["POST"])
def create_market_run():
    try:
        payload = request.get_json() or {}
        scenario = _parse_scenario(payload)
        run = MarketRunManager.create_run(scenario)
        return jsonify({"success": True, "data": run.to_dict()})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@market_bp.route("/runs", methods=["GET"])
def list_market_runs():
    limit = request.args.get("limit", 20, type=int)
    runs = MarketRunManager.list_runs(limit=limit)
    return jsonify({
        "success": True,
        "data": [run.to_dict() for run in runs],
        "count": len(runs),
    })


@market_bp.route("/runs/<run_id>", methods=["GET"])
def get_market_run(run_id: str):
    run = MarketRunManager.get_run(run_id)
    if not run:
        return jsonify({"success": False, "error": f"市场仿真不存在: {run_id}"}), 404
    return jsonify({
        "success": True,
        "data": {
            **run.to_dict(),
            "world_state": MarketRunManager.read_json(run_id, "world_state.json", {}),
            "prepared_context": MarketRunManager.read_json(run_id, "prepared_context.json", {}),
            "has_results": MarketRunManager.read_json(run_id, "results.json") is not None,
        },
    })


@market_bp.route("/runs/<run_id>/build-world", methods=["POST"])
def build_market_world(run_id: str):
    try:
        service = MarketSimulationService()
        run = service.build_world_state(run_id)
        world_state = MarketRunManager.read_json(run_id, "world_state.json", {})
        return jsonify({
            "success": True,
            "data": {
                **run.to_dict(),
                "world_state": world_state,
            },
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("构建市场世界失败 run=%s error=%s", run_id, exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }), 500


@market_bp.route("/runs/<run_id>/prepare", methods=["POST"])
def prepare_market_run(run_id: str):
    try:
        service = MarketSimulationService()
        run = service.prepare_run(run_id)
        prepared = MarketRunManager.read_json(run_id, "prepared_context.json", {})
        return jsonify({
            "success": True,
            "data": {
                **run.to_dict(),
                "world_state": MarketRunManager.read_json(run_id, "world_state.json", {}),
                "prepared_context": prepared,
            },
        })
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("准备市场仿真失败 run=%s error=%s", run_id, exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }), 500


@market_bp.route("/runs/<run_id>/start", methods=["POST"])
def start_market_run(run_id: str):
    try:
        service = MarketSimulationService()
        run = service.start_run(run_id)
        return jsonify({"success": True, "data": run.to_dict()})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("启动市场仿真失败 run=%s error=%s", run_id, exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }), 500


@market_bp.route("/runs/<run_id>/status", methods=["GET"])
def get_market_run_status(run_id: str):
    try:
        service = MarketSimulationService()
        status = service.get_run_status(run_id)
        return jsonify({"success": True, "data": status})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404


@market_bp.route("/runs/<run_id>/results", methods=["GET"])
def get_market_run_results(run_id: str):
    try:
        service = MarketSimulationService()
        results = service.get_results(run_id)
        return jsonify({"success": True, "data": results})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


@market_bp.route("/runs/<run_id>/chat", methods=["POST"])
def chat_market_run(run_id: str):
    try:
        payload = request.get_json() or {}
        message = (payload.get("message") or "").strip()
        if not message:
            return jsonify({"success": False, "error": "message 不能为空"}), 400
        service = MarketSimulationService()
        result = service.chat(run_id, message)
        return jsonify({"success": True, "data": result})
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("市场分析师问答失败 run=%s error=%s", run_id, exc)
        return jsonify({
            "success": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }), 500


@market_bp.route("/runs/<run_id>/timeline", methods=["GET"])
def get_market_timeline(run_id: str):
    if not MarketRunManager.get_run(run_id):
        return jsonify({"success": False, "error": "市场仿真不存在"}), 404
    return jsonify({"success": True, "data": MarketRunManager.read_json(run_id, "world_timeline.json", [])})


@market_bp.route("/runs/<run_id>/agents/<int:agent_id>", methods=["GET"])
def get_market_agent(run_id: str, agent_id: int):
    agents = MarketRunManager.read_json(run_id, "agent_states.json", [])
    agent = next((item for item in agents if item["profile"]["agent_id"] == agent_id), None)
    if not agent:
        return jsonify({"success": False, "error": "代理人记忆尚未生成或不存在"}), 404
    return jsonify({"success": True, "data": agent})
