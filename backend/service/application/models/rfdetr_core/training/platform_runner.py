"""RF-DETR 平台训练主入口。"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.training.device_selection import (
    SingleTrainingDeviceSelection,
    resolve_single_training_device,
)
from backend.service.application.support.resource_cleanup import (
    release_model_task_resources,
)
from backend.service.application.models.rfdetr_core.config import (
    SegmentationTrainConfig,
    TrainConfig,
)
from backend.service.application.models.rfdetr_core.datasets.aug_config import (
    AUG_AERIAL,
    AUG_AGGRESSIVE,
    AUG_CONSERVATIVE,
    AUG_INDUSTRIAL,
)
from backend.service.application.models.rfdetr_core.factory import (
    align_rfdetr_full_core_input_size,
    build_rfdetr_full_core_config,
)
from backend.service.application.models.rfdetr_core.training.platform_artifacts import (
    build_metrics_payload,
    build_validation_metrics_payload,
    prepare_pretrain_checkpoint,
    prepare_resume_checkpoint,
    read_or_build_checkpoint_artifacts,
    resolve_best_metric,
)
from backend.service.application.models.rfdetr_core.training.platform_dataset import (
    prepare_roboflow_coco_dataset,
)
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
    best_checkpoint_bytes: bytes | None = None
    test_metrics_payload: dict[str, object] | None = None


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
    aligned_input_size = resolve_rfdetr_platform_training_input_size(
        task_type=request.task_type,
        model_scale=request.model_scale,
        input_size=request.input_size,
    )
    resolution = max(aligned_input_size)
    device_selection = _resolve_device_selection(extra_options)
    device_name = device_selection.device_name

    temp_root = request.dataset_storage.root_dir / ".tmp" / "rfdetr-core-training"
    temp_root.mkdir(parents=True, exist_ok=True)
    module = None
    data_module = None
    trainer = None
    try:
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
            resume_checkpoint_path = prepare_resume_checkpoint(
                request.resume_checkpoint_path,
                temporary_dir,
            )
            warm_start_checkpoint_path = (
                None if resume_checkpoint_path is not None else request.warm_start_checkpoint_path
            )
            pretrain_checkpoint_path = prepare_pretrain_checkpoint(
                warm_start_checkpoint_path,
                temporary_dir,
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
                pretrained_path=pretrain_checkpoint_path,
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
                device_selection=device_selection,
                resume_checkpoint_path=resume_checkpoint_path,
                run_test=prepared_dataset.has_test_split,
            )
            RFDETRDataModule, RFDETRModelModule, build_trainer = (
                _load_rfdetr_lightning_training_components()
            )
            module = RFDETRModelModule(model_config, train_config)
            data_module = RFDETRDataModule(model_config, train_config)
            trainer = build_trainer(
                train_config,
                model_config,
                accelerator=device_selection.lightning_accelerator,
                num_sanity_val_steps=0,
                enable_model_summary=False,
            )
            trainer.fit(
                module,
                datamodule=data_module,
                ckpt_path=train_config.resume or None,
            )

            checkpoint_artifacts = read_or_build_checkpoint_artifacts(
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
            metrics_payload.update(
                {
                    "optimizer": "AdamW",
                    "initial_learning_rate": float(train_config.lr),
                    "final_learning_rate": _resolve_rfdetr_final_learning_rate(
                        trainer=trainer,
                        fallback=float(train_config.lr),
                    ),
                }
            )
            validation_metrics_payload = build_validation_metrics_payload(trainer)
            test_metrics_payload = _build_rfdetr_test_metrics_payload(
                validation_metrics_payload=validation_metrics_payload,
                has_test_split=prepared_dataset.has_test_split,
            )
            best_metric_name, best_metric_value = resolve_best_metric(
                task_type=request.task_type,
                validation_metrics=validation_metrics_payload,
            )
            return RfdetrPlatformTrainingResult(
                best_metric_value=best_metric_value,
                best_metric_name=best_metric_name,
                best_checkpoint_bytes=checkpoint_artifacts.best_checkpoint_bytes,
                latest_checkpoint_bytes=checkpoint_artifacts.latest_checkpoint_bytes,
                metrics_payload=metrics_payload,
                validation_metrics_payload=validation_metrics_payload,
                labels=prepared_dataset.labels,
                aligned_input_size=aligned_input_size,
                warm_start_summary=warm_start_summary,
                test_metrics_payload=test_metrics_payload,
            )
    finally:
        _release_rfdetr_training_resources(
            module=module,
            data_module=data_module,
            trainer=trainer,
        )


def resolve_rfdetr_platform_training_input_size(
    *,
    task_type: ModelTaskType,
    model_scale: str,
    input_size: tuple[int, int],
) -> tuple[int, int]:
    """将平台输入尺寸收敛为 RF-DETR 实际训练使用的方形尺寸。"""

    aligned_height, aligned_width = align_rfdetr_full_core_input_size(
        task_type=task_type,
        model_scale=model_scale,
        input_size=input_size,
    )
    resolution = max(aligned_height, aligned_width)
    return resolution, resolution


def _build_rfdetr_test_metrics_payload(
    *,
    validation_metrics_payload: dict[str, object],
    has_test_split: bool,
) -> dict[str, object]:
    """从 Lightning 最终指标中分离独立 test 结果。"""

    test_metrics = {
        str(key): value
        for key, value in validation_metrics_payload.items()
        if str(key).startswith("test/")
    }
    return {
        "available": bool(has_test_split and test_metrics),
        "split_name": "test",
        "checkpoint_role": "best",
        "metrics": test_metrics,
        "reason": (
            None
            if has_test_split and test_metrics
            else (
                "RF-DETR test 执行未产生指标"
                if has_test_split
                else "dataset export 未提供独立 test split"
            )
        ),
    }


def _resolve_rfdetr_final_learning_rate(*, trainer: Any, fallback: float) -> float:
    """从训练器 optimizer 读取最终基础学习率。"""

    optimizers = list(getattr(trainer, "optimizers", []) or [])
    if not optimizers:
        return float(fallback)
    param_groups = list(getattr(optimizers[0], "param_groups", []) or [])
    if not param_groups:
        return float(fallback)
    return float(param_groups[0].get("lr", fallback))


def _release_rfdetr_training_resources(
    *,
    module: object | None,
    data_module: object | None,
    trainer: object | None,
) -> None:
    """在成功、失败和取消路径统一释放 RF-DETR 训练资源。"""

    model = getattr(module, "model", None)
    original_model = getattr(model, "_orig_mod", model)
    move_to = getattr(original_model, "to", None)
    if callable(move_to):
        try:
            move_to("cpu")
        except Exception:
            pass
    release_model_task_resources(trainer, data_module, module)


def _load_rfdetr_lightning_training_components():
    """训练真正执行时再加载 Lightning 相关组件，避免 API 启动触发重依赖。"""

    from backend.service.application.models.rfdetr_core.training.module_data import (
        RFDETRDataModule,
    )
    from backend.service.application.models.rfdetr_core.training.module_model import (
        RFDETRModelModule,
    )
    from backend.service.application.models.rfdetr_core.training.trainer import (
        build_trainer,
    )

    return RFDETRDataModule, RFDETRModelModule, build_trainer


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
    device_selection: SingleTrainingDeviceSelection,
    resume_checkpoint_path: str | None = None,
    run_test: bool = False,
) -> TrainConfig:
    """把平台训练参数转换成 RF-DETR core 训练配置。"""

    gpu_count = int(extra_options.get("gpu_count", 1))
    if gpu_count < 1:
        raise InvalidRequestError("gpu_count 必须大于 0")
    if gpu_count > 1:
        raise InvalidRequestError("当前版本只支持单 GPU 训练，gpu_count 必须为 1")

    config_cls = (
        SegmentationTrainConfig
        if request.task_type == SEGMENTATION_TASK_TYPE
        else TrainConfig
    )
    lr_scheduler = str(extra_options.get("lr_scheduler", "step")).strip().lower()
    if lr_scheduler not in {"step", "cosine"}:
        raise InvalidRequestError(
            "RF-DETR lr_scheduler 只支持 step 或 cosine",
            details={"lr_scheduler": lr_scheduler},
        )

    config_options: dict[str, object] = {
        "dataset_file": "roboflow",
        "dataset_dir": str(dataset_dir),
        "output_dir": str(output_dir),
        "class_names": list(labels),
        "batch_size": max(1, int(request.batch_size)),
        "grad_accum_steps": max(1, int(extra_options.get("grad_accum_steps", 4))),
        "epochs": max(1, int(request.max_epochs)),
        "resume": resume_checkpoint_path,
        "lr": float(extra_options.get("learning_rate", 1e-4)),
        "weight_decay": float(extra_options.get("weight_decay", 1e-4)),
        "lr_scheduler": lr_scheduler,
        "lr_min_factor": (
            float(extra_options.get("min_lr_ratio", 0.01))
            if lr_scheduler == "cosine"
            else 0.0
        ),
        "set_cost_class": float(extra_options.get("class_cost", 2.0)),
        "set_cost_bbox": float(extra_options.get("bbox_cost", 5.0)),
        "set_cost_giou": float(extra_options.get("giou_cost", 2.0)),
        "cls_loss_coef": float(
            extra_options.get(
                "class_loss_weight",
                5.0 if request.task_type == SEGMENTATION_TASK_TYPE else 1.0,
            )
        ),
        "bbox_loss_coef": float(extra_options.get("bbox_loss_weight", 5.0)),
        "giou_loss_coef": float(extra_options.get("giou_loss_weight", 2.0)),
        "eval_interval": max(1, int(extra_options.get("evaluation_interval", 1))),
        "eval_max_dets": max(100, int(extra_options.get("evaluation_max_detections", 500))),
        "accelerator": device_selection.lightning_accelerator,
        "devices": device_selection.lightning_devices,
        "num_workers": max(0, int(extra_options.get("num_workers", 0))),
        "progress_bar": None,
        "tensorboard": False,
        "use_ema": _read_bool_option(
            extra_options,
            "use_ema",
            extra_options.get("ema", True),
        ),
        "multi_scale": _read_bool_option(extra_options, "multi_scale", True),
        "expanded_scales": _read_bool_option(extra_options, "expanded_scales", True),
        "square_resize_div_64": True,
        "checkpoint_interval": 1,
        "run_test": run_test,
        "log_per_class_metrics": True,
        "aug_config": _resolve_rfdetr_aug_config(extra_options),
        "augmentation_backend": _resolve_rfdetr_augmentation_backend(extra_options),
    }
    if request.task_type == SEGMENTATION_TASK_TYPE:
        config_options.update(
            {
                "mask_ce_loss_coef": float(extra_options.get("mask_ce_weight", 5.0)),
                "mask_dice_loss_coef": float(extra_options.get("mask_dice_weight", 5.0)),
            }
        )

    return config_cls(
        **config_options,
    )


def _resolve_device_selection(
    extra_options: dict[str, object],
) -> SingleTrainingDeviceSelection:
    """解析 RF-DETR 单卡训练设备。"""

    return resolve_single_training_device(
        torch_module=torch,
        extra_options=extra_options,
    )


def _resolve_rfdetr_aug_config(
    extra_options: dict[str, object],
) -> dict[str, object] | None:
    """解析 RF-DETR 训练增强配置。"""

    if _read_bool_option(
        extra_options,
        "disable_augmentation",
        extra_options.get("no_augmentation", extra_options.get("no_aug", False)),
    ):
        return {}

    custom_config = extra_options.get("aug_config")
    if isinstance(custom_config, dict):
        return dict(custom_config)

    preset = str(extra_options.get("rfdetr_augmentation_preset", "default")).strip().lower()
    presets: dict[str, dict[str, object] | None] = {
        "default": None,
        "conservative": AUG_CONSERVATIVE,
        "aggressive": AUG_AGGRESSIVE,
        "aerial": AUG_AERIAL,
        "industrial": AUG_INDUSTRIAL,
    }
    return presets.get(preset, None)


def _resolve_rfdetr_augmentation_backend(extra_options: dict[str, object]) -> str:
    """解析 RF-DETR 增强执行后端。"""

    backend = str(extra_options.get("augmentation_backend", "cpu")).strip().lower()
    if backend in {"cpu", "auto", "gpu"}:
        return backend
    return "cpu"


def _read_bool_option(
    extra_options: dict[str, object],
    key: str,
    default: object,
) -> bool:
    """读取布尔训练选项。"""

    value = extra_options.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _precision_enables_amp(precision: str) -> bool:
    """判断当前 precision 是否启用 AMP。"""

    return str(precision).strip().lower() in {"fp16", "bf16", "16-mixed", "bf16-mixed"}
