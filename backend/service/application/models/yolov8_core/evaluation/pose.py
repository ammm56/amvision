"""YOLOv8 pose 评估入口。"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass, field
from typing import Any

from backend.service.application.models.evaluation.model_mode import evaluating_model

from backend.service.application.models.yolo_core_common.geometry import (
    build_yolo_letterbox_transform,
)

from backend.service.application.models.evaluation.coco_style_metrics import (
    compute_pycocotools_detection_ap,
    compute_pycocotools_pose_ap,
    resolve_keypoint_oks_sigmas,
)
from backend.service.application.models.evaluation.pose_evaluation import (
    PoseEvaluationRequest,
    PoseEvaluationResult,
    run_pose_evaluation,
)
from backend.service.application.models.yolo_core_common.training.task_dataloader import (
    YoloTaskDataLoaderPlan,
    build_yolo_task_evaluation_dataloader,
    iter_yolo_task_evaluation_items,
    load_yolo_task_dataloader_imports,
    managed_yolo_task_evaluation_dataloader,
    move_yolo_task_batch_to_device,
    resolve_yolo_task_evaluation_dataloader_plan,
)
from backend.service.application.models.yolov8_core.data import (
    build_yolov8_pose_training_batch,
)
from backend.service.application.models.yolov8_core.postprocess import (
    build_yolov8_pose_postprocess_instances,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.application.runtime.support.detection import batched_nms_indices
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


@dataclass(frozen=True)
class YoloV8PoseEvaluationRequest:
    """描述一次 YOLOv8 pose 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.001
    extra_options: dict[str, object] = field(default_factory=dict)


YoloV8PoseEvaluationResult = PoseEvaluationResult


def run_yolov8_pose_evaluation(
    request: YoloV8PoseEvaluationRequest,
) -> YoloV8PoseEvaluationResult:
    """执行 YOLOv8 pose 数据集级评估。"""

    return run_pose_evaluation(
        PoseEvaluationRequest(
            dataset_storage=request.dataset_storage,
            runtime_target=request.runtime_target,
            manifest_payload=request.manifest_payload,
            score_threshold=request.score_threshold,
            extra_options=dict(request.extra_options),
        ),
    )


def evaluate_yolov8_pose_samples(
    *,
    model: Any,
    samples: list[Any],
    labels: tuple[str, ...],
    input_size: tuple[int, int],
    device: str,
    precision: str,
    score_threshold: float,
    nms_threshold: float,
    kpt_shape: tuple[int, int],
    imports: Any,
    batch_size: int = 1,
    dataloader_plan: YoloTaskDataLoaderPlan | None = None,
    control_callback: Callable[[], None] | None = None,
) -> dict[str, float]:
    """对少量验证样本执行 YOLOv8 pose 训练期评估。"""

    gt_items: list[dict[str, object]] = []
    pred_items: list[dict[str, object]] = []
    total_predictions = 0
    evaluation_loader = build_yolo_task_evaluation_dataloader(
        torch_module=imports.torch,
        samples=samples,
        batch_size=batch_size,
        input_size=input_size,
        plan=dataloader_plan
        or resolve_yolo_task_evaluation_dataloader_plan(device=device),
        build_batch=build_yolov8_pose_training_batch,
        load_imports=load_yolo_task_dataloader_imports,
    )
    next_image_index = 0
    letterbox_transform = build_yolo_letterbox_transform(
        source_width=int(input_size[1]),
        source_height=int(input_size[0]),
        input_size=input_size,
    )
    with (
        managed_yolo_task_evaluation_dataloader(evaluation_loader),
        evaluating_model(model),
        imports.torch.no_grad(),
    ):
        for batch in evaluation_loader:
            if control_callback is not None:
                control_callback()
            if batch is None:
                continue
            batch = move_yolo_task_batch_to_device(
                batch=batch,
                device=device,
                precision=precision,
                torch_module=imports.torch,
            )
            with _yolov8_evaluation_autocast(imports, precision, device):
                outputs = model(batch.images)
            prediction_array = _yolov8_tensor_to_np(outputs, imports)
            for image_index, target, output_slices in iter_yolo_task_evaluation_items(
                targets=batch.targets,
                batched_outputs=(prediction_array,),
                image_index_start=next_image_index,
            ):
                instances, _ = build_yolov8_pose_postprocess_instances(
                    np_module=imports.np,
                    prediction_array=output_slices[0],
                    labels=labels,
                    score_threshold=score_threshold,
                    # 评估必须保留所有坐标；该阈值仅用于推理结果显示。
                    keypoint_confidence_threshold=0.0,
                    letterbox_transform=letterbox_transform,
                    default_kpt_shape=kpt_shape,
                    nms_threshold=nms_threshold,
                    nms_indices_func=batched_nms_indices,
                )
                _append_yolov8_pose_gt_items(
                    image_index=image_index,
                    target=target,
                    gt_items=gt_items,
                )
                total_predictions += len(instances)
                pred_items.extend(
                    _build_yolov8_pose_prediction_items(
                        image_index=image_index,
                        predictions=instances,
                    )
                )
            next_image_index += len(batch.targets)
    if control_callback is not None:
        control_callback()
    category_names = {index: name for index, name in enumerate(labels)}
    bbox_metrics = compute_pycocotools_detection_ap(
        gt_items=gt_items,
        pred_items=pred_items,
        category_names=category_names,
        image_count=next_image_index,
    )
    oks_metrics = compute_pycocotools_pose_ap(
        gt_items=gt_items,
        pred_items=pred_items,
        category_names=category_names,
        image_count=next_image_index,
        keypoint_count=int(kpt_shape[0]),
        keypoint_oks_sigmas=resolve_keypoint_oks_sigmas(int(kpt_shape[0])),
    )
    return {
        "map50": round(bbox_metrics.ap50, 6),
        "map50_95": round(bbox_metrics.ap50_95, 6),
        "bbox_map50": round(bbox_metrics.ap50, 6),
        "bbox_map50_95": round(bbox_metrics.ap50_95, 6),
        "oks_ap50": round(oks_metrics.ap50, 6),
        "oks_ap50_95": round(oks_metrics.ap50_95, 6),
        "prediction_count": float(total_predictions),
    }


def _append_yolov8_pose_gt_items(
    *,
    image_index: int,
    target: Any,
    gt_items: list[dict[str, object]],
) -> None:
    """把 YOLOv8 pose target 转成 OKS AP 使用的 GT 项。"""

    keypoints_group = target.keypoints or []
    for object_index, (box, class_id) in enumerate(
        zip(target.boxes_xyxy, target.category_indexes, strict=True)
    ):
        if object_index >= len(keypoints_group) or not keypoints_group[object_index]:
            continue
        gt_items.append(
            {
                "image_id": image_index,
                "category_id": int(class_id),
                "keypoints": [float(value) for value in keypoints_group[object_index]],
                "bbox_xyxy": [float(value) for value in box],
                "area": _yolov8_pose_box_area(box),
            }
        )


def _build_yolov8_pose_prediction_items(
    *,
    image_index: int,
    predictions: tuple[Any, ...],
) -> list[dict[str, object]]:
    """把 YOLOv8 pose 后处理实例转成 OKS AP 预测项。"""

    items: list[dict[str, object]] = []
    for prediction in predictions:
        items.append(
            {
                "image_id": image_index,
                "category_id": int(prediction.class_id),
                "keypoints": _flatten_yolov8_pose_prediction_keypoints(
                    prediction.keypoints
                ),
                "bbox_xyxy": [float(value) for value in prediction.bbox_xyxy],
                "score": float(prediction.score),
            }
        )
    return items


def _flatten_yolov8_pose_prediction_keypoints(
    keypoints: tuple[Any, ...],
) -> list[float]:
    """把 YOLOv8 pose 后处理 keypoints 展平成 COCO 格式。"""

    flattened: list[float] = []
    for keypoint in keypoints:
        confidence = keypoint.confidence
        flattened.extend(
            [
                float(keypoint.x),
                float(keypoint.y),
                2.0 if confidence is None else float(confidence),
            ]
        )
    return flattened


def _yolov8_pose_box_area(box: list[float] | tuple[float, ...]) -> float:
    """用 bbox 面积作为 OKS area。"""

    return max((float(box[2]) - float(box[0])) * (float(box[3]) - float(box[1])), 1.0)


def _yolov8_evaluation_autocast(imports: Any, precision: str, device: str):
    """返回 YOLOv8 训练期评估使用的 autocast 上下文。"""

    if precision != "fp16":
        return nullcontext()
    amp = getattr(imports.torch, "amp", None)
    if amp is not None and hasattr(amp, "autocast"):
        device_type = "cuda" if str(device).startswith("cuda") else "cpu"
        return amp.autocast(device_type=device_type, enabled=True)
    return nullcontext()


def _yolov8_tensor_to_np(outputs: Any, imports: Any) -> Any:
    """把 YOLOv8 pose 输出转换为 NumPy 数组。"""

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
    "YoloV8PoseEvaluationRequest",
    "YoloV8PoseEvaluationResult",
    "evaluate_yolov8_pose_samples",
    "run_yolov8_pose_evaluation",
]
