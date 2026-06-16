"""RF-DETR 平台训练产物整理。"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import torch

from backend.service.application.models.rfdetr_core.config import TrainConfig
from backend.service.application.models.rfdetr_core.training.module_model import (
    RFDETRModelModule,
)
from backend.service.domain.models.model_task_types import (
    ModelTaskType,
    SEGMENTATION_TASK_TYPE,
)


def prepare_pretrain_checkpoint(
    checkpoint_path: Path | None,
    temporary_dir: Path,
) -> str | None:
    """把平台 checkpoint 归一成 RF-DETR 训练入口可读取的权重文件。"""

    if checkpoint_path is None or not checkpoint_path.is_file():
        return None
    checkpoint = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
    if isinstance(checkpoint, dict) and "model" in checkpoint:
        return str(checkpoint_path)
    if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
        normalized_path = temporary_dir / "normalized-pretrain.pth"
        normalized_payload = {
            "model": checkpoint["model_state_dict"],
            "args": checkpoint.get("args", {}),
            "epoch": checkpoint.get("epoch", 0),
        }
        torch.save(normalized_payload, normalized_path)
        return str(normalized_path)
    return str(checkpoint_path)


def read_or_build_checkpoint_bytes(
    *,
    output_dir: Path,
    module: RFDETRModelModule,
    model_config: Any,
    train_config: TrainConfig,
    trainer: Any,
) -> bytes:
    """读取训练输出 checkpoint；缺少文件时按当前 module 状态补一个标准 checkpoint。"""

    for file_name in (
        "checkpoint_best_total.pth",
        "checkpoint_best_regular.pth",
        "checkpoint_0.pth",
        "checkpoint_1.pth",
        "last.ckpt",
    ):
        candidate = output_dir / file_name
        if candidate.is_file():
            return candidate.read_bytes()

    model = getattr(module.model, "_orig_mod", module.model)
    payload = {
        "model": model.state_dict(),
        "args": train_config.model_dump(),
        "model_config": model_config.model_dump(),
        "epoch": int(getattr(trainer, "current_epoch", 0)),
    }
    checkpoint_path = output_dir / "checkpoint_best_total.pth"
    torch.save(payload, checkpoint_path)
    return checkpoint_path.read_bytes()


def build_metrics_payload(
    *,
    output_dir: Path,
    trainer: Any,
    aligned_input_size: tuple[int, int],
) -> dict[str, object]:
    """组装 RF-DETR 训练任务的指标摘要。"""

    return {
        "epoch_history": _read_metrics_csv(output_dir / "metrics.csv"),
        "callback_metrics": _tensor_mapping_to_float_dict(
            getattr(trainer, "callback_metrics", {}),
        ),
        "input_size": list(aligned_input_size),
        "implementation_mode": "rfdetr-full-core",
    }


def build_validation_metrics_payload(trainer: Any) -> dict[str, object]:
    """从 trainer callback metrics 中提取 validation/test 指标。"""

    metrics = _tensor_mapping_to_float_dict(getattr(trainer, "callback_metrics", {}))
    return {
        key: value
        for key, value in metrics.items()
        if key.startswith("val/") or key.startswith("test/")
    }


def resolve_best_metric(
    *,
    task_type: ModelTaskType,
    validation_metrics: dict[str, object],
) -> tuple[str, float]:
    """解析本轮训练的最佳指标。"""

    candidate_names = (
        ("val/segm_mAP_50_95", "val/mAP_50_95")
        if task_type == SEGMENTATION_TASK_TYPE
        else ("val/mAP_50_95",)
    )
    for metric_name in candidate_names:
        metric_value = validation_metrics.get(metric_name)
        if isinstance(metric_value, int | float):
            return metric_name, float(metric_value)
    return candidate_names[0], 0.0


def _read_metrics_csv(metrics_path: Path) -> list[dict[str, object]]:
    """读取 Lightning 写出的 metrics.csv。"""

    if not metrics_path.is_file():
        return []
    with metrics_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return [dict(row) for row in reader]


def _tensor_mapping_to_float_dict(payload: object) -> dict[str, float]:
    """把 tensor/int/float 指标统一转成 float 字典。"""

    if not isinstance(payload, dict):
        return {}
    result: dict[str, float] = {}
    for key, value in payload.items():
        metric_name = str(key)
        if hasattr(value, "detach"):
            result[metric_name] = float(value.detach().cpu().item())
        elif isinstance(value, int | float):
            result[metric_name] = float(value)
    return result
