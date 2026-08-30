"""通用 Blob、路径宽度与轮廓偏差检查节点。"""

from __future__ import annotations

import math
from typing import Any

from backend.nodes.core_nodes.support.region import build_regions_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.opencv_nodes.shared.backend.runtime.atomic_ops import (
    read_choice,
    read_float,
    read_int,
)
from custom_nodes.opencv_nodes.shared.backend.runtime.images import load_image_matrix
from custom_nodes.opencv_nodes.shared.backend.runtime.imports import require_opencv_imports
from custom_nodes.opencv_nodes.shared.backend.runtime.payloads import (
    require_contours_payload,
    require_points_payload,
)

BLOB_ANALYSIS_NODE_TYPE_ID = "custom.opencv.blob-analysis"
BEAD_INSPECT_NODE_TYPE_ID = "custom.opencv.bead-inspect"
CONTOUR_DEVIATION_NODE_TYPE_ID = "custom.opencv.contour-deviation-inspect"


def handle_blob_analysis(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对二值前景执行连通分析、形状和可选灰度统计。"""

    cv2_module, np_module = require_opencv_imports()
    mask_payload, _, mask = load_image_matrix(
        request,
        input_name="mask",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    source = None
    if request.input_values.get("image") is not None:
        _, _, source = load_image_matrix(
            request,
            input_name="image",
            imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
        )
        if source.shape != mask.shape:
            raise InvalidRequestError("blob-analysis 的 image 与 mask 尺寸必须一致")
    binary = (
        mask
        > read_float(
            request.parameters.get("threshold"),
            field_name="threshold",
            default=0.0,
            minimum=0.0,
            maximum=255.0,
        )
    ).astype(np_module.uint8)
    connectivity = read_int(
        request.parameters.get("connectivity"),
        field_name="connectivity",
        default=8,
    )
    if connectivity not in {4, 8}:
        raise InvalidRequestError("connectivity 只支持 4 或 8")
    minimum_area = read_int(
        request.parameters.get("minimum_area"),
        field_name="minimum_area",
        default=1,
        minimum=1,
    )
    maximum_area = read_int(
        request.parameters.get("maximum_area"),
        field_name="maximum_area",
        default=int(binary.size),
        minimum=1,
    )
    if maximum_area < minimum_area:
        raise InvalidRequestError("maximum_area 必须大于等于 minimum_area")
    count, labels, stats, centroids = cv2_module.connectedComponentsWithStats(
        binary,
        connectivity=connectivity,
    )
    regions = []
    measurements = []
    for label in range(1, count):
        x, y, width, height, area = [int(item) for item in stats[label]]
        if not minimum_area <= area <= maximum_area:
            continue
        component_mask = (labels == label).astype(np_module.uint8)
        contours, _ = cv2_module.findContours(
            component_mask,
            cv2_module.RETR_EXTERNAL,
            cv2_module.CHAIN_APPROX_SIMPLE,
        )
        contour = max(contours, key=cv2_module.contourArea)
        perimeter = float(cv2_module.arcLength(contour, True))
        circularity = 4.0 * math.pi * area / (perimeter * perimeter) if perimeter > 0 else 0.0
        region_id = f"blob-{len(regions) + 1}"
        regions.append(
            {
                "region_id": region_id,
                "class_id": 0,
                "class_name": "blob",
                "score": 1.0,
                "bbox_xyxy": [float(x), float(y), float(x + width), float(y + height)],
                "polygon_xy": contour.reshape(-1, 2).astype(float).tolist(),
                "area": area,
                "center_xy": centroids[label].astype(float).tolist(),
            }
        )
        measurements.append(
            _measurement_item(
                measurement_id=region_id,
                measurement_kind="blob",
                values={
                    "area": area,
                    "perimeter": perimeter,
                    "circularity": circularity,
                    "width": width,
                    "height": height,
                    "centroid_xy": centroids[label].astype(float).tolist(),
                    "mean_gray": (
                        float(cv2_module.mean(source, mask=component_mask)[0])
                        if source is not None
                        else None
                    ),
                },
            )
        )
    return {
        "regions": build_regions_payload(
            source_image=mask_payload,
            selected_frame_index=None,
            items=regions,
        ),
        "measurements": _measurements_payload(
            measurements,
            source_image=mask_payload,
            measurement_kind="blob-analysis",
        ),
    }


def handle_bead_inspect(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """沿参考路径法向量测前景宽度、缺失、溢出和中心偏差。"""

    cv2_module, np_module = require_opencv_imports()
    image_payload, _, gray = load_image_matrix(
        request,
        input_name="image",
        imdecode_flags=cv2_module.IMREAD_GRAYSCALE,
    )
    path = require_points_payload(request.input_values.get("reference_path"))
    if path["coordinate_space"] != "source-image-pixels" or path["unit"] != "pixel":
        raise InvalidRequestError("bead-inspect 要求 source-image-pixels/pixel 路径")
    path_points = [item["xy"] for item in path["items"]]
    if len(path_points) < 2:
        raise InvalidRequestError("reference_path 至少包含两个点")
    threshold = read_float(
        request.parameters.get("threshold"),
        field_name="threshold",
        default=128.0,
        minimum=0.0,
        maximum=255.0,
    )
    polarity = read_choice(
        request.parameters.get("foreground_polarity"),
        field_name="foreground_polarity",
        choices={"bright", "dark"},
        default="bright",
    )
    binary = gray >= threshold if polarity == "bright" else gray <= threshold
    expected_width = read_float(
        request.parameters.get("expected_width"),
        field_name="expected_width",
        default=10.0,
        minimum=0.1,
    )
    width_tolerance = read_float(
        request.parameters.get("width_tolerance"),
        field_name="width_tolerance",
        default=3.0,
        minimum=0.0,
    )
    center_tolerance = read_float(
        request.parameters.get("center_tolerance"),
        field_name="center_tolerance",
        default=width_tolerance,
        minimum=0.0,
    )
    search_half_width = read_float(
        request.parameters.get("search_half_width"),
        field_name="search_half_width",
        default=expected_width + width_tolerance,
        minimum=1.0,
    )
    samples = _sample_path_widths(
        binary,
        path_points=path_points,
        search_half_width=search_half_width,
        sample_spacing=read_float(
            request.parameters.get("sample_spacing"),
            field_name="sample_spacing",
            default=2.0,
            minimum=0.1,
        ),
        cv2_module=cv2_module,
        np_module=np_module,
    )
    minimum_width = max(0.0, expected_width - width_tolerance)
    maximum_width = expected_width + width_tolerance
    error_regions = []
    error_counts = {"missing": 0, "narrow": 0, "overflow": 0, "offset": 0}
    for sample in samples:
        width = float(sample["width"])
        error_kind = (
            "missing"
            if width <= 0
            else "narrow"
            if width < minimum_width
            else "overflow"
            if width > maximum_width
            else "offset"
            if float(sample["center_deviation"]) > center_tolerance
            else None
        )
        if error_kind is None:
            continue
        error_counts[error_kind] += 1
        center_x, center_y = sample["center_xy"]
        radius = max(2.0, search_half_width)
        error_regions.append(
            _error_region(
                region_id=f"bead-error-{len(error_regions) + 1}",
                error_kind=error_kind,
                bbox=[center_x - radius, center_y - radius, center_x + radius, center_y + radius],
                score=min(1.0, abs(width - expected_width) / max(1.0, expected_width)),
            )
        )
    valid_widths = [float(item["width"]) for item in samples if float(item["width"]) > 0]
    values = {
        "sample_count": len(samples),
        "valid_sample_count": len(valid_widths),
        "coverage_ratio": len(valid_widths) / len(samples),
        "expected_width": expected_width,
        "minimum_width": minimum_width,
        "maximum_width": maximum_width,
        "center_tolerance": center_tolerance,
        "mean_width": float(np_module.mean(valid_widths)) if valid_widths else None,
        "minimum_measured_width": min(valid_widths) if valid_widths else None,
        "maximum_measured_width": max(valid_widths) if valid_widths else None,
        **{f"{name}_count": count for name, count in error_counts.items()},
        "samples": samples,
    }
    return {
        "error_regions": build_regions_payload(
            source_image=image_payload,
            selected_frame_index=None,
            items=error_regions,
        ),
        "measurements": _measurements_payload(
            [_measurement_item("bead-inspect-1", "bead-width", values)],
            source_image=image_payload,
            measurement_kind="bead-inspect",
        ),
    }


def handle_contour_deviation(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """计算实测轮廓点到参考轮廓的有符号距离和误差区域。"""

    cv2_module, np_module = require_opencv_imports()
    reference = require_contours_payload(request.input_values.get("reference_contours"))
    measured = require_contours_payload(request.input_values.get("measured_contours"))
    if len(reference["items"]) != 1 or len(measured["items"]) != 1:
        raise InvalidRequestError("contour-deviation-inspect 要求参考和实测各一个轮廓")
    reference_array = np_module.asarray(
        reference["items"][0]["points"],
        dtype=np_module.float32,
    ).reshape(-1, 1, 2)
    measured_points = measured["items"][0]["points"]
    positive_tolerance = read_float(
        request.parameters.get("positive_tolerance"),
        field_name="positive_tolerance",
        default=2.0,
        minimum=0.0,
    )
    negative_tolerance = read_float(
        request.parameters.get("negative_tolerance"),
        field_name="negative_tolerance",
        default=2.0,
        minimum=0.0,
    )
    signed_distances = [
        float(cv2_module.pointPolygonTest(reference_array, tuple(map(float, point)), True))
        for point in measured_points
    ]
    error_flags = [
        distance > positive_tolerance or distance < -negative_tolerance
        for distance in signed_distances
    ]
    error_regions = []
    for start, end in _contiguous_runs(error_flags):
        run_points = measured_points[start : end + 1]
        run_distances = signed_distances[start : end + 1]
        xs = [float(point[0]) for point in run_points]
        ys = [float(point[1]) for point in run_points]
        dominant = max(run_distances, key=abs)
        error_regions.append(
            _error_region(
                region_id=f"contour-error-{len(error_regions) + 1}",
                # pointPolygonTest 对参考轮廓内部返回正值；实测点落在参考外部
                # 表示材料外凸（burr），落在内部表示缺口（notch）。
                error_kind="burr" if dominant < 0 else "notch",
                bbox=[min(xs), min(ys), max(xs) + 1.0, max(ys) + 1.0],
                score=min(
                    1.0,
                    abs(dominant) / max(1.0, positive_tolerance, negative_tolerance),
                ),
                polygon=run_points if len(run_points) >= 3 else None,
            )
        )
    values = {
        "sample_count": len(signed_distances),
        "error_sample_count": sum(error_flags),
        "error_ratio": sum(error_flags) / len(error_flags),
        "positive_tolerance": positive_tolerance,
        "negative_tolerance": negative_tolerance,
        "maximum_positive_deviation": max(signed_distances),
        "maximum_negative_deviation": min(signed_distances),
        "mean_absolute_deviation": float(np_module.mean(np_module.abs(signed_distances))),
        "signed_distances": signed_distances,
    }
    source_image = measured.get("source_image") or reference.get("source_image")
    return {
        "error_regions": build_regions_payload(
            source_image=source_image,
            selected_frame_index=None,
            items=error_regions,
        ),
        "measurements": _measurements_payload(
            [_measurement_item("contour-deviation-1", "contour-deviation", values)],
            source_image=source_image,
            measurement_kind="contour-deviation",
        ),
    }


def _sample_path_widths(
    binary: Any,
    *,
    path_points: list[list[float]],
    search_half_width: float,
    sample_spacing: float,
    cv2_module: Any,
    np_module: Any,
) -> list[dict[str, object]]:
    """沿折线路径采样连续前景宽度。"""

    samples = []
    for segment_index in range(len(path_points) - 1):
        start = np_module.asarray(path_points[segment_index], dtype=np_module.float64)
        end = np_module.asarray(path_points[segment_index + 1], dtype=np_module.float64)
        length = float(np_module.linalg.norm(end - start))
        if length <= 1e-9:
            continue
        direction = (end - start) / length
        normal = np_module.asarray([-direction[1], direction[0]], dtype=np_module.float64)
        count = max(2, int(math.ceil(length / sample_spacing)) + 1)
        is_last = segment_index == len(path_points) - 2
        for offset in np_module.linspace(0.0, length, count, endpoint=is_last):
            center = start + direction * offset
            cross = np_module.linspace(
                -search_half_width,
                search_half_width,
                max(3, int(math.ceil(search_half_width * 2)) + 1),
            )
            coordinates = center[None, :] + cross[:, None] * normal[None, :]
            values = cv2_module.remap(
                binary.astype(np_module.uint8),
                coordinates[:, 0].astype(np_module.float32).reshape(1, -1),
                coordinates[:, 1].astype(np_module.float32).reshape(1, -1),
                interpolation=cv2_module.INTER_NEAREST,
                borderMode=cv2_module.BORDER_CONSTANT,
                borderValue=0,
            ).reshape(-1).astype(bool)
            center_index = len(values) // 2
            foreground_runs = _contiguous_runs(values.tolist())
            if foreground_runs:
                left, right = min(
                    foreground_runs,
                    key=lambda run: abs((run[0] + run[1]) / 2.0 - center_index),
                )
                width = float(cross[right] - cross[left] + (cross[1] - cross[0]))
                foreground_center = coordinates[int(round((left + right) / 2.0))]
                center_deviation = float(np_module.linalg.norm(foreground_center - center))
            else:
                width = 0.0
                center_deviation = 0.0
            samples.append(
                {
                    "sample_index": len(samples),
                    "segment_index": segment_index,
                    "center_xy": center.astype(float).tolist(),
                    "width": width,
                    "center_deviation": center_deviation,
                }
            )
    if not samples:
        raise InvalidRequestError("reference_path 没有可采样线段")
    return samples


def _error_region(
    *,
    region_id: str,
    error_kind: str,
    bbox: list[float],
    score: float,
    polygon: list[list[float]] | None = None,
) -> dict[str, object]:
    """构建通用检查误差 region。"""

    x1, y1, x2, y2 = bbox
    return {
        "region_id": region_id,
        "class_id": 0,
        "class_name": error_kind,
        "score": max(0.0, min(1.0, score)),
        "bbox_xyxy": bbox,
        "polygon_xy": polygon or [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        "area": max(1, int(round(max(0.0, x2 - x1) * max(0.0, y2 - y1)))),
        "error_kind": error_kind,
    }


def _contiguous_runs(flags: list[bool]) -> list[tuple[int, int]]:
    """把线性序列中的连续异常样本分组。"""

    runs = []
    start = None
    for index, flag in enumerate(flags):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(flags) - 1))
    return runs


def _measurement_item(
    measurement_id: str,
    measurement_kind: str,
    values: dict[str, object],
) -> dict[str, object]:
    """构建一个规范通用量测项。"""

    return {
        "measurement_id": measurement_id,
        "measurement_kind": measurement_kind,
        "coordinate_space": "source-image-pixels",
        "unit": "pixel",
        "values": values,
    }


def _measurements_payload(
    items: list[dict[str, object]],
    *,
    source_image: object,
    measurement_kind: str,
) -> dict[str, object]:
    """构建通用 measurements.v1。"""

    payload: dict[str, object] = {
        "coordinate_space": "source-image-pixels",
        "unit": "pixel",
        "items": items,
        "summary": {"measurement_kind": measurement_kind, "count": len(items)},
    }
    if isinstance(source_image, dict):
        payload["source_image"] = source_image
    return payload


INDUSTRIAL_INSPECTION_NODE_HANDLERS = (
    (BLOB_ANALYSIS_NODE_TYPE_ID, handle_blob_analysis),
    (BEAD_INSPECT_NODE_TYPE_ID, handle_bead_inspect),
    (CONTOUR_DEVIATION_NODE_TYPE_ID, handle_contour_deviation),
)


__all__ = ["INDUSTRIAL_INSPECTION_NODE_HANDLERS"]
