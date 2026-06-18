"""worker profile manifest 守卫测试。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.workers.settings import SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKER_PROFILES_DIR = REPO_ROOT / "runtimes" / "manifests" / "worker-profiles"
DEFAULT_BACKEND_WORKER_CONFIG = REPO_ROOT / "config" / "backend-worker.json"


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

    for profile_id, expected_consumer_kinds in EXPECTED_WORKER_PROFILE_CONSUMERS.items():
        manifest_path = WORKER_PROFILES_DIR / f"{profile_id}.json"
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert tuple(manifest_payload["enabled_consumer_kinds"]) == expected_consumer_kinds


def test_worker_profile_manifests_only_use_supported_consumer_kinds() -> None:
    """验证 worker profile manifest 不会引用未注册的 consumer kind。"""

    for manifest_path in WORKER_PROFILES_DIR.glob("*.json"):
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        enabled_consumer_kinds = manifest_payload.get("enabled_consumer_kinds")
        assert isinstance(enabled_consumer_kinds, list)
        assert enabled_consumer_kinds
        assert set(enabled_consumer_kinds).issubset(SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS)


def test_default_backend_worker_config_enables_current_full_consumer_set() -> None:
    """验证默认 backend-worker 配置覆盖当前真实使用的所有 consumer。"""

    config_payload = json.loads(DEFAULT_BACKEND_WORKER_CONFIG.read_text(encoding="utf-8"))
    enabled_consumer_kinds = tuple(config_payload["task_manager"]["enabled_consumer_kinds"])
    expected_consumer_kinds = set().union(*EXPECTED_WORKER_PROFILE_CONSUMERS.values())

    assert len(enabled_consumer_kinds) == len(set(enabled_consumer_kinds))
    assert set(enabled_consumer_kinds) == expected_consumer_kinds
    assert set(enabled_consumer_kinds).issubset(SUPPORTED_BACKEND_WORKER_CONSUMER_KINDS)
