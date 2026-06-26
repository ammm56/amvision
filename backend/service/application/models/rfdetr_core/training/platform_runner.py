"""RF-DETR 平台训练主入口。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.rfdetr_core.config import (
    SegmentationTrainConfig,
    TrainConfig,
)
from backend.service.application.models.rfdetr_core.factory import (
    align_rfdetr_full_core_input_size,
    build_rfdetr_full_core_config,
)
from backend.service.application.models.rfdetr_core.training.module_data import (
    RFDETRDataModule,
)
from backend.service.application.models.rfdetr_core.training.module_model import (
    RFDETRModelModule,
)
from backend.service.application.models.rfdetr_core.training.platform_artifacts import (
    build_metrics_payload,
    build_validation_metrics_payload,
    prepare_pretrain_checkpoint,
    read_or_build_checkpoint_bytes,
    resolve_best_metric,
)
from backend.service.application.models.rfdetr_core.training.platform_dataset import (
    prepare_roboflow_coco_dataset,
)
from backend.service.application.models.rfdetr_core.training.trainer import build_trainer
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
    ModelTaskType,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class RfdetrPlatformTrainingRequest:
    """平台任务传入 RF-DETR full core 的训练请求。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    task_type: ModelTaskType
    model_scale: str
    batch_size: int
    max_epochs: int
    input_size: tuple[int, int]
    precision: str
    resume_checkpoint_path: Path | None = None
    warm_start_checkpoint_path: Path | None = None
    warm_start_source_summary: dict[str, object] | None = None
    extra_options: dict[str, object] | None = None


@dataclass(frozen=True)
class RfdetrPlatformTrainingResult:
    """RF-DETR full core 训练完成后交给平台登记的结果。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    aligned_input_size: tuple[int, int]
    warm_start_summary: dict[str, object]


def run_rfdetr_platform_training(
    request: RfdetrPlatformTrainingRequest,
) -> RfdetrPlatformTrainingResult:
    """执行 RF-DETR 平台训练，并返回平台需要登记的 checkpoint 与指标。"""

    if request.task_type not in {DETECTION_TASK_TYPE, SEGMENTATION_TASK_TYPE}:
        raise InvalidRequestError(
            "RF-DETR full core 当前只支持 detection 和 segmentation 训练",
            details={"task_type": request.task_type},
        )

    extra_options = dict(request.extra_options or {})
    aligned_input_size = align_rfdetr_full_core_input_size(
        task_type=request.task_type,
        model_scale=request.model_scale,
        input_size=request.input_size,
    )
    resolution = max(aligned_input_size)
    device_name = _resolve_device_name(extra_options)

    temp_root = request.dataset_storage.root_dir / ".tmp" / "rfdetr-core-training"
    temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="run-",
        dir=str(temp_root),
    ) as temporary_dir_name:
        temporary_dir = Path(temporary_dir_name)
        prepared_dataset = prepare_roboflow_coco_dataset(
            dataset_storage=request.dataset_storage,
            manifest_payload=request.manifest_payload,
            dataset_dir=temporary_dir / "dataset",
            task_type=request.task_type,
        )
        output_dir = temporary_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        pretrain_checkpoint_path = (
            request.resume_checkpoint_path or request.warm_start_checkpoint_path
        )
        warm_start_summary = _build_warm_start_summary(
            warm_start_checkpoint_path=request.warm_start_checkpoint_path,
            source_summary=request.warm_start_source_summary,
            resume_checkpoint_path=request.resume_checkpoint_path,
        )

        model_config = build_rfdetr_full_core_config(
            task_type=request.task_type,
            model_scale=request.model_scale,
            num_classes=len(prepared_dataset.labels),
            pretrained_path=prepare_pretrain_checkpoint(
                pretrain_checkpoint_path,
                temporary_dir,
            ),
            device=device_name,
        )
        model_config.resolution = resolution
        model_config.amp = _precision_enables_amp(request.precision)

        train_config = _build_train_config(
            request=request,
            dataset_dir=prepared_dataset.dataset_dir,
            output_dir=output_dir,
            labels=prepared_dataset.labels,
            extra_options=extra_options,
        )
        module = RFDETRModelModule(model_config, train_config)
        data_module = RFDETRDataModule(model_config, train_config)
        trainer = build_trainer(
            train_config,
            model_config,
            accelerator="cpu" if device_name == "cpu" else "gpu",
            num_sanity_val_steps=0,
            enable_model_summary=False,
        )
        trainer.fit(module, datamodule=data_module)

        latest_checkpoint_bytes = read_or_build_checkpoint_bytes(
            output_dir=output_dir,
            module=module,
            model_config=model_config,
            train_config=train_config,
            trainer=trainer,
        )
        metrics_payload = build_metrics_payload(
            output_dir=output_dir,
            trainer=trainer,
            aligned_input_size=aligned_input_size,
        )
        validation_metrics_payload = build_validation_metrics_payload(trainer)
        best_metric_name, best_metric_value = resolve_best_metric(
            task_type=request.task_type,
            validation_metrics=validation_metrics_payload,
        )
        return RfdetrPlatformTrainingResult(
            best_metric_value=best_metric_value,
            best_metric_name=best_metric_name,
            latest_checkpoint_bytes=latest_checkpoint_bytes,
            metrics_payload=metrics_payload,
            validation_metrics_payload=validation_metrics_payload,
            labels=prepared_dataset.labels,
            aligned_input_size=aligned_input_size,
            warm_start_summary=warm_start_summary,
        )


def _build_warm_start_summary(
    *,
    warm_start_checkpoint_path: Path | None,
    source_summary: dict[str, object] | None,
    resume_checkpoint_path: Path | None,
) -> dict[str, object]:
    """构建 RF-DETR warm start 训练摘要。"""

    if warm_start_checkpoint_path is None or resume_checkpoint_path is not None:
        return {
            "enabled": False,
            "source_model_version_id": None,
            "source_kind": None,
            "source_model_name": None,
            "source_model_scale": None,
            "load_summary": None,
        }
    summary = dict(source_summary or {})
    summary.update(
        {
            "enabled": True,
            "load_summary": {
                "checkpoint_path": str(warm_start_checkpoint_path),
                "loader": "rfdetr-full-core-pretrain",
            },
        }
    )
    return summary


def _build_train_config(
    *,
    request: RfdetrPlatformTrainingRequest,
    dataset_dir: Path,
    output_dir: Path,
    labels: tuple[str, ...],
    extra_options: dict[str, object],
) -> TrainConfig:
    """把平台训练参数转换成 RF-DETR core 训练配置。"""

    config_cls = (
        SegmentationTrainConfig
        if request.task_type == SEGMENTATION_TASK_TYPE
        else TrainConfig
    )
    return config_cls(
        dataset_file="roboflow",
        dataset_dir=str(dataset_dir),
        output_dir=str(output_dir),
        class_names=list(labels),
        batch_size=max(1, int(request.batch_size)),
        epochs=max(1, int(request.max_epochs)),
        lr=float(extra_options.get("learning_rate", 1e-4)),
        weight_decay=float(extra_options.get("weight_decay", 1e-4)),
        eval_interval=max(1, int(extra_options.get("evaluation_interval", 1))),
        accelerator="cpu" if _resolve_device_name(extra_options) == "cpu" else "gpu",
        devices=max(1, int(extra_options.get("gpu_count", 1))),
        num_workers=max(0, int(extra_options.get("num_workers", 0))),
        progress_bar=None,
        tensorboard=False,
        use_ema=bool(extra_options.get("use_ema", False)),
        multi_scale=bool(extra_options.get("multi_scale", False)),
        expanded_scales=bool(extra_options.get("expanded_scales", False)),
        square_resize_div_64=True,
        checkpoint_interval=1,
        run_test=False,
        log_per_class_metrics=False,
    )


def _resolve_device_name(extra_options: dict[str, object]) -> str:
    """解析训练设备名称。"""

    requested = str(extra_options.get("device", "cpu")).strip().lower()
    if requested == "cuda" or requested.startswith("cuda:"):
        return requested if torch.cuda.is_available() else "cpu"
    return "cpu"


def _precision_enables_amp(precision: str) -> bool:
    """判断当前 precision 是否启用 AMP。"""

    return str(precision).strip().lower() in {"fp16", "bf16", "16-mixed", "bf16-mixed"}
