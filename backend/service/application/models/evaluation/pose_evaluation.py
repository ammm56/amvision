"""Pose 数据集级评估执行模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.evaluation.coco_style_metrics import (
    compute_pycocotools_detection_ap,
    compute_pycocotools_pose_ap,
    resolve_keypoint_oks_sigmas,
)
from backend.service.application.models.evaluation.manifest_splits import (
    select_independent_evaluation_split,
)
from backend.service.application.models.support.yolo_dataset_manifest_support import (
    build_coco_payload_from_yolo_pose_split,
    normalize_yolo_category_names,
)
from backend.service.application.runtime.contracts.pose.prediction import (
    PosePredictionRequest,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetSnapshot,
)
from backend.service.application.runtime.session_lifecycle import RuntimeSessionLease
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)


DefaultPoseModelRuntime: type | None = None


@dataclass(frozen=True)
class PoseEvaluationRequest:
    """描述一次 pose 数据集级评估请求。"""

    dataset_storage: LocalDatasetStorage
    runtime_target: RuntimeTargetSnapshot
    manifest_payload: dict[str, object]
    score_threshold: float = 0.01
    extra_options: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class PoseEvaluationResult:
    """Pose 评估结果。"""

    sample_count: int
    bbox_map50: float
    bbox_map50_95: float
    oks_ap50: float
    oks_ap50_95: float
    duration_seconds: float
    report_object_key: str
    per_class_metrics: list[dict] = field(default_factory=list)
    predictions_payload: list[dict] = field(default_factory=list)
    report_payload: dict[str, object] = field(default_factory=dict)


def run_pose_evaluation(request: PoseEvaluationRequest) -> PoseEvaluationResult:
    """执行 Pose 数据集级评估（简化版 OKS AP 计算）。"""
    dataset_storage = request.dataset_storage
    manifest = request.manifest_payload
    score_threshold = request.score_threshold
    output_prefix = f"task-runs/evaluation/{request.runtime_target.model_version_id}"
    _, samples, categories = _parse_pose_manifest(manifest, dataset_storage)

    runtime_class = DefaultPoseModelRuntime
    if runtime_class is None:
        from backend.service.application.runtime.tasks.pose_model_runtime import (
            DefaultPoseModelRuntime as runtime_class,
        )

    model_runtime = runtime_class()
    session = RuntimeSessionLease(
        model_runtime.load_session(
            dataset_storage=dataset_storage,
            runtime_target=request.runtime_target,
        )
    )
    try:
        return _run_pose_evaluation_with_session(
            request=request,
            dataset_storage=dataset_storage,
            score_threshold=score_threshold,
            output_prefix=output_prefix,
            samples=samples,
            categories=categories,
            session=session,
        )
    finally:
        session.close()


def _run_pose_evaluation_with_session(
    *,
    request: PoseEvaluationRequest,
    dataset_storage: LocalDatasetStorage,
    score_threshold: float,
    output_prefix: str,
    samples: list[dict[str, object]],
    categories: list[dict[str, Any]],
    session: RuntimeSessionLease,
) -> PoseEvaluationResult:
    """在受控 runtime session 内计算 pose 指标。"""

    started_at = datetime.now(timezone.utc)

    # 收集预测
    all_preds: list[dict] = []
    all_gts: list[dict] = []
    processed_count = 0

    for image_index, sample in enumerate(samples):
        image_path = str(sample.get("image_path", "")).strip()
        gt_anns = sample.get("annotations", [])
        if not isinstance(gt_anns, list):
            gt_anns = []
        resolved = (
            dataset_storage.resolve_filesystem_path(image_path) if image_path else None
        )
        if not resolved or not resolved.is_file():
            raise InvalidRequestError(
                "pose 评估样本文件不存在",
                details={"image_path": image_path},
            )

        image_bytes = resolved.read_bytes()
        pred_request = PosePredictionRequest(
            score_threshold=score_threshold,
            # COCO OKS 使用所有预测坐标；显示阈值不能改写评估几何。
            keypoint_confidence_threshold=0.0,
            save_result_image=False,
            input_image_bytes=image_bytes,
        )

        result = session.predict(pred_request)

        processed_count += 1

        # 收集 GT keypoints
        for gt_ann in gt_anns:
            if not isinstance(gt_ann, dict):
                continue
            kpts = gt_ann.get("keypoints", [])
            if kpts:
                all_gts.append(
                    {
                        "image_id": image_index,
                        "category_id": gt_ann.get("category_id", 0),
                        "keypoints": kpts,
                        "num_keypoints": gt_ann.get("num_keypoints", len(kpts) // 3),
                        "bbox_xyxy": _resolve_pose_annotation_bbox_xyxy(gt_ann),
                        "area": _resolve_pose_annotation_area(gt_ann),
                    },
                )

        # 收集预测 keypoints
        for det in _iter_pose_prediction_instances(result):
            all_preds.append(
                {
                    "image_id": image_index,
                    "category_id": det.class_id,
                    "keypoints": _flatten_pose_keypoints(det.keypoints),
                    "bbox_xyxy": [float(value) for value in det.bbox_xyxy],
                    "score": det.score,
                }
            )

    category_names = {
        int(cat.get("id", 0)): str(cat.get("name", cat.get("id", 0)))
        for cat in categories
    }
    keypoint_count = max(
        (len(item.get("keypoints", ())) // 3 for item in all_gts),
        default=0,
    )
    oks_sigmas = _resolve_oks_sigmas(
        request.extra_options,
        num_keypoints=keypoint_count,
    )
    bbox_metrics = compute_pycocotools_detection_ap(
        gt_items=all_gts,
        pred_items=all_preds,
        category_names=category_names,
        image_count=len(samples),
    )
    oks_metrics = compute_pycocotools_pose_ap(
        gt_items=all_gts,
        pred_items=all_preds,
        category_names=category_names,
        image_count=len(samples),
        keypoint_count=keypoint_count,
        keypoint_oks_sigmas=oks_sigmas,
    )

    finished_at = datetime.now(timezone.utc)
    duration = (finished_at - started_at).total_seconds()

    # 写报告
    report_key = f"{output_prefix}/reports/pose_evaluation.json"
    report = {
        "sample_count": processed_count,
        "bbox_map50": bbox_metrics.ap50,
        "bbox_map50_95": bbox_metrics.ap50_95,
        "oks_ap50": oks_metrics.ap50,
        "oks_ap50_95": oks_metrics.ap50_95,
        "duration_seconds": duration,
        "per_class_metrics": oks_metrics.per_class_metrics,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }
    dataset_storage.write_json(report_key, report)

    return PoseEvaluationResult(
        sample_count=processed_count,
        bbox_map50=bbox_metrics.ap50,
        bbox_map50_95=bbox_metrics.ap50_95,
        oks_ap50=oks_metrics.ap50,
        oks_ap50_95=oks_metrics.ap50_95,
        duration_seconds=duration,
        report_object_key=report_key,
        per_class_metrics=oks_metrics.per_class_metrics,
        predictions_payload=all_preds,
        report_payload=report,
    )


def _parse_pose_manifest(
    manifest: dict[str, object],
    dataset_storage: LocalDatasetStorage,
) -> tuple[str, list[dict[str, object]], list[dict[str, Any]]]:
    """解析 pose export manifest。"""

    splits = manifest.get("splits", [])
    chosen_split = select_independent_evaluation_split(splits)
    if chosen_split is None:
        raise InvalidRequestError("pose manifest 不包含可用的 split")

    split_name = str(chosen_split.get("name", "unknown"))
    image_root = str(chosen_split.get("image_root", "")).strip()
    annotation_file = str(chosen_split.get("annotation_file", "")).strip()
    label_root = str(chosen_split.get("label_root", "")).strip()
    if annotation_file:
        annotation_payload = dataset_storage.read_json(annotation_file)
        if not isinstance(annotation_payload, dict):
            raise InvalidRequestError(
                "pose annotation 文件格式无效",
                details={"annotation_file": annotation_file},
            )
        categories = _normalize_pose_categories(annotation_payload.get("categories"))
        return (
            split_name,
            _build_pose_samples(image_root=image_root, payload=annotation_payload),
            categories,
        )
    if label_root:
        category_names = normalize_yolo_category_names(
            category_names=manifest.get("category_names"),
            format_label="YOLO pose",
        )
        image_root_path = dataset_storage.resolve_filesystem_path(image_root)
        label_root_path = dataset_storage.resolve_filesystem_path(label_root)
        if not image_root_path.is_dir():
            raise InvalidRequestError(
                "pose 图片目录不存在",
                details={"image_root": image_root, "split_name": split_name},
            )
        if not label_root_path.is_dir():
            raise InvalidRequestError(
                "pose 标签目录不存在",
                details={"label_root": label_root, "split_name": split_name},
            )
        payload = build_coco_payload_from_yolo_pose_split(
            split_name=split_name,
            image_root=image_root_path,
            label_root=label_root_path,
            category_names=category_names,
        )
        categories = _normalize_pose_categories(payload.get("categories"))
        return (
            split_name,
            _build_pose_samples(image_root=image_root, payload=payload),
            categories,
        )
    categories = _normalize_pose_categories(manifest.get("categories"))
    return (
        split_name,
        _build_pose_samples(image_root=image_root, payload=chosen_split),
        categories,
    )


def _build_pose_samples(
    *,
    image_root: str,
    payload: dict[str, object],
) -> list[dict[str, object]]:
    """把 COCO 风格 pose 标注组装成按图片分组的样本列表。"""

    images_by_id: dict[int, str] = {}
    for image in payload.get("images") or []:
        if not isinstance(image, dict):
            continue
        image_id = image.get("id")
        file_name = str(image.get("file_name", "")).strip()
        if not isinstance(image_id, int) or not file_name:
            continue
        images_by_id[image_id] = file_name

    anns_by_image: dict[int, list[dict[str, object]]] = {}
    for ann in payload.get("annotations") or []:
        if not isinstance(ann, dict):
            continue
        image_id = ann.get("image_id")
        if not isinstance(image_id, int):
            continue
        anns_by_image.setdefault(image_id, []).append(ann)

    samples: list[dict[str, object]] = []
    for image_id, file_name in images_by_id.items():
        full_path = f"{image_root}/{file_name}" if image_root else file_name
        samples.append(
            {
                "image_path": full_path,
                "annotations": anns_by_image.get(image_id, []),
            }
        )
    return samples


def _normalize_pose_categories(categories_payload: object) -> list[dict[str, Any]]:
    """归一化 pose 类别列表。"""

    categories: list[dict[str, Any]] = []
    for category in categories_payload if isinstance(categories_payload, list) else ():
        if not isinstance(category, dict):
            continue
        category_id = category.get("id", category.get("category_id"))
        if not isinstance(category_id, int):
            continue
        categories.append(
            {"id": category_id, "name": str(category.get("name", category_id))}
        )
    return categories


def _iter_pose_prediction_instances(result: object):
    """返回当前 runtime contract 下的 pose instance 列表。"""

    instances = getattr(result, "instances", None)
    if instances is not None:
        return instances
    return getattr(result, "detections", ())


def _flatten_pose_keypoints(keypoints: object) -> list[float]:
    """把 pose keypoint 对象归一化为 COCO 风格扁平列表。"""

    if not isinstance(keypoints, (list, tuple)):
        return []
    flattened: list[float] = []
    for keypoint in keypoints:
        if isinstance(keypoint, (int, float)):
            flattened.append(float(keypoint))
            continue
        x = float(getattr(keypoint, "x", 0.0))
        y = float(getattr(keypoint, "y", 0.0))
        confidence = getattr(keypoint, "confidence", None)
        visibility = 2.0 if confidence is None else float(confidence)
        flattened.extend([x, y, visibility])
    return flattened


def _resolve_pose_annotation_area(annotation: dict[str, object]) -> float:
    """解析 pose 标注面积，缺失时用 bbox 面积兜底。"""

    area = annotation.get("area")
    if area is not None:
        return max(float(area), 1.0)
    bbox = annotation.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        return max(float(bbox[2]) * float(bbox[3]), 1.0)
    return 1.0


def _resolve_pose_annotation_bbox_xyxy(
    annotation: dict[str, object],
) -> list[float]:
    """把 COCO xywh bbox 转为共享 pose evaluator 使用的 xyxy。"""

    bbox = annotation.get("bbox")
    if isinstance(bbox, list) and len(bbox) >= 4:
        x, y, width, height = (float(value) for value in bbox[:4])
        return [x, y, x + max(width, 0.0), y + max(height, 0.0)]
    keypoints = annotation.get("keypoints")
    if isinstance(keypoints, list):
        visible = [
            (float(keypoints[index]), float(keypoints[index + 1]))
            for index in range(0, len(keypoints) - 2, 3)
            if float(keypoints[index + 2]) > 0.0
        ]
        if visible:
            xs = [point[0] for point in visible]
            ys = [point[1] for point in visible]
            return [min(xs), min(ys), max(xs), max(ys)]
    raise InvalidRequestError("pose 标注缺少有效 bbox 和可见关键点")


def _resolve_oks_sigmas(
    extra_options: dict[str, object],
    *,
    num_keypoints: int,
) -> tuple[float, ...]:
    """解析 OKS sigma，并校验它与当前 pose 拓扑严格一致。"""

    raw_sigmas = extra_options.get("oks_sigmas")
    if isinstance(raw_sigmas, list) and raw_sigmas:
        sigmas = tuple(float(value) for value in raw_sigmas)
        if len(sigmas) != int(num_keypoints):
            raise InvalidRequestError(
                "pose oks_sigmas 数量与关键点拓扑不一致",
                details={
                    "num_keypoints": int(num_keypoints),
                    "sigma_count": len(sigmas),
                },
            )
        if any(value <= 0.0 for value in sigmas):
            raise InvalidRequestError("pose oks_sigmas 必须全部大于 0")
        return sigmas
    if int(num_keypoints) < 1:
        raise InvalidRequestError("pose 评估数据不包含有效关键点")
    return resolve_keypoint_oks_sigmas(int(num_keypoints))
