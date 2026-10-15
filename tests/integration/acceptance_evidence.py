"""验收运行目录与阶段证据；只管理当前运行拥有的文件。"""

from __future__ import annotations

import json
import hashlib
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.service.infrastructure.filesystem.atomic_files import discard_temporary_file, replace_path_with_retry


def create_run_directory(root: Path, run_id: str) -> Path:
    """在 root 下新建 run_id 目录，拒绝路径穿越和覆盖历史验收。"""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("run-id 必须是单个字母数字目录名，可含点、下划线和连字符")
    directory = (root.resolve() / run_id).resolve()
    if directory.parent != root.resolve():
        raise ValueError("验收目录必须位于指定根目录内")
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def write_evidence(path: Path, payload: dict[str, Any]) -> None:
    """把 payload 原子写入 path，避免中断留下半个 JSON。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        replace_path_with_retry(temporary, path)
    finally:
        discard_temporary_file(temporary)


def record_case_progress(run_dir: Path, stage: str, **changes: Any) -> dict[str, Any]:
    """逐阶段保存资源身份，即使后续转换失败仍可续查原训练和产物。"""
    path = run_dir / "progress.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    payload.update(changes)
    payload.update(stage=stage, updated_at=datetime.now(UTC).isoformat())
    write_evidence(path, payload)
    return payload


def read_case_progress(run_dir: Path) -> dict[str, Any] | None:
    """读取已落盘阶段证据；不存在时返回 None。"""
    path = run_dir / "progress.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def record_case_failure(run_dir: Path, error: Exception) -> dict[str, Any]:
    """保存失败终态和失败前阶段，保留模型及任务身份。"""
    previous = read_case_progress(run_dir) or {}
    return record_case_progress(
        run_dir, "failed", status="failed", error=str(error),
        failed_stage=previous.get("stage", "preparation"),
    )


def copy_pretrained_assets(
    *, source_root: Path, destination_root: Path, model_version_ids: set[str],
) -> list[dict[str, Any]]:
    """只复制选中版本的 manifest 和 checkpoint，拒绝目录越界、缺失和重复身份。"""
    source_root, destination_root = source_root.resolve(), destination_root.resolve()
    if (destination_root == source_root or source_root.is_relative_to(destination_root)
            or destination_root.is_relative_to(source_root)):
        raise ValueError("验收存储不得覆盖预训练资产来源")
    selected: dict[str, tuple[Path, Path]] = {}
    for manifest in (source_root / "models/pretrained").rglob("manifest.json"):
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        version_id = payload.get("model_version_id")
        if version_id not in model_version_ids:
            continue
        checkpoint = (manifest.parent / payload["checkpoint_path"]).resolve()
        if not manifest.resolve().is_relative_to(source_root) or not checkpoint.is_relative_to(source_root):
            raise ValueError(f"预训练资产越出来源存储：{version_id}")
        if Path(payload["checkpoint_path"]).is_absolute():
            raise ValueError(f"预训练 manifest 必须使用相对 checkpoint_path，避免副本仍引用原存储：{version_id}")
        if version_id in selected or not checkpoint.is_file():
            raise ValueError(f"预训练资产身份重复或 checkpoint 缺失：{version_id}")
        selected[version_id] = (manifest, checkpoint)
    missing = model_version_ids - selected.keys()
    if missing:
        raise ValueError(f"预训练资产未找到：{sorted(missing)}")
    evidence = []
    for version_id, paths in sorted(selected.items()):
        for source in paths:
            relative = source.relative_to(source_root)
            destination = destination_root / relative
            if not destination.resolve().is_relative_to(destination_root):
                raise ValueError("验收资产目标越出隔离存储")
            destination.parent.mkdir(parents=True, exist_ok=True)
            # 使用独立副本，不建立会共享修改的硬链接。
            with source.open("rb") as reader, destination.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
            with destination.open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            evidence.append({"model_version_id": version_id, "object_key": relative.as_posix(),
                             "sha256": digest, "bytes": destination.stat().st_size})
    return evidence
