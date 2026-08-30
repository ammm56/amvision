"""正常样本变化模型构建与异常检查节点。"""

from __future__ import annotations

import hashlib
from io import BytesIO
from typing import Any

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload, require_dataset_storage
from backend.nodes.save_locations import (
    SAVE_LOCATION_OBJECT_STORE,
    resolve_required_save_location_from_request,
    save_bytes,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import read_float, read_int
from custom_nodes.opencv_nodes.shared.backend.runtime.images import (
    build_output_image_matrix_payload,
    load_image_matrix,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import require_image_refs_payload

VARIATION_MODEL_BUILD_NODE_TYPE_ID = "custom.opencv.variation-model-build"
VARIATION_INSPECT_NODE_TYPE_ID = "custom.opencv.variation-inspect"
_MODEL_FORMAT_ID = "amvision.variation-model.v1"


def handle_variation_model_build(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """从同尺寸正常样本建立逐像素均值和标准差模型。"""

    cv2_module, np_module = require_opencv_imports()
    image_refs = require_image_refs_payload(request.input_values.get("images"))
    minimum_samples = read_int(
        request.parameters.get("minimum_samples"),
        field_name="minimum_samples",
        default=3,
        minimum=2,
    )
    items = list(image_refs["items"])
    if len(items) < minimum_samples:
        raise InvalidRequestError(
            "variation-model-build 的正常样本数量不足",
            details={"sample_count": len(items), "minimum_samples": minimum_samples},
        )
    standard_deviation_floor = read_float(
        request.parameters.get("standard_deviation_floor"),
        field_name="standard_deviation_floor",
        default=2.0,
        minimum=0.001,
    )
    execution_control = build_node_execution_control(request)
    sample_count = 0
    running_mean = None
    running_m2 = None
    expected_shape: tuple[int, int] | None = None
    for item_index, item in enumerate(items, start=1):
        execution_control.raise_if_cancelled_or_expired()
        _, matrix = load_image_matrix_from_payload(
            request,
            image_payload=item,
            cv2_module=cv2_module,
            np_module=np_module,
            imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
            copy_raw=False,
        )
        shape = (int(matrix.shape[0]), int(matrix.shape[1]))
        if expected_shape is None:
            expected_shape = shape
        elif shape != expected_shape:
            raise InvalidRequestError(
                "variation-model-build 的全部样本尺寸必须一致",
                details={
                    "item_index": item_index,
                    "expected_shape": list(expected_shape),
                    "actual_shape": list(shape),
                },
            )
        sample = matrix.astype(np_module.float64)
        sample_count += 1
        if running_mean is None:
            running_mean = sample
            running_m2 = np_module.zeros_like(sample, dtype=np_module.float64)
            continue
        delta = sample - running_mean
        running_mean += delta / float(sample_count)
        running_m2 += delta * (sample - running_mean)
    if running_mean is None or running_m2 is None:
        raise InvalidRequestError("variation-model-build 没有可用的正常样本")
    mean = running_mean.astype(np_module.float32)
    standard_deviation = np_module.sqrt(running_m2 / float(sample_count)).astype(
        np_module.float32
    )
    standard_deviation = np_module.maximum(
        standard_deviation,
        np_module.float32(standard_deviation_floor),
    )
    execution_control.raise_if_cancelled_or_expired()
    buffer = BytesIO()
    np_module.savez_compressed(
        buffer,
        mean=mean,
        standard_deviation=standard_deviation,
    )
    content = buffer.getvalue()
    digest = hashlib.sha256(content).hexdigest()
    save_location = resolve_required_save_location_from_request(
        request,
        scope="directory",
    )
    if save_location.kind != SAVE_LOCATION_OBJECT_STORE:
        raise InvalidRequestError(
            "variation-model-build 的模型必须保存到 ObjectStore 相对位置"
        )
    saved = save_bytes(
        request,
        save_location=save_location,
        file_name=f"variation-model-{digest[:16]}.npz",
        content=content,
    )
    width = int(expected_shape[1]) if expected_shape is not None else 0
    height = int(expected_shape[0]) if expected_shape is not None else 0
    model = {
        "format_id": _MODEL_FORMAT_ID,
        "model_id": f"variation-{digest[:16]}",
        "object_key": str(saved.object_key or ""),
        "sha256": digest,
        "image_size": [width, height],
        "sample_count": sample_count,
        "standard_deviation_floor": standard_deviation_floor,
        "color_space": "GRAY",
        "dtype": "float32",
    }
    return {
        "model": build_value_payload(model),
        "statistics": build_value_payload(
            {
                "sample_count": sample_count,
                "mean_intensity": float(np_module.mean(mean)),
                "mean_standard_deviation": float(np_module.mean(standard_deviation)),
                "maximum_standard_deviation": float(np_module.max(standard_deviation)),
            }
        ),
    }


def handle_variation_inspect(
    request: WorkflowNodeExecutionRequest,
) -> dict[str, object]:
    """使用正常样本模型计算 z-score 热图与异常区域。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, image = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    model = _require_model(request.input_values.get("model"))
    expected_width, expected_height = [int(item) for item in model["image_size"]]
    if (int(image.shape[1]), int(image.shape[0])) != (expected_width, expected_height):
        raise InvalidRequestError(
            "variation-inspect 的图片尺寸与模型不一致",
            details={
                "expected_size": [expected_width, expected_height],
                "actual_size": [int(image.shape[1]), int(image.shape[0])],
            },
        )
    execution_control = build_node_execution_control(request)
    execution_control.raise_if_cancelled_or_expired()
    storage = require_dataset_storage(request)
    model_path = storage.resolve(str(model["object_key"]))
    if not model_path.is_file():
        raise InvalidRequestError(
            "variation-inspect 引用的模型文件不存在",
            details={"object_key": model["object_key"]},
        )
    with model_path.open("rb") as model_file:
        actual_digest = hashlib.file_digest(model_file, "sha256").hexdigest()
    if actual_digest != model["sha256"]:
        raise InvalidRequestError("variation-inspect 模型文件完整性校验失败")
    with np_module.load(model_path, allow_pickle=False) as archive:
        mean = np_module.asarray(archive["mean"], dtype=np_module.float32)
        standard_deviation = np_module.asarray(
            archive["standard_deviation"],
            dtype=np_module.float32,
        )
    if mean.shape != image.shape or standard_deviation.shape != image.shape:
        raise InvalidRequestError("variation-inspect 模型矩阵尺寸与模型元数据不一致")
    execution_control.raise_if_cancelled_or_expired()
    z_score = np_module.abs(image.astype(np_module.float32) - mean) / standard_deviation
    threshold = read_float(
        request.parameters.get("z_score_threshold"),
        field_name="z_score_threshold",
        default=4.0,
        minimum=0.01,
    )
    minimum_area = read_int(
        request.parameters.get("minimum_area"),
        field_name="minimum_area",
        default=4,
        minimum=1,
    )
    binary = (z_score >= threshold).astype(np_module.uint8)
    morphology_size = read_int(
        request.parameters.get("morphology_size"),
        field_name="morphology_size",
        default=3,
        minimum=0,
        maximum=31,
    )
    if morphology_size > 0:
        kernel_size = morphology_size if morphology_size % 2 == 1 else morphology_size + 1
        kernel = np_module.ones((kernel_size, kernel_size), dtype=np_module.uint8)
        binary = cv2_module.morphologyEx(binary, cv2_module.MORPH_OPEN, kernel)
        binary = cv2_module.morphologyEx(binary, cv2_module.MORPH_CLOSE, kernel)
    regions = _build_anomaly_regions(
        binary,
        z_score=z_score,
        minimum_area=minimum_area,
        cv2_module=cv2_module,
        np_module=np_module,
    )
    heatmap_scale = read_float(
        request.parameters.get("heatmap_max_z_score"),
        field_name="heatmap_max_z_score",
        default=max(8.0, threshold),
        minimum=threshold,
    )
    heatmap = np_module.clip(z_score / heatmap_scale * 255.0, 0.0, 255.0).astype(
        np_module.uint8
    )
    return {
        "heatmap": build_output_image_matrix_payload(
            request,
            source_payload=image_payload,
            image_matrix=heatmap,
            save_location=_optional_text(request.parameters.get("save_location")),
            variant_name="variation-heatmap",
        ),
        "error_regions": _regions_payload(image_payload, regions),
        "statistics": build_value_payload(
            {
                "model_id": model["model_id"],
                "anomaly_region_count": len(regions),
                "anomaly_pixel_count": int(np_module.count_nonzero(binary)),
                "anomaly_ratio": float(np_module.count_nonzero(binary) / binary.size),
                "maximum_z_score": float(np_module.max(z_score)),
                "mean_z_score": float(np_module.mean(z_score)),
                "z_score_threshold": threshold,
            }
        ),
    }


def _require_model(payload: object) -> dict[str, object]:
    """校验 variation model value payload。"""

    value = require_value_payload(payload, field_name="model")["value"]
    if not isinstance(value, dict) or value.get("format_id") != _MODEL_FORMAT_ID:
        raise InvalidRequestError("model 必须是 amvision.variation-model.v1")
    object_key = value.get("object_key")
    digest = value.get("sha256")
    image_size = value.get("image_size")
    if not isinstance(object_key, str) or not object_key.strip():
        raise InvalidRequestError("variation model 缺少 object_key")
    if not isinstance(digest, str) or len(digest) != 64:
        raise InvalidRequestError("variation model 缺少有效 sha256")
    if (
        not isinstance(image_size, list)
        or len(image_size) != 2
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0 for item in image_size)
    ):
        raise InvalidRequestError("variation model 缺少有效 image_size")
    return dict(value)


def _build_anomaly_regions(
    binary: Any,
    *,
    z_score: Any,
    minimum_area: int,
    cv2_module: Any,
    np_module: Any,
) -> list[dict[str, object]]:
    """把异常 mask 转换成通用 regions.v1 items。"""

    contours, _ = cv2_module.findContours(
        binary,
        cv2_module.RETR_EXTERNAL,
        cv2_module.CHAIN_APPROX_SIMPLE,
    )
    regions = []
    for contour in contours:
        area = float(cv2_module.contourArea(contour))
        if area < minimum_area:
            continue
        x, y, width, height = cv2_module.boundingRect(contour)
        component_mask = np_module.zeros(binary.shape, dtype=np_module.uint8)
        cv2_module.drawContours(component_mask, [contour], -1, 1, thickness=-1)
        values = z_score[component_mask.astype(bool)]
        regions.append(
            {
                "region_id": f"variation-error-{len(regions) + 1}",
                "class_id": 0,
                "class_name": "variation",
                "score": min(1.0, float(np_module.max(values)) / 10.0),
                "bbox_xyxy": [float(x), float(y), float(x + width), float(y + height)],
                "polygon_xy": contour.reshape(-1, 2).astype(float).tolist(),
                "area": max(1, int(round(area))),
                "error_kind": "variation",
                "maximum_z_score": float(np_module.max(values)),
                "mean_z_score": float(np_module.mean(values)),
            }
        )
    return regions


def _regions_payload(source_image: dict[str, object], items: list[dict[str, object]]) -> dict[str, object]:
    """构建通用 regions.v1，避免检查模块依赖渲染实现。"""

    return {
        "count": len(items),
        "items": items,
        "source_image": source_image,
    }


def _optional_text(value: object) -> str | None:
    """读取可选非空字符串。"""

    return value.strip() if isinstance(value, str) and value.strip() else None


VARIATION_MODEL_NODE_HANDLERS = (
    (VARIATION_MODEL_BUILD_NODE_TYPE_ID, handle_variation_model_build),
    (VARIATION_INSPECT_NODE_TYPE_ID, handle_variation_inspect),
)


__all__ = ["VARIATION_MODEL_NODE_HANDLERS"]
