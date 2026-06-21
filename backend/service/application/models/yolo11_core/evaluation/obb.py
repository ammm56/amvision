"""YOLO11 OBB 数据集级评估入口。"""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from backend.service.application.models.evaluation.coco_style_metrics import (
    compute_coco_style_ap,
    rotated_iou_xywhr,
)
from backend.service.application.models.evaluation.obb_evaluation import (
    ObbEvaluationRequest,
    ObbEvaluationResult,
    run_obb_evaluation,
)
from backend.service.application.models.yolo11_core.data import (
    build_yolo11_obb_training_batch,
)
from backend.service.application.models.yolo11_core.postprocess import (
    build_yolo11_obb_postprocess_instances,
)
from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
from backend.service.application.runtime.support.detection import batched_nms_indices
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class Yolo11ObbEvaluationRequest:
    """描述一次 YOLO11 OBB 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    extra_options: dict[str, object] = field(default_factory=dict)


Yolo11ObbEvaluationResult = ObbEvaluationResult


def run_yolo11_obb_evaluation(
    request: Yolo11ObbEvaluationRequest,
) -> Yolo11ObbEvaluationResult:
    """执行 YOLO11 OBB 数据集级评估。"""

    return run_obb_evaluation(
        ObbEvaluationRequest(
            dataset_storage=request.dataset_storage,
            runtime_target=request.runtime_target,
            manifest_payload=request.manifest_payload,
            score_threshold=request.score_threshold,
            extra_options=dict(request.extra_options),
        ),
    )


def evaluate_yolo11_obb_samples(
    *,
    model: Any,
    samples: list[Any],
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    score_threshold: float,
    nms_threshold: float,
    imports: Any,
) -> dict[str, float]:
    """对少量验证样本执行 YOLO11 OBB 训练期评估。"""

    model.eval()
    gt_items: list[dict[str, object]] = []
    pred_items: list[dict[str, object]] = []
    total_predictions = 0
    with imports.torch.no_grad():
        for image_index, sample in enumerate(samples[:8]):
            batch = build_yolo11_obb_training_batch(
                samples=[sample],
                input_size=input_size,
                device=device,
                precision=precision,
                imports=imports,
            )
            if batch is None:
                continue
            with _yolo11_evaluation_autocast(imports, precision, device):
                outputs = model(batch.images)
            prediction_array = _yolo11_tensor_to_np(outputs, imports)
            instances = build_yolo11_obb_postprocess_instances(
                np_module=imports.np,
                prediction_array=prediction_array,
                labels=labels,
                score_threshold=score_threshold,
                resize_ratio=1.0,
                image_width=int(input_size[0]),
                image_height=int(input_size[1]),
                nms_threshold=nms_threshold,
                nms_indices_func=batched_nms_indices,
            )
            target = batch.targets[0]
            _append_yolo11_obb_gt_items(
                image_index=image_index,
                target=target,
                gt_items=gt_items,
            )
            total_predictions += len(instances)
            pred_items.extend(
                _build_yolo11_obb_prediction_items(
                    image_index=image_index,
                    predictions=instances,
                )
            )
    model.train()
    rotated_metrics = compute_coco_style_ap(
        gt_items=gt_items,
        pred_items=pred_items,
        category_names={index: name for index, name in enumerate(labels)},
        similarity_func=lambda pred, gt: rotated_iou_xywhr(
            pred["bbox_xywhr"], gt["bbox_xywhr"]
        ),
    )
    return {
        "map50": round(rotated_metrics.ap50, 6),
        "map50_95": round(rotated_metrics.ap50_95, 6),
        "rotated_map50": round(rotated_metrics.ap50, 6),
        "rotated_map50_95": round(rotated_metrics.ap50_95, 6),
        "prediction_count": float(total_predictions),
    }


def _append_yolo11_obb_gt_items(
    *,
    image_index: int,
    target: Any,
    gt_items: list[dict[str, object]],
) -> None:
    """把 YOLO11 OBB target 转成 rotated AP 使用的 GT 项。"""

    for box, class_id in zip(target.boxes_xywhr, target.category_indexes, strict=True):
        gt_items.append(
            {
                "image_id": image_index,
                "category_id": int(class_id),
                "bbox_xywhr": [float(value) for value in box],
            }
        )


def _build_yolo11_obb_prediction_items(
    *,
    image_index: int,
    predictions: tuple[Any, ...],
) -> list[dict[str, object]]:
    """把 YOLO11 OBB 后处理实例转成 rotated AP 预测项。"""

    return [
        {
            "image_id": image_index,
            "category_id": int(prediction.class_id),
            "bbox_xywhr": list(prediction.bbox_xywhr),
            "score": float(prediction.score),
        }
        for prediction in predictions
    ]


def _yolo11_evaluation_autocast(imports: Any, precision: str, device: str):
    """返回 YOLO11 OBB 训练期评估使用的 autocast 上下文。"""

    if precision != "fp16":
        return nullcontext()
    amp = getattr(imports.torch, "amp", None)
    if amp is not None and hasattr(amp, "autocast"):
        device_type = "cuda" if str(device).startswith("cuda") else "cpu"
        return amp.autocast(device_type=device_type, enabled=True)
    return nullcontext()


def _yolo11_tensor_to_np(outputs: Any, imports: Any) -> Any:
    """把 YOLO11 OBB 输出转换为 NumPy 数组。"""

    tensor = outputs[0] if isinstance(outputs, tuple) else outputs
    if isinstance(tensor, dict):
        tensor = tensor.get("prediction", tensor)
    if hasattr(tensor, "detach"):
        tensor = tensor.detach()
    if hasattr(tensor, "cpu"):
        tensor = tensor.cpu()
    if hasattr(tensor, "numpy"):
        tensor = tensor.numpy()
    array = imports.np.asarray(tensor, dtype=imports.np.float32)
    if array.ndim == 2:
        array = imports.np.expand_dims(array, axis=0)
    return array


__all__ = [
    "Yolo11ObbEvaluationRequest",
    "Yolo11ObbEvaluationResult",
    "evaluate_yolo11_obb_samples",
    "run_yolo11_obb_evaluation",
]
