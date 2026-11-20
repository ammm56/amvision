"""读取分类、实例分割、姿态和旋转框评估的报告及样本。"""

from pathlib import PurePosixPath
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.api.deps.db import get_session_factory
from backend.service.api.deps.storage import get_dataset_storage
from backend.service.api.resource_file_response import ResourceFileResponse
from backend.service.api.rest.v1.routes.task_evaluation.services import get_evaluation_task_record
from backend.service.application.errors import ResourceNotFoundError
from backend.service.application.models.evaluation.sample_diagnostics import explain_geometry_errors
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


evaluation_reports_router = APIRouter(prefix="/models", tags=["models"])
EvaluationKind = Literal["classification", "segmentation", "pose", "obb", "semantic", "anomaly"]
Principal = Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read"))]
SamplePrincipal = Annotated[AuthenticatedPrincipal, Depends(require_scopes("tasks:read", "datasets:read"))]
Factory = Annotated[SessionFactory, Depends(get_session_factory)]
Storage = Annotated[LocalDatasetStorage, Depends(get_dataset_storage)]


def _read_snapshot(storage: LocalDatasetStorage, key: object):
    """读取任务对象存储中的 JSON 快照；历史文件可能不存在。"""
    if isinstance(key, str) and key and storage.resolve(key).is_file():
        return storage.read_json(key)
    return None


def _sample_rows(task, kind: EvaluationKind, storage: LocalDatasetStorage) -> list:
    """返回按原报告顺序保存的样本。Pose 与 OBB 的旧预测文件只保存几何。"""
    key = task.result.get("predictions_object_key")
    if kind in {"pose", "obb"} and isinstance(key, str) and key:
        key = str(PurePosixPath(key).with_name("samples.json"))
    rows = _read_snapshot(storage, key)
    return rows if isinstance(rows, list) else []


def _classification_confusion(rows: list, report: dict) -> dict:
    """从真实分类快照恢复矩阵，空预测单独记为未识别。"""
    names = {row["class_id"]: row["class_name"] for row in report.get("per_class_metrics", [])}
    unknown = False
    counts: dict[tuple[int, int | None], int] = {}
    for sample in rows:
        actual = sample["ground_truth_class_id"]
        candidates = sample.get("predicted_top_k", [])
        predicted = candidates[0]["class_id"] if candidates else None
        names.setdefault(actual, sample.get("ground_truth_class_name") or str(actual))
        if predicted is None:
            unknown = True
        else:
            names.setdefault(predicted, candidates[0].get("class_name") or str(predicted))
        pair = actual, predicted
        counts[pair] = counts.get(pair, 0) + 1
    ids = sorted(names)
    axes = [*ids, None] if unknown else ids
    return {
        "labels": [names.get(key) for key in axes],
        "rows": [[counts.get((actual, predicted), 0) for predicted in axes] for actual in axes],
    }


@evaluation_reports_router.get("/{kind}/evaluation-tasks/{task_id}/report")
def evaluation_report(kind: EvaluationKind, task_id: str, principal: Principal, factory: Factory, storage: Storage) -> dict:
    """读取非检测任务保存的原始评估报告。"""
    task = get_evaluation_task_record(
        principal=principal, session_factory=factory, task_id=task_id, expected_task_kind=f"{kind}-evaluation",
    )
    report = _read_snapshot(storage, task.result.get("report_object_key"))
    if not isinstance(report, dict):
        if task.state in {"queued", "running", "cancelling"}:
            return {"file_status": "pending", "payload": {}}
        raise ResourceNotFoundError("找不到评估报告")
    if kind == "classification":
        rows = _sample_rows(task, kind, storage)
        if rows:
            report["confusion_matrix"] = _classification_confusion(rows, report)
    return {"file_status": "ready", "payload": report}


@evaluation_reports_router.get("/{kind}/evaluation-tasks/{task_id}/samples")
def evaluation_samples(
    kind: EvaluationKind, task_id: str, principal: SamplePrincipal, factory: Factory, storage: Storage,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=12)] = 1,
    errors_only: bool = False,
    issue: Literal["all", "errors", "keypoints", "angle", "localization", "missed", "extra"] = "all",
    sample_filter: Literal["all", "normal", "anomaly", "errors"] = "all",
) -> dict:
    """分页返回评估快照中的样本与叠加数据。"""
    task = get_evaluation_task_record(
        principal=principal, session_factory=factory, task_id=task_id, expected_task_kind=f"{kind}-evaluation",
    )
    rows = _sample_rows(task, kind, storage)
    if kind in {"pose", "obb"}:
        report = _read_snapshot(storage, task.result.get("report_object_key")) or {}
        sigmas = tuple(report.get("evaluation_policy", {}).get("oks_sigmas", []))
        for row in rows:
            if "errors" not in row:
                row["errors"] = explain_geometry_errors(row, kind, sigmas=sigmas)
    indices = []
    issue_counts: dict[str, int] = {}
    label_indices: dict[int, int] = {}
    label_counts: dict[str, int] = {}
    for index, row in enumerate(rows):
        if kind == "anomaly" and (label := row.get("label")) in {"normal", "anomaly"}:
            label_indices[index] = label_counts.get(label, 0)
            label_counts[label] = label_indices[index] + 1
        errors = row.get("errors", {})
        has_errors = any(errors.values())
        for name, count in errors.items():
            if count:
                issue_counts[name] = issue_counts.get(name, 0) + 1
        if has_errors:
            issue_counts["errors"] = issue_counts.get("errors", 0) + 1
        if errors_only and (kind != "classification" or row.get("top1_correct") is not False):
            continue
        if kind in {"semantic", "anomaly"} and sample_filter != "all":
            if sample_filter == "errors":
                failed = row.get("different_pixels", 0) > 0 if kind == "semantic" else row["label"] != row["predicted_label"]
                if not failed:
                    continue
            elif row.get("label") != sample_filter:
                continue
        if issue == "all" or (has_errors if issue == "errors" else errors.get(issue, 0)):
            indices.append(index)
    items = []
    for index in indices[offset:offset + limit]:
        sample = rows[index]
        path = str(sample.get("image_path", "")).replace("\\", "/")
        public_row = {key: value for key, value in sample.items() if key not in {"image_path", "truth_key", "prediction_key"}}
        if kind in {"semantic", "anomaly"}:
            public_row["has_truth"] = "truth_key" in sample
            public_row["has_prediction"] = "prediction_key" in sample
        if index in label_indices:
            public_row["label_index"] = label_indices[index]
        if kind == "segmentation":
            public_row["mask_available"] = "ground_truth" in public_row and "predictions" in public_row
            public_row.pop("ground_truth", None)
            public_row.pop("predictions", None)
        items.append({**public_row, "name": public_row.pop("sample_name", PurePosixPath(path).name), "index": index})
    return {"items": items, "total": len(indices), "available": bool(rows), "issue_counts": issue_counts}


@evaluation_reports_router.get("/{kind}/evaluation-tasks/{task_id}/samples/{index}/image")
def evaluation_image(
    kind: EvaluationKind, task_id: str, index: int, principal: SamplePrincipal, factory: Factory, storage: Storage,
    layer: Literal["original", "truth", "prediction"] = "original",
) -> ResourceFileResponse:
    """仅返回任务所用导出目录中有快照记录的图片。"""
    task = get_evaluation_task_record(
        principal=principal, session_factory=factory, task_id=task_id, expected_task_kind=f"{kind}-evaluation",
    )
    rows = _sample_rows(task, kind, storage)
    if kind in {"semantic", "anomaly"}:
        if index < 0 or index >= len(rows):
            raise ResourceNotFoundError("找不到评估图片")
        key = rows[index].get({"original": "image_path", "truth": "truth_key", "prediction": "prediction_key"}[layer])
        output = task.result.get("output_object_prefix")
        if not isinstance(output, str) or not isinstance(key, str):
            raise ResourceNotFoundError("找不到评估图片")
        image = storage.resolve(key)
        if not image.is_relative_to(storage.resolve(output)) or not image.is_file():
            raise ResourceNotFoundError("找不到评估图片")
        return ResourceFileResponse(
            session_factory=factory, project_id=task.project_id, resource_id=task_id,
            path=image, media_type="image/png", headers={"X-Content-Type-Options": "nosniff"},
        )
    with factory.create_session() as session:
        export_id = task.task_spec.get("dataset_export_id")
        export = SqlAlchemyUnitOfWork(session).dataset_exports.get_dataset_export(export_id) if isinstance(export_id, str) else None
    if index < 0 or index >= len(rows) or not export or export.project_id != task.project_id or not export.export_path:
        raise ResourceNotFoundError("找不到评估图片")
    image_key = rows[index].get("image_path")
    if not isinstance(image_key, str) or not image_key:
        raise ResourceNotFoundError("找不到评估图片")
    candidate = storage.resolve_deletion_path(image_key)
    root = storage.resolve_deletion_path(export.export_path)
    mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".bmp": "image/bmp", ".webp": "image/webp"}
    media_type = mime.get(candidate.suffix.lower())
    if not candidate.is_relative_to(root) or not candidate.is_file() or not media_type:
        raise ResourceNotFoundError("找不到评估图片")
    return ResourceFileResponse(
        session_factory=factory, project_id=task.project_id, resource_id=task_id,
        path=candidate, media_type=media_type, headers={"X-Content-Type-Options": "nosniff"},
    )


@evaluation_reports_router.get("/segmentation/evaluation-tasks/{task_id}/samples/{index}/mask-overlay")
def evaluation_mask_overlay(
    task_id: str, index: int, principal: SamplePrincipal, factory: Factory, storage: Storage,
    layer: Literal["combined", "difference"],
) -> Response:
    """从原始 mask RLE 生成可叠加的前景轮廓及差异图层。"""
    task = get_evaluation_task_record(
        principal=principal, session_factory=factory, task_id=task_id, expected_task_kind="segmentation-evaluation",
    )
    rows = _sample_rows(task, "segmentation", storage)
    if index < 0 or index >= len(rows):
        raise ResourceNotFoundError("找不到该样本的 mask")
    sample = rows[index]
    actual = sample.get("ground_truth", [])
    predicted = sample.get("predictions", [])
    first = next((item["mask"] for item in [*actual, *predicted] if "mask" in item), None)
    if first is None:
        return Response(status_code=204)

    import cv2
    import numpy as np
    from backend.service.application.models.yolo_core_common.targets.segmentation import decode_coco_rle_mask

    size = tuple(first["size"])

    def foreground(rows: list) -> np.ndarray:
        """合并各实例前景，保持原图的像素坐标。"""
        merged = np.zeros(size, dtype=np.uint8)
        for row in rows:
            if (mask := row.get("mask")) and tuple(mask["size"]) == size:
                decoded = decode_coco_rle_mask(segmentation=mask, np_module=np)
                if decoded is not None:
                    merged |= decoded.astype(np.uint8)
        return merged

    truth = foreground(actual)
    pred = foreground(predicted)
    rgba = np.zeros((*size, 4), dtype=np.uint8)
    if layer == "combined":
        rgba[pred != 0] = (36, 152, 255, 120)
        edge = truth != cv2.erode(truth, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
        rgba[edge] = (125, 220, 0, 255)
    else:
        rgba[(pred != 0) & (truth == 0)] = (80, 80, 255, 170)
        rgba[(truth != 0) & (pred == 0)] = (255, 122, 46, 170)
    ready, png = cv2.imencode(".png", rgba)
    if not ready:
        raise ResourceNotFoundError("无法显示该样本的 mask")
    return Response(png.tobytes(), media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})
