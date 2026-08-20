"""worker profile manifest 守卫测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.workers.contracts import (
    WORKER_PROFILE_FORMAT_ID,
    load_worker_profile_manifest,
)
from backend.workers.settings import BackendWorkerSettings


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_PROFILES_DIR = REPO_ROOT / "runtimes" / "manifests" / "worker-profiles"


EXPECTED_WORKER_PROFILE_CONSUMERS: dict[str, tuple[str, ...]] = {
    "dataset-import": ("dataset-import",),
    "dataset-export": ("dataset-export",),
    "training": (
        "yolox-training",
        "yolov8-training",
        "yolo11-training",
        "yolo26-training",
        "rfdetr-training",
        "classification-training",
        "segmentation-training",
        "pose-training",
        "obb-training",
    ),
    "conversion": (
        "yolox-conversion",
        "yolov8-conversion",
        "yolo11-conversion",
        "yolo26-conversion",
        "rfdetr-conversion",
    ),
    "evaluation": (
        "detection-evaluation",
        "classification-evaluation",
        "segmentation-evaluation",
        "pose-evaluation",
        "obb-evaluation",
    ),
    "inference": (
        "detection-inference",
        "classification-inference",
        "segmentation-inference",
        "pose-inference",
        "obb-inference",
    ),
}


def test_worker_profile_manifests_cover_current_release_full_consumer_matrix() -> None:
    """验证 full 发布目录使用的 worker profile 已覆盖当前真实消费者矩阵。"""

    for (
        profile_id,
        expected_consumer_kinds,
    ) in EXPECTED_WORKER_PROFILE_CONSUMERS.items():
        manifest_path = WORKER_PROFILES_DIR / f"{profile_id}.json"
        manifest = load_worker_profile_manifest(manifest_path)
        assert manifest.format_id == WORKER_PROFILE_FORMAT_ID
        assert manifest.enabled_consumer_kinds == expected_consumer_kinds


def test_worker_profile_manifests_only_use_supported_consumer_kinds() -> None:
    """验证 worker profile manifest 不会引用未注册的 consumer kind。"""

    for manifest_path in WORKER_PROFILES_DIR.glob("*.json"):
        manifest = load_worker_profile_manifest(manifest_path)
        assert manifest.enabled_consumer_kinds


def test_backend_worker_config_does_not_repeat_profile_runtime_policy() -> None:
    """consumer、并发和轮询策略只能来自严格 Profile Manifest。"""

    config_text = (REPO_ROOT / "config" / "backend-worker.json").read_text(
        encoding="utf-8"
    )

    assert '"task_manager"' not in config_text
    assert '"enabled_consumer_kinds"' not in config_text


def test_backend_worker_settings_reject_removed_task_manager_config() -> None:
    """旧 task_manager 配置不能被静默忽略。"""

    with pytest.raises(ValidationError, match="task_manager"):
        BackendWorkerSettings(task_manager={})
