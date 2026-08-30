"""通用图片质量指标节点。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_float,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import (
    require_opencv_imports,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.search_roi import (
    resolve_search_roi,
)

NODE_TYPE_ID = "custom.opencv.image-quality-metrics"


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """一次计算亮度、对比度、清晰度、曝光、饱和度和稳健噪声估计。"""

    cv2_module, np_module = require_opencv_imports()
    source_payload, _, source = load_image_matrix(
        request,
        imdecode_flags=cv2_module.IMREAD_UNCHANGED,
    )
    search_roi = resolve_search_roi(request, image_matrix=source)
    selected = search_roi.image_matrix
    gray = (
        selected
        if len(selected.shape) == 2
        else cv2_module.cvtColor(
            selected,
            cv2_module.COLOR_BGRA2GRAY
            if int(selected.shape[2]) == 4
            else cv2_module.COLOR_BGR2GRAY,
        )
    )
    gray_float = gray.astype(np_module.float64)
    low_threshold = read_float(
        request.parameters.get("low_clip_threshold"),
        field_name="low_clip_threshold",
        default=1.0,
        minimum=0.0,
        maximum=255.0,
    )
    high_threshold = read_float(
        request.parameters.get("high_clip_threshold"),
        field_name="high_clip_threshold",
        default=254.0,
        minimum=0.0,
        maximum=255.0,
    )
    if high_threshold <= low_threshold:
        from backend.service.application.errors import InvalidRequestError  # noqa: PLC0415

        raise InvalidRequestError(
            "high_clip_threshold 必须大于 low_clip_threshold"
        )
    laplacian = cv2_module.Laplacian(gray_float, cv2_module.CV_64F)
    gradient_x = cv2_module.Sobel(gray_float, cv2_module.CV_64F, 1, 0, ksize=3)
    gradient_y = cv2_module.Sobel(gray_float, cv2_module.CV_64F, 0, 1, ksize=3)
    tenengrad = float(np_module.mean(gradient_x * gradient_x + gradient_y * gradient_y))
    median = cv2_module.medianBlur(gray, 3).astype(np_module.float64)
    residual = gray_float - median
    residual_median = float(np_module.median(residual))
    noise_mad = float(np_module.median(np_module.abs(residual - residual_median)))
    noise_sigma = noise_mad / 0.6744897501960817
    if len(selected.shape) == 2:
        saturation = np_module.zeros_like(gray, dtype=np_module.uint8)
    else:
        bgr = (
            cv2_module.cvtColor(selected, cv2_module.COLOR_BGRA2BGR)
            if int(selected.shape[2]) == 4
            else selected
        )
        saturation = cv2_module.cvtColor(bgr, cv2_module.COLOR_BGR2HSV)[..., 1]
    percentiles = np_module.percentile(gray_float, [1, 5, 50, 95, 99])
    saturation_percentiles = np_module.percentile(saturation, [50, 95, 99])
    pixel_count = int(gray.size)
    metrics = {
        "format_id": "amvision.image-quality-metrics.v1",
        "source_image": source_payload,
        "roi_bbox_xyxy": search_roi.bbox_xyxy,
        "width": int(gray.shape[1]),
        "height": int(gray.shape[0]),
        "pixel_count": pixel_count,
        "mean": round(float(np_module.mean(gray_float)), 8),
        "standard_deviation": round(float(np_module.std(gray_float)), 8),
        "minimum": round(float(np_module.min(gray_float)), 8),
        "maximum": round(float(np_module.max(gray_float)), 8),
        "percentiles": {
            "p01": round(float(percentiles[0]), 8),
            "p05": round(float(percentiles[1]), 8),
            "p50": round(float(percentiles[2]), 8),
            "p95": round(float(percentiles[3]), 8),
            "p99": round(float(percentiles[4]), 8),
        },
        "laplacian_variance": round(float(np_module.var(laplacian)), 8),
        "tenengrad": round(tenengrad, 8),
        "low_clip_threshold": low_threshold,
        "high_clip_threshold": high_threshold,
        "low_clipping_ratio": round(
            float(np_module.count_nonzero(gray_float <= low_threshold) / pixel_count),
            10,
        ),
        "high_clipping_ratio": round(
            float(np_module.count_nonzero(gray_float >= high_threshold) / pixel_count),
            10,
        ),
        "saturation_mean": round(float(np_module.mean(saturation)), 8),
        "saturation_ratio": round(
            float(np_module.count_nonzero(saturation >= 250) / pixel_count),
            10,
        ),
        "saturation_percentiles": {
            "p50": round(float(saturation_percentiles[0]), 8),
            "p95": round(float(saturation_percentiles[1]), 8),
            "p99": round(float(saturation_percentiles[2]), 8),
        },
        "noise_sigma_robust": round(noise_sigma, 8),
        "noise_estimator": "median-residual-mad",
    }
    return {"metrics": build_value_payload(metrics)}


__all__ = ["NODE_TYPE_ID", "handle_node"]
