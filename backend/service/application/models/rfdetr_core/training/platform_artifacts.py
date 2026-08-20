"""RF-DETR 平台训练产物整理。"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.service.domain.models.model_input_spec import serialize_spatial_size_hw

import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core.config import TrainConfig
from backend.service.domain.models.model_task_types import (
    ModelTaskType,
    SEGMENTATION_TASK_TYPE,
)


@dataclass(frozen=True)
class RfdetrCheckpointArtifacts:
    """描述 RF-DETR 可发布 best 与可恢复 latest checkpoint。"""

    best_checkpoint_bytes: bytes
    latest_checkpoint_bytes: bytes


def read_or_build_checkpoint_artifacts(
    *,
    output_dir: Path,
    module: Any,
    model_config: Any,
    train_config: TrainConfig,
    trainer: Any,
) -> RfdetrCheckpointArtifacts:
    """分别读取 best 权重和 latest Lightning 恢复状态。"""

    best_checkpoint_path = next(
        (
            output_dir / file_name
            for file_name in (
                "checkpoint_best_total.pth",
                "checkpoint_best_regular.pth",
                "checkpoint_0.pth",
                "checkpoint_1.pth",
            )
            if (output_dir / file_name).is_file()
        ),
        None,
    )
    if best_checkpoint_path is None:
        best_checkpoint_path = output_dir / "checkpoint_best_total.pth"
        model = getattr(module.model, "_orig_mod", module.model)
        torch.save(
            {
                "model": model.state_dict(),
                "args": train_config.model_dump(),
                "model_config": model_config.model_dump(),
                "epoch": int(getattr(trainer, "current_epoch", 0)),
            },
            best_checkpoint_path,
        )

    latest_checkpoint_path = output_dir / "last.ckpt"
    if not latest_checkpoint_path.is_file():
        save_checkpoint = getattr(trainer, "save_checkpoint", None)
        if callable(save_checkpoint):
            raise InvalidRequestError(
                "RF-DETR 训练结束时缺少 last.ckpt；禁止在 EMA/best 权重可能已替换后补存恢复文件",
                details={"checkpoint_path": str(latest_checkpoint_path)},
            )
    if not latest_checkpoint_path.is_file():
        # 极简测试 trainer 可能不提供 Lightning save_checkpoint；此时明确回退，
        # 但真实训练器必须生成 last.ckpt。
        latest_checkpoint_path = best_checkpoint_path

    return RfdetrCheckpointArtifacts(
        best_checkpoint_bytes=best_checkpoint_path.read_bytes(),
        latest_checkpoint_bytes=latest_checkpoint_path.read_bytes(),
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


def prepare_resume_checkpoint(
    checkpoint_path: Path | None,
    temporary_dir: Path,
) -> str | None:
    """校验并归一平台 resume checkpoint，保留 Lightning 训练状态。"""

    if checkpoint_path is None:
        return None
    if not checkpoint_path.is_file():
        raise InvalidRequestError(
            "RF-DETR resume checkpoint 不存在",
            details={"checkpoint_path": str(checkpoint_path)},
        )

    _ = temporary_dir
    checkpoint = torch.load(str(checkpoint_path), map_location="cpu", weights_only=False)
    if not isinstance(checkpoint, dict):
        raise InvalidRequestError("RF-DETR resume checkpoint 格式无效")
    required_fields = (
        "state_dict",
        "optimizer_states",
        "lr_schedulers",
        "callbacks",
        "loops",
        "epoch",
        "global_step",
        "pytorch-lightning_version",
    )
    missing_fields = [field for field in required_fields if field not in checkpoint]
    state_dict = checkpoint.get("state_dict")
    optimizer_states = checkpoint.get("optimizer_states")
    lr_schedulers = checkpoint.get("lr_schedulers")
    if missing_fields:
        raise InvalidRequestError(
            "RF-DETR resume 只接受完整 Lightning checkpoint",
            details={
                "checkpoint_path": str(checkpoint_path),
                "missing_fields": missing_fields,
                "hint": "weights-only checkpoint 必须改用 warm-start",
            },
        )
    if not isinstance(state_dict, dict) or not state_dict:
        raise InvalidRequestError("RF-DETR resume checkpoint 的 state_dict 为空或格式无效")
    if not all(str(key).startswith("model.") for key in state_dict):
        raise InvalidRequestError(
            "RF-DETR resume checkpoint 的 state_dict 不是当前 Lightning 模型状态",
            details={"hint": "weights-only checkpoint 必须改用 warm-start"},
        )
    if not isinstance(optimizer_states, list) or not optimizer_states:
        raise InvalidRequestError("RF-DETR resume checkpoint 缺少有效 optimizer state")
    if not isinstance(lr_schedulers, list) or not lr_schedulers:
        raise InvalidRequestError("RF-DETR resume checkpoint 缺少有效 scheduler state")
    if "legacy_ema_state_dict" in checkpoint:
        raise InvalidRequestError(
            "RF-DETR resume 不再接受 legacy EMA checkpoint；请使用当前平台生成的完整 checkpoint"
        )
    return str(checkpoint_path)


def read_or_build_checkpoint_bytes(
    *,
    output_dir: Path,
    module: Any,
    model_config: Any,
    train_config: TrainConfig,
    trainer: Any,
) -> bytes:
    """读取训练输出 checkpoint；缺少文件时按当前 module 状态补一个标准 checkpoint。"""

    return read_or_build_checkpoint_artifacts(
        output_dir=output_dir,
        module=module,
        model_config=model_config,
        train_config=train_config,
        trainer=trainer,
    ).best_checkpoint_bytes


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
        "input_size": serialize_spatial_size_hw(aligned_input_size),
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
