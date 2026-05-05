"""YOLOX 数据集级评估执行链。"""

from __future__ import annotations

from collections import Counter
from contextlib import redirect_stdout
from dataclasses import dataclass, field
import io
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol

from backend.service.application.errors import InvalidRequestError, ServiceConfigurationError
from backend.service.application.models.yolox_detection_training import (
    _CocoDetectionExportDataset,
    _ResolvedCocoSplit,
    _build_autocast_context,
    _build_yolox_model,
    _convert_predictions_to_coco_detections,
    _extract_batch_image_id,
    _extract_batch_image_info,
    _load_coco_ground_truth_silently,
    _load_warm_start_checkpoint,
    _require_training_imports,
    _resolve_coco_splits,
    _resolve_train_split,
    _resolve_validation_split,
)
from backend.service.application.runtime.yolox_runtime_target import RuntimeTargetSnapshot
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


YOLOX_EVALUATION_IMPLEMENTATION_MODE = "yolox-evaluation-minimal"
YOLOX_EVALUATION_DEFAULT_BATCH_SIZE = 1
YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD = 0.01
YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD = 0.65


@dataclass(frozen=True)
class YoloXDetectionEvaluationRequest:
    """描述一次最小 YOLOX 数据集级评估请求。

    字段：
    - dataset_storage：本地文件存储服务。
    - dataset_export_manifest_key：评估输入 manifest object key。
    - dataset_export_id：评估输入 DatasetExport id。
    - dataset_version_id：评估输入 DatasetVersion id。
    - runtime_target：评估使用的运行时快照。
    - score_threshold：评估 score threshold。
    - nms_threshold：评估 NMS threshold。
    - extra_options：附加评估选项。
    """

    dataset_storage: LocalDatasetStorage
    dataset_export_manifest_key: str
    dataset_export_id: str
    dataset_version_id: str
    runtime_target: RuntimeTargetSnapshot
    score_threshold: float = YOLOX_EVALUATION_DEFAULT_SCORE_THRESHOLD
    nms_threshold: float = YOLOX_EVALUATION_DEFAULT_NMS_THRESHOLD
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class YoloXDetectionEvaluationResult:
    """描述一次最小 YOLOX 数据集级评估结果。"""

    split_name: str
    sample_count: int
    duration_seconds: float
    map50: float
    map50_95: float
    per_class_metrics: tuple[dict[str, object], ...]
    detections: tuple[dict[str, object], ...]
    report_payload: dict[str, object]
    detections_payload: dict[str, object]


class YoloXEvaluator(Protocol):
    """定义 YOLOX 数据集级 evaluator 接口。"""

    def evaluate(self, request: YoloXDetectionEvaluationRequest) -> YoloXDetectionEvaluationResult:
        """执行一次数据集级评估。

        参数：
        - request：评估请求。

        返回：
        - YoloXDetectionEvaluationResult：评估结果。
        """


class PyTorchYoloXEvaluator:
    """基于 PyTorch checkpoint 的 YOLOX 数据集级 evaluator。"""

    def evaluate(self, request: YoloXDetectionEvaluationRequest) -> YoloXDetectionEvaluationResult:
        """执行一次 PyTorch YOLOX 数据集级评估。

        参数：
        - request：评估请求。

        返回：
        - YoloXDetectionEvaluationResult：评估结果。
        """

        return run_yolox_detection_evaluation(request)


def run_yolox_detection_evaluation(
    request: YoloXDetectionEvaluationRequest,
) -> YoloXDetectionEvaluationResult:
    """执行一次最小 YOLOX 数据集级评估。"""

    imports = _require_training_imports()
    manifest_payload = request.dataset_storage.read_json(request.dataset_export_manifest_key)
    if not isinstance(manifest_payload, dict):
        raise InvalidRequestError(
            "评估输入 manifest 内容不合法",
            details={"manifest_object_key": request.dataset_export_manifest_key},
        )

    resolved_splits = _resolve_coco_splits(request.dataset_storage, manifest_payload)
    evaluation_split = _resolve_evaluation_split(
        resolved_splits=resolved_splits,
        requested_split_name=_read_optional_str_option(request.extra_options, "split_name"),
    )
    batch_size = _read_positive_int_option(
        request.extra_options,
        "batch_size",
        default=YOLOX_EVALUATION_DEFAULT_BATCH_SIZE,
    )
    device_name = _resolve_evaluation_device_name(
        torch_module=imports.torch,
        requested_device_name=_read_optional_str_option(request.extra_options, "device")
        or _read_optional_str_option(request.extra_options, "device_name")
        or request.runtime_target.device_name,
    )
    precision = _resolve_evaluation_precision(
        imports=imports,
        requested_precision=_read_optional_str_option(request.extra_options, "precision") or "fp32",
        device_name=device_name,
    )
    dataset = _CocoDetectionExportDataset(
        annotation_file=evaluation_split.annotation_file,
        image_root=evaluation_split.image_root,
        input_size=request.runtime_target.input_size,
        imports=imports,
        flip_prob=0.0,
        hsv_prob=0.0,
        max_labels=_read_positive_int_option(request.extra_options, "max_labels", default=120),
    )
    if len(request.runtime_target.labels) != len(dataset.category_ids):
        raise InvalidRequestError(
            "模型类别数量与评估数据集 categories 数量不一致",
            details={
                "model_version_id": request.runtime_target.model_version_id,
                "label_count": len(request.runtime_target.labels),
                "dataset_category_count": len(dataset.category_ids),
            },
        )

    data_loader = imports.torch.utils.data.DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=False,
        drop_last=False,
        num_workers=0,
        pin_memory=device_name.startswith("cuda"),
    )
    if request.runtime_target.runtime_backend != "pytorch":
        raise InvalidRequestError(
            "当前 evaluator 仅支持 pytorch runtime_backend",
            details={
                "runtime_backend": request.runtime_target.runtime_backend,
                "model_build_id": request.runtime_target.model_build_id,
            },
        )
    model = _build_yolox_model(
        imports=imports,
        model_scale=request.runtime_target.model_scale,
        num_classes=len(request.runtime_target.labels),
    )
    _load_warm_start_checkpoint(
        imports=imports,
        model=model,
        checkpoint_path=request.runtime_target.runtime_artifact_path,
        source_summary={
            "source_model_version_id": request.runtime_target.model_version_id,
            "source_model_build_id": request.runtime_target.model_build_id,
            "runtime_artifact_file_id": request.runtime_target.runtime_artifact_file_id,
            "runtime_artifact_storage_uri": request.runtime_target.runtime_artifact_storage_uri,
        },
    )
    model.to(device_name)
    model.eval()

    started_at = perf_counter()
    detections = _collect_coco_detections(
        imports=imports,
        model=model,
        loader=data_loader,
        device_name=device_name,
        precision=precision,
        input_size=request.runtime_target.input_size,
        num_classes=len(request.runtime_target.labels),
        category_ids=dataset.category_ids,
        score_threshold=request.score_threshold,
        nms_threshold=request.nms_threshold,
    )
    evaluation_summary = _evaluate_coco_metrics(
        imports=imports,
        annotation_file=evaluation_split.annotation_file,
        detections=detections,
        category_ids=dataset.category_ids,
        category_names=request.runtime_target.labels,
    )
    duration_seconds = round(perf_counter() - started_at, 6)
    report_payload = {
        "implementation_mode": YOLOX_EVALUATION_IMPLEMENTATION_MODE,
        "model_version_id": request.runtime_target.model_version_id,
        "dataset_export_id": request.dataset_export_id,
        "dataset_version_id": request.dataset_version_id,
        "dataset_export_manifest_key": request.dataset_export_manifest_key,
        "split_name": evaluation_split.name,
        "sample_count": len(dataset),
        "device": device_name,
        "precision": precision,
        "input_size": [request.runtime_target.input_size[0], request.runtime_target.input_size[1]],
        "score_threshold": request.score_threshold,
        "nms_threshold": request.nms_threshold,
        "duration_seconds": duration_seconds,
        "detection_count": len(detections),
        "map50": evaluation_summary["map50"],
        "map50_95": evaluation_summary["map50_95"],
        "per_class_metrics": [dict(item) for item in evaluation_summary["per_class_metrics"]],
    }
    detections_payload = {
        "model_version_id": request.runtime_target.model_version_id,
        "dataset_export_id": request.dataset_export_id,
        "dataset_version_id": request.dataset_version_id,
        "split_name": evaluation_split.name,
        "sample_count": len(dataset),
        "detection_count": len(detections),
        "detections": [dict(item) for item in detections],
    }
    return YoloXDetectionEvaluationResult(
        split_name=evaluation_split.name,
        sample_count=len(dataset),
        duration_seconds=duration_seconds,
        map50=float(evaluation_summary["map50"]),
        map50_95=float(evaluation_summary["map50_95"]),
        per_class_metrics=tuple(dict(item) for item in evaluation_summary["per_class_metrics"]),
        detections=tuple(dict(item) for item in detections),
        report_payload=report_payload,
        detections_payload=detections_payload,
    )


def _resolve_evaluation_split(
    *,
    resolved_splits: tuple[_ResolvedCocoSplit, ...],
    requested_split_name: str | None,
) -> _ResolvedCocoSplit:
    """解析当前评估应使用的 split。"""

    if requested_split_name is not None:
        for split in resolved_splits:
            if split.name == requested_split_name:
                return split
        raise InvalidRequestError(
            "指定的 split_name 在当前 DatasetExport 中不存在",
            details={"split_name": requested_split_name},
        )

    train_split = _resolve_train_split(resolved_splits)
    validation_split = _resolve_validation_split(
        resolved_splits,
        train_split_name=train_split.name,
    )
    return validation_split or train_split


def _collect_coco_detections(
    *,
    imports: Any,
    model: Any,
    loader: Any,
    device_name: str,
    precision: str,
    input_size: tuple[int, int],
    num_classes: int,
    category_ids: tuple[int, ...],
    score_threshold: float,
    nms_threshold: float,
) -> tuple[dict[str, object], ...]:
    """把整套评估数据集转换为 COCO detection 结果列表。"""

    detections: list[dict[str, object]] = []
    with imports.torch.no_grad():
        for images, _targets, image_infos, image_ids in loader:
            images = images.to(device=device_name, dtype=imports.torch.float32)
            with _build_autocast_context(
                imports=imports,
                device=device_name,
                precision=precision,
            ):
                raw_outputs = model(images)
            processed_outputs = imports.postprocess(
                raw_outputs,
                num_classes,
                conf_thre=score_threshold,
                nms_thre=nms_threshold,
                class_agnostic=False,
            )
            detections.extend(
                _convert_predictions_to_coco_detections(
                    predictions=processed_outputs,
                    image_infos=image_infos,
                    image_ids=image_ids,
                    input_size=input_size,
                    category_ids=category_ids,
                )
            )

    return tuple(detections)


def _evaluate_coco_metrics(
    *,
    imports: Any,
    annotation_file: Path,
    detections: tuple[dict[str, object], ...],
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
) -> dict[str, object]:
    """基于 COCOeval 生成全局 mAP 和 per-class metrics。"""

    ground_truth = _load_coco_ground_truth_silently(
        imports=imports,
        annotation_file=annotation_file,
    )
    per_class_metrics = _build_zero_per_class_metrics(
        ground_truth=ground_truth,
        category_ids=category_ids,
        category_names=category_names,
        detections=detections,
    )
    if not detections:
        return {
            "map50": 0.0,
            "map50_95": 0.0,
            "per_class_metrics": per_class_metrics,
        }

    with redirect_stdout(io.StringIO()):
        coco_detections = ground_truth.loadRes(list(detections))
        coco_evaluator = imports.COCOeval(ground_truth, coco_detections, "bbox")
        coco_evaluator.evaluate()
        coco_evaluator.accumulate()
        coco_evaluator.summarize()

    return {
        "map50_95": float(coco_evaluator.stats[0]),
        "map50": float(coco_evaluator.stats[1]),
        "per_class_metrics": _build_per_class_metrics(
            coco_evaluator=coco_evaluator,
            ground_truth=ground_truth,
            category_ids=category_ids,
            category_names=category_names,
            detections=detections,
        ),
    }


def _build_per_class_metrics(
    *,
    coco_evaluator: Any,
    ground_truth: Any,
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
    detections: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """从 COCOeval 结果中提取每个类别的 AP 指标。"""

    detection_counts = Counter(
        int(detection["category_id"])
        for detection in detections
        if isinstance(detection.get("category_id"), int)
    )
    precision = coco_evaluator.eval.get("precision")
    if precision is None:
        return _build_zero_per_class_metrics(
            ground_truth=ground_truth,
            category_ids=category_ids,
            category_names=category_names,
            detections=detections,
        )

    iou_thresholds = list(coco_evaluator.params.iouThrs)
    ap50_index = next(
        (
            threshold_index
            for threshold_index, threshold in enumerate(iou_thresholds)
            if abs(float(threshold) - 0.5) < 1e-6
        ),
        0,
    )
    per_class_metrics: list[dict[str, object]] = []
    for class_index, category_id in enumerate(category_ids):
        class_name = (
            category_names[class_index]
            if class_index < len(category_names)
            else f"class-{category_id}"
        )
        all_precision = precision[:, :, class_index, 0, -1]
        valid_all_precision = all_precision[all_precision > -1]
        ap50_95 = (
            float(valid_all_precision.mean())
            if getattr(valid_all_precision, "size", 0) > 0
            else 0.0
        )

        precision50 = precision[ap50_index, :, class_index, 0, -1]
        valid_precision50 = precision50[precision50 > -1]
        ap50 = (
            float(valid_precision50.mean())
            if getattr(valid_precision50, "size", 0) > 0
            else 0.0
        )
        per_class_metrics.append(
            {
                "category_id": category_id,
                "class_index": class_index,
                "class_name": class_name,
                "ground_truth_count": len(ground_truth.getAnnIds(catIds=[category_id])),
                "detection_count": detection_counts.get(category_id, 0),
                "ap50": round(ap50, 6),
                "ap50_95": round(ap50_95, 6),
            }
        )
    return tuple(per_class_metrics)


def _build_zero_per_class_metrics(
    *,
    ground_truth: Any,
    category_ids: tuple[int, ...],
    category_names: tuple[str, ...],
    detections: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    """构建无评估结果时的 per-class metrics 占位值。"""

    detection_counts = Counter(
        int(detection["category_id"])
        for detection in detections
        if isinstance(detection.get("category_id"), int)
    )
    return tuple(
        {
            "category_id": category_id,
            "class_index": class_index,
            "class_name": (
                category_names[class_index]
                if class_index < len(category_names)
                else f"class-{category_id}"
            ),
            "ground_truth_count": len(ground_truth.getAnnIds(catIds=[category_id])),
            "detection_count": detection_counts.get(category_id, 0),
            "ap50": 0.0,
            "ap50_95": 0.0,
        }
        for class_index, category_id in enumerate(category_ids)
    )


def _resolve_evaluation_device_name(*, torch_module: Any, requested_device_name: str) -> str:
    """校验并返回本次评估实际使用的 device。"""

    if requested_device_name == "cpu":
        return "cpu"
    if requested_device_name == "cuda":
        requested_device_name = "cuda:0"
    if requested_device_name.startswith("cuda:"):
        if not torch_module.cuda.is_available():
            raise InvalidRequestError(
                "当前运行环境没有可用 GPU，不能使用 CUDA 评估",
                details={"device_name": requested_device_name},
            )
        raw_index = requested_device_name.split(":", 1)[1]
        if not raw_index.isdigit():
            raise InvalidRequestError(
                "device_name 必须是 cpu、cuda 或 cuda:<index>",
                details={"device_name": requested_device_name},
            )
        device_index = int(raw_index)
        available_count = int(torch_module.cuda.device_count())
        if device_index >= available_count:
            raise InvalidRequestError(
                "指定的 CUDA device 超出了本机可用 GPU 范围",
                details={
                    "device_name": requested_device_name,
                    "available_gpu_count": available_count,
                },
            )
        return requested_device_name
    raise InvalidRequestError(
        "device_name 必须是 cpu、cuda 或 cuda:<index>",
        details={"device_name": requested_device_name},
    )


def _resolve_evaluation_precision(
    *,
    imports: Any,
    requested_precision: str,
    device_name: str,
) -> str:
    """解析当前评估使用的 precision。"""

    if requested_precision not in {"fp16", "fp32"}:
        raise InvalidRequestError(
            "precision 必须是 fp16 或 fp32",
            details={"precision": requested_precision},
        )
    if requested_precision == "fp16" and not device_name.startswith("cuda"):
        raise InvalidRequestError("fp16 评估需要 CUDA 环境")
    if requested_precision == "fp16" and not hasattr(imports.torch, "autocast"):
        raise ServiceConfigurationError("当前 torch 版本缺少 autocast，无法执行 fp16 评估")
    return requested_precision


def _read_positive_int_option(extra_options: dict[str, object], key: str, *, default: int) -> int:
    """从 extra_options 中读取正整数配置。"""

    value = extra_options.get(key)
    if isinstance(value, int) and value > 0:
        return value
    return default


def _read_optional_str_option(extra_options: dict[str, object], key: str) -> str | None:
    """从 extra_options 中读取可选字符串配置。"""

    value = extra_options.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None