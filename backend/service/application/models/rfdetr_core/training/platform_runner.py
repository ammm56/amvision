"""RF-DETR core 训练处理模块：`training.platform_runner`。"""

from __future__ import annotations

import csv
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

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
    """RF-DETR core 类：`RfdetrPlatformTrainingRequest`。"""

    dataset_storage: LocalDatasetStorage
    manifest_payload: dict[str, object]
    task_type: ModelTaskType
    model_scale: str
    batch_size: int
    max_epochs: int
    input_size: tuple[int, int]
    precision: str
    resume_checkpoint_path: Path | None = None
    extra_options: dict[str, object] | None = None


@dataclass(frozen=True)
class RfdetrPlatformTrainingResult:
    """RF-DETR core 类：`RfdetrPlatformTrainingResult`。"""

    best_metric_value: float
    best_metric_name: str
    latest_checkpoint_bytes: bytes
    metrics_payload: dict[str, object]
    validation_metrics_payload: dict[str, object]
    labels: tuple[str, ...]
    aligned_input_size: tuple[int, int]


@dataclass(frozen=True)
class _PreparedDataset:
    """RF-DETR core 类：`_PreparedDataset`。"""

    dataset_dir: Path
    labels: tuple[str, ...]


_SPLIT_NAME_MAP: dict[str, str] = {
    "train": "train",
    "training": "train",
    "val": "valid",
    "valid": "valid",
    "validation": "valid",
    "test": "test",
}


def run_rfdetr_platform_training(
    request: RfdetrPlatformTrainingRequest,
) -> RfdetrPlatformTrainingResult:
    """执行 `run_rfdetr_platform_training`。
    
    参数：
    - `request`：传入的 `request` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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
        prepared_dataset = _prepare_roboflow_coco_dataset(
            dataset_storage=request.dataset_storage,
            manifest_payload=request.manifest_payload,
            dataset_dir=temporary_dir / "dataset",
            task_type=request.task_type,
        )
        output_dir = temporary_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        model_config = build_rfdetr_full_core_config(
            task_type=request.task_type,
            model_scale=request.model_scale,
            num_classes=len(prepared_dataset.labels),
            pretrained_path=_prepare_pretrain_checkpoint(
                request.resume_checkpoint_path,
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

        latest_checkpoint_bytes = _read_or_build_checkpoint_bytes(
            output_dir=output_dir,
            module=module,
            model_config=model_config,
            train_config=train_config,
            trainer=trainer,
        )
        metrics_payload = _build_metrics_payload(
            output_dir=output_dir,
            trainer=trainer,
            aligned_input_size=aligned_input_size,
        )
        validation_metrics_payload = _build_validation_metrics_payload(trainer)
        best_metric_name, best_metric_value = _resolve_best_metric(
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
        )


def _build_train_config(
    *,
    request: RfdetrPlatformTrainingRequest,
    dataset_dir: Path,
    output_dir: Path,
    labels: tuple[str, ...],
    extra_options: dict[str, object],
) -> TrainConfig:
    """执行 `_build_train_config`。
    
    参数：
    - `request`：传入的 `request` 参数。
    - `dataset_dir`：传入的 `dataset_dir` 参数。
    - `output_dir`：传入的 `output_dir` 参数。
    - `labels`：传入的 `labels` 参数。
    - `extra_options`：传入的 `extra_options` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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


def _prepare_roboflow_coco_dataset(
    *,
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
    dataset_dir: Path,
    task_type: ModelTaskType,
) -> _PreparedDataset:
    """执行 `_prepare_roboflow_coco_dataset`。
    
    参数：
    - `dataset_storage`：传入的 `dataset_storage` 参数。
    - `manifest_payload`：传入的 `manifest_payload` 参数。
    - `dataset_dir`：传入的 `dataset_dir` 参数。
    - `task_type`：传入的 `task_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    split_payloads = _read_manifest_splits(manifest_payload)
    category_names_by_id: dict[int, str] = {}
    prepared_splits: dict[str, dict[str, object]] = {}

    for split_payload in split_payloads:
        split_name = _normalize_split_name(split_payload.get("name"))
        if split_name is None:
            continue
        annotation_key = str(split_payload.get("annotation_file") or "").strip()
        image_root = str(split_payload.get("image_root") or "").strip()
        if not annotation_key or not image_root:
            continue

        annotation_payload = dataset_storage.read_json(annotation_key)
        if not isinstance(annotation_payload, dict):
            continue
        prepared_payload = _copy_coco_split(
            dataset_storage=dataset_storage,
            annotation_payload=annotation_payload,
            image_root=image_root,
            target_split_dir=dataset_dir / split_name,
            task_type=task_type,
        )
        prepared_splits[split_name] = prepared_payload
        for category in prepared_payload.get("categories", []):
            if isinstance(category, dict):
                category_names_by_id[int(category.get("id", -1))] = str(
                    category.get("name", "")
                )

    if "train" not in prepared_splits:
        raise InvalidRequestError("RF-DETR 训练数据缺少 train split")
    if "valid" not in prepared_splits:
        prepared_splits["valid"] = json.loads(json.dumps(prepared_splits["train"]))
        _copy_split_directory(dataset_dir / "train", dataset_dir / "valid")

    for split_name, prepared_payload in prepared_splits.items():
        split_dir = dataset_dir / split_name
        split_dir.mkdir(parents=True, exist_ok=True)
        (split_dir / "_annotations.coco.json").write_text(
            json.dumps(prepared_payload, ensure_ascii=False),
            encoding="utf-8",
        )

    labels = tuple(
        category_name
        for _, category_name in sorted(category_names_by_id.items())
        if category_name
    )
    if not labels:
        raise InvalidRequestError("RF-DETR 训练数据缺少类别")
    return _PreparedDataset(dataset_dir=dataset_dir, labels=labels)


def _read_manifest_splits(manifest_payload: dict[str, object]) -> list[dict[str, object]]:
    """执行 `_read_manifest_splits`。
    
    参数：
    - `manifest_payload`：传入的 `manifest_payload` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    raw_splits = manifest_payload.get("splits")
    if not isinstance(raw_splits, list):
        raise InvalidRequestError("DatasetExport manifest 缺少 splits")
    return [item for item in raw_splits if isinstance(item, dict)]


def _copy_coco_split(
    *,
    dataset_storage: LocalDatasetStorage,
    annotation_payload: dict[str, object],
    image_root: str,
    target_split_dir: Path,
    task_type: ModelTaskType,
) -> dict[str, object]:
    """执行 `_copy_coco_split`。
    
    参数：
    - `dataset_storage`：传入的 `dataset_storage` 参数。
    - `annotation_payload`：传入的 `annotation_payload` 参数。
    - `image_root`：传入的 `image_root` 参数。
    - `target_split_dir`：传入的 `target_split_dir` 参数。
    - `task_type`：传入的 `task_type` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    target_split_dir.mkdir(parents=True, exist_ok=True)
    image_payloads = [
        image for image in annotation_payload.get("images", []) if isinstance(image, dict)
    ]
    image_ids = {int(image.get("id", -1)) for image in image_payloads}
    kept_annotations: list[dict[str, object]] = []

    for image_payload in image_payloads:
        file_name = _normalize_coco_file_name(image_payload.get("file_name"))
        source_path = _resolve_coco_source_image_path(
            dataset_storage=dataset_storage,
            image_root=image_root,
            file_name=file_name,
        )
        rfdetr_file_name = _build_rfdetr_roboflow_file_name(
            split_name=target_split_dir.name,
            file_name=file_name,
        )
        destination_path = target_split_dir / rfdetr_file_name
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination_path)
        image_payload["file_name"] = rfdetr_file_name

    for annotation in annotation_payload.get("annotations", []):
        if not isinstance(annotation, dict):
            continue
        if int(annotation.get("image_id", -1)) not in image_ids:
            continue
        if task_type == SEGMENTATION_TASK_TYPE and not annotation.get("segmentation"):
            continue
        kept_annotations.append(annotation)

    return {
        "images": image_payloads,
        "annotations": kept_annotations,
        "categories": [
            category
            for category in annotation_payload.get("categories", [])
            if isinstance(category, dict)
        ],
    }


def _normalize_split_name(raw_name: object) -> str | None:
    """执行 `_normalize_split_name`。
    
    参数：
    - `raw_name`：传入的 `raw_name` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return _SPLIT_NAME_MAP.get(str(raw_name or "").strip().lower())


def _normalize_coco_file_name(raw_file_name: object) -> str:
    """执行 `_normalize_coco_file_name`。
    
    参数：
    - `raw_file_name`：传入的 `raw_file_name` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    file_name = PurePosixPath(str(raw_file_name or "").strip())
    normalized = PurePosixPath(*[part for part in file_name.parts if part not in {"", "/", "."}])
    if str(normalized) == ".":
        raise InvalidRequestError("COCO annotation 中存在空 file_name")
    return str(normalized)


def _resolve_coco_source_image_path(
    *,
    dataset_storage: LocalDatasetStorage,
    image_root: str,
    file_name: str,
) -> Path:
    """从 DatasetExport 中解析 COCO 图片源文件。"""

    normalized_file_name = PurePosixPath(file_name)
    candidate_keys = [
        str(PurePosixPath(image_root) / normalized_file_name),
    ]
    if len(normalized_file_name.parts) > 1:
        candidate_keys.append(str(PurePosixPath(image_root) / normalized_file_name.name))

    for candidate_key in dict.fromkeys(candidate_keys):
        source_path = dataset_storage.resolve(candidate_key)
        if source_path.is_file():
            return source_path

    raise InvalidRequestError(
        "RF-DETR 训练数据图片不存在",
        details={"candidates": candidate_keys},
    )


def _build_rfdetr_roboflow_file_name(*, split_name: str, file_name: str) -> str:
    """生成 RF-DETR Roboflow COCO 读取约定使用的 split 相对图片路径。"""

    normalized_file_name = PurePosixPath(file_name)
    parts = [
        part
        for part in normalized_file_name.parts
        if part not in {"", "/", "."}
    ]
    if parts and parts[0] == split_name:
        return str(PurePosixPath(*parts))
    return str(PurePosixPath(split_name) / normalized_file_name.name)


def _copy_split_directory(source_dir: Path, target_dir: Path) -> None:
    """执行 `_copy_split_directory`。
    
    参数：
    - `source_dir`：传入的 `source_dir` 参数。
    - `target_dir`：传入的 `target_dir` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(source_dir, target_dir)


def _prepare_pretrain_checkpoint(
    checkpoint_path: Path | None,
    temporary_dir: Path,
) -> str | None:
    """执行 `_prepare_pretrain_checkpoint`。
    
    参数：
    - `checkpoint_path`：传入的 `checkpoint_path` 参数。
    - `temporary_dir`：传入的 `temporary_dir` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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


def _read_or_build_checkpoint_bytes(
    *,
    output_dir: Path,
    module: RFDETRModelModule,
    model_config: Any,
    train_config: TrainConfig,
    trainer: Any,
) -> bytes:
    """执行 `_read_or_build_checkpoint_bytes`。
    
    参数：
    - `output_dir`：传入的 `output_dir` 参数。
    - `module`：传入的 `module` 参数。
    - `model_config`：传入的 `model_config` 参数。
    - `train_config`：传入的 `train_config` 参数。
    - `trainer`：传入的 `trainer` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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


def _build_metrics_payload(
    *,
    output_dir: Path,
    trainer: Any,
    aligned_input_size: tuple[int, int],
) -> dict[str, object]:
    """执行 `_build_metrics_payload`。
    
    参数：
    - `output_dir`：传入的 `output_dir` 参数。
    - `trainer`：传入的 `trainer` 参数。
    - `aligned_input_size`：传入的 `aligned_input_size` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return {
        "epoch_history": _read_metrics_csv(output_dir / "metrics.csv"),
        "callback_metrics": _tensor_mapping_to_float_dict(
            getattr(trainer, "callback_metrics", {}),
        ),
        "input_size": list(aligned_input_size),
        "implementation_mode": "rfdetr-full-core",
    }


def _build_validation_metrics_payload(trainer: Any) -> dict[str, object]:
    """执行 `_build_validation_metrics_payload`。
    
    参数：
    - `trainer`：传入的 `trainer` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    metrics = _tensor_mapping_to_float_dict(getattr(trainer, "callback_metrics", {}))
    return {
        key: value
        for key, value in metrics.items()
        if key.startswith("val/") or key.startswith("test/")
    }


def _read_metrics_csv(metrics_path: Path) -> list[dict[str, object]]:
    """执行 `_read_metrics_csv`。
    
    参数：
    - `metrics_path`：传入的 `metrics_path` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    if not metrics_path.is_file():
        return []
    with metrics_path.open("r", encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        return [dict(row) for row in reader]


def _tensor_mapping_to_float_dict(payload: object) -> dict[str, float]:
    """执行 `_tensor_mapping_to_float_dict`。
    
    参数：
    - `payload`：传入的 `payload` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

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


def _resolve_best_metric(
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


def _resolve_device_name(extra_options: dict[str, object]) -> str:
    """解析训练设备名称。"""

    requested = str(extra_options.get("device", "cpu")).strip().lower()
    if requested == "cuda" or requested.startswith("cuda:"):
        return requested if torch.cuda.is_available() else "cpu"
    return "cpu"


def _precision_enables_amp(precision: str) -> bool:
    """执行 `_precision_enables_amp`。
    
    参数：
    - `precision`：传入的 `precision` 参数。
    
    返回：
    - 当前函数的执行结果。
    """

    return str(precision).strip().lower() in {"fp16", "bf16", "16-mixed", "bf16-mixed"}
