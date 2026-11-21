"""读取和保存 segmentation 最佳权重实际对应的轮次。"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


def load_yolo_segmentation_best_checkpoint(
    path: Path | None, *, torch_module: Any
) -> tuple[bytes, int | None]:
    """从实际权重文件恢复轮次，兼容已保存的旧版 YOLO checkpoint。"""
    if path is None or not path.is_file():
        return b"", None
    checkpoint_bytes = path.read_bytes()
    if not checkpoint_bytes:
        return b"", None
    checkpoint = torch_module.load(
        io.BytesIO(checkpoint_bytes), map_location="cpu", weights_only=False
    )
    epoch = checkpoint.get("epoch") if isinstance(checkpoint, dict) else None
    return checkpoint_bytes, epoch if type(epoch) is int and epoch > 0 else None


def write_segmentation_best_checkpoint_epoch(
    *, dataset_storage: LocalDatasetStorage, summary_object_key: str, epoch: int
) -> None:
    """最佳权重保存成功后立即更新摘要，供运行中和暂停时查询。"""
    summary = (
        dataset_storage.read_json(summary_object_key)
        if dataset_storage.resolve(summary_object_key).is_file()
        else {}
    )
    summary = dict(summary) if isinstance(summary, dict) else {}
    if summary.get("best_checkpoint_saved_epoch") == epoch:
        return
    summary["best_checkpoint_saved_epoch"] = epoch
    dataset_storage.write_json(summary_object_key, summary)
