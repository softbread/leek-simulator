"""
市场模拟数据模型与持久化
"""

import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from market_sim.types import MarketScenario

from ..config import Config
from ..utils.file_parser import FileParser


class MarketRunStatus(str, Enum):
    CREATED = "created"
    BUILDING_WORLD = "building_world"
    WORLD_READY = "world_ready"
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class MarketUpload:
    upload_id: str
    filename: str
    path: str
    size: int
    extracted_text: str
    uploaded_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "upload_id": self.upload_id,
            "filename": self.filename,
            "path": self.path,
            "size": self.size,
            "extracted_text": self.extracted_text,
            "uploaded_at": self.uploaded_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketUpload":
        return cls(
            upload_id=data["upload_id"],
            filename=data["filename"],
            path=data["path"],
            size=data["size"],
            extracted_text=data.get("extracted_text", ""),
            uploaded_at=data.get("uploaded_at", datetime.now().isoformat()),
        )


@dataclass
class MarketRun:
    run_id: str
    scenario: MarketScenario
    status: MarketRunStatus = MarketRunStatus.CREATED
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    error: Optional[str] = None
    current_phase: str = "scenario_created"
    world_summary: Dict[str, Any] = field(default_factory=dict)
    preparation_summary: Dict[str, Any] = field(default_factory=dict)
    simulation_summary: Dict[str, Any] = field(default_factory=dict)
    result_summary: Dict[str, Any] = field(default_factory=dict)
    chat_history: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "scenario": self.scenario.to_dict(),
            "status": self.status.value if isinstance(self.status, MarketRunStatus) else self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "current_phase": self.current_phase,
            "world_summary": self.world_summary,
            "preparation_summary": self.preparation_summary,
            "simulation_summary": self.simulation_summary,
            "result_summary": self.result_summary,
            "chat_history": self.chat_history,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketRun":
        status = data.get("status", MarketRunStatus.CREATED.value)
        if isinstance(status, str):
            status = MarketRunStatus(status)
        return cls(
            run_id=data["run_id"],
            scenario=MarketScenario.from_dict(data["scenario"]),
            status=status,
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
            error=data.get("error"),
            current_phase=data.get("current_phase", "scenario_created"),
            world_summary=data.get("world_summary", {}),
            preparation_summary=data.get("preparation_summary", {}),
            simulation_summary=data.get("simulation_summary", {}),
            result_summary=data.get("result_summary", {}),
            chat_history=data.get("chat_history", []),
        )


class MarketUploadManager:
    UPLOADS_DIR = os.path.join(Config.UPLOAD_FOLDER, "market_uploads")

    @classmethod
    def _ensure_dir(cls) -> None:
        os.makedirs(cls.UPLOADS_DIR, exist_ok=True)

    @classmethod
    def _get_meta_path(cls, upload_id: str) -> str:
        return os.path.join(cls.UPLOADS_DIR, f"{upload_id}.json")

    @classmethod
    def save_upload(cls, file_storage) -> MarketUpload:
        cls._ensure_dir()
        original_filename = file_storage.filename or "upload.txt"
        ext = os.path.splitext(original_filename)[1].lower() or ".txt"
        upload_id = f"upload_{uuid.uuid4().hex[:12]}"
        stored_path = os.path.join(cls.UPLOADS_DIR, f"{upload_id}{ext}")
        file_storage.save(stored_path)
        extracted_text = FileParser.extract_text(stored_path)
        upload = MarketUpload(
            upload_id=upload_id,
            filename=original_filename,
            path=stored_path,
            size=os.path.getsize(stored_path),
            extracted_text=extracted_text,
        )
        cls._atomic_write_json(cls._get_meta_path(upload_id), upload.to_dict())
        return upload

    @classmethod
    def get_upload(cls, upload_id: str) -> Optional[MarketUpload]:
        meta_path = cls._get_meta_path(upload_id)
        if not os.path.exists(meta_path):
            return None
        with open(meta_path, "r", encoding="utf-8") as f:
            return MarketUpload.from_dict(json.load(f))


class MarketRunManager:
    RUNS_DIR = os.path.join(Config.UPLOAD_FOLDER, "market_runs")

    @classmethod
    def _ensure_dir(cls) -> None:
        os.makedirs(cls.RUNS_DIR, exist_ok=True)

    @classmethod
    def get_run_dir(cls, run_id: str) -> str:
        cls._ensure_dir()
        run_dir = os.path.join(cls.RUNS_DIR, run_id)
        os.makedirs(run_dir, exist_ok=True)
        return run_dir

    @classmethod
    def get_artifact_path(cls, run_id: str, name: str) -> str:
        return os.path.join(cls.get_run_dir(run_id), name)

    @classmethod
    def _state_path(cls, run_id: str) -> str:
        return os.path.join(cls.get_run_dir(run_id), "state.json")

    @classmethod
    def create_run(cls, scenario: MarketScenario) -> MarketRun:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        run = MarketRun(run_id=run_id, scenario=scenario)
        cls.save_run(run)
        cls._copy_uploads(run)
        return run

    @classmethod
    def _copy_uploads(cls, run: MarketRun) -> None:
        upload_ids = run.scenario.optional_upload_ids
        if not upload_ids:
            return
        attachments_dir = cls.get_artifact_path(run.run_id, "attachments")
        os.makedirs(attachments_dir, exist_ok=True)
        copied = []
        for upload_id in upload_ids:
            upload = MarketUploadManager.get_upload(upload_id)
            if not upload or not os.path.exists(upload.path):
                continue
            target_path = os.path.join(attachments_dir, os.path.basename(upload.path))
            shutil.copy2(upload.path, target_path)
            copied.append({
                "upload_id": upload.upload_id,
                "filename": upload.filename,
                "path": target_path,
                "size": upload.size,
            })
        if copied:
            cls.write_json(run.run_id, "attachments.json", copied)

    @classmethod
    def save_run(cls, run: MarketRun) -> None:
        run.updated_at = datetime.now().isoformat()
        cls._atomic_write_json(cls._state_path(run.run_id), run.to_dict())

    @classmethod
    def get_run(cls, run_id: str) -> Optional[MarketRun]:
        state_path = cls._state_path(run_id)
        if not os.path.exists(state_path):
            return None
        with open(state_path, "r", encoding="utf-8") as f:
            return MarketRun.from_dict(json.load(f))

    @classmethod
    def list_runs(cls, limit: int = 50) -> List[MarketRun]:
        cls._ensure_dir()
        runs: List[MarketRun] = []
        for run_id in os.listdir(cls.RUNS_DIR):
            run = cls.get_run(run_id)
            if run:
                runs.append(run)
        runs.sort(key=lambda item: item.created_at, reverse=True)
        return runs[:limit]

    @classmethod
    def write_json(cls, run_id: str, filename: str, payload: Any) -> str:
        path = cls.get_artifact_path(run_id, filename)
        cls._atomic_write_json(path, payload)
        return path

    @classmethod
    def read_json(cls, run_id: str, filename: str, default: Any = None) -> Any:
        path = cls.get_artifact_path(run_id, filename)
        if not os.path.exists(path):
            return default
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _atomic_write_json(path: str, payload: Any) -> None:
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
