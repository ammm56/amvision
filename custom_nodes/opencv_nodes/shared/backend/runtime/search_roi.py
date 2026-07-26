"""OpenCV 节点通用搜索 ROI 工具。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

from backend.nodes.core_nodes.support.roi import require_roi_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


@dataclass(frozen=True)
class ResolvedSearchRoi:
    """节点执行时解析后的搜索 ROI。

    说明：
    - image_matrix 是实际送入 OpenCV 算法的图像区域。
    - bbox_xyxy 是原图坐标系中的整数搜索框；为空表示整图。
    - offset_x / offset_y 用于把裁剪区域中的结果映射回原图坐标。
    """

    image_matrix: Any
    bbox_xyxy: list[int] | None
    offset_x: int
    offset_y: int
    source: str
    roi_id: str | None = None
    roi_kind: str | None = None
    polygon_bbox_only: bool = False


def read_optional_bbox_xyxy(raw_value: object, *, field_name: str = "search_bbox_xyxy") -> list[float] | None:
    """读取可选 bbox 参数，格式为 [x1, y1, x2, y2]。"""

    if raw_value is None or raw_value == "":
        return None
    parsed_value = raw_value
    if isinstance(raw_value, str):
        try:
            parsed_value = json.loads(raw_value)
        except json.JSONDecodeError as exc:
            raise InvalidRequestError(f"{field_name} 必须是 JSON 数组") from exc
    if not isinstance(parsed_value, list) or len(parsed_value) != 4:
        raise InvalidRequestError(f"{field_name} 必须是 [x1, y1, x2, y2]")

    bbox_values: list[float] = []
    for item in parsed_value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise InvalidRequestError(f"{field_name} 的坐标必须是数值")
        value = float(item)
        if not math.isfinite(value):
            raise InvalidRequestError(f"{field_name} 的坐标必须是有限数值")
        bbox_values.append(value)

    x1_value, y1_value, x2_value, y2_value = bbox_values
    if x2_value <= x1_value or y2_value <= y1_value:
        raise InvalidRequestError(f"{field_name} 必须满足 x2 > x1 且 y2 > y1")
    return bbox_values


def resolve_search_roi(
    request: WorkflowNodeExecutionRequest,
    *,
    image_matrix: Any,
    roi_input_name: str = "roi",
    bbox_parameter_name: str = "search_bbox_xyxy",
) -> ResolvedSearchRoi:
    """统一解析节点可选搜索区域。

    优先级：
    - 已连接 roi.v1 输入时，使用 ROI 的 bbox。
    - 否则使用图像面板写回的 search_bbox_xyxy 参数。
    - 两者都没有时使用整张图。
    """

    image_height, image_width = image_matrix.shape[:2]
    raw_roi_payload = request.input_values.get(roi_input_name)
    if raw_roi_payload is not None:
        roi_payload = require_roi_payload(raw_roi_payload, node_id=request.node_id)
        clipped_bbox = clip_bbox_xyxy(
            roi_payload["bbox_xyxy"],
            image_width=image_width,
            image_height=image_height,
            field_name=f"{roi_input_name}.bbox_xyxy",
        )
        return _build_resolved_search_roi(
            image_matrix=image_matrix,
            bbox_xyxy=clipped_bbox,
            source="roi-input",
            roi_id=str(roi_payload["roi_id"]),
            roi_kind=str(roi_payload["roi_kind"]),
            polygon_bbox_only=roi_payload["roi_kind"] == "polygon",
        )

    parameter_bbox = read_optional_bbox_xyxy(
        request.parameters.get(bbox_parameter_name),
        field_name=bbox_parameter_name,
    )
    if parameter_bbox is None:
        return ResolvedSearchRoi(
            image_matrix=image_matrix,
            bbox_xyxy=None,
            offset_x=0,
            offset_y=0,
            source="full-image",
        )
    clipped_bbox = clip_bbox_xyxy(
        parameter_bbox,
        image_width=image_width,
        image_height=image_height,
        field_name=bbox_parameter_name,
    )
    return _build_resolved_search_roi(
        image_matrix=image_matrix,
        bbox_xyxy=clipped_bbox,
        source="parameter",
    )


def clip_bbox_xyxy(
    raw_bbox_xyxy: object,
    *,
    image_width: int,
    image_height: int,
    field_name: str,
) -> list[int]:
    """把 bbox 裁剪到图片范围内，并返回整数 xyxy。"""

    bbox_values = read_optional_bbox_xyxy(raw_bbox_xyxy, field_name=field_name)
    if bbox_values is None:
        raise InvalidRequestError(f"{field_name} 不能为空")
    x1_value = max(0, min(int(math.floor(bbox_values[0])), image_width - 1))
    y1_value = max(0, min(int(math.floor(bbox_values[1])), image_height - 1))
    x2_value = max(x1_value + 1, min(int(math.ceil(bbox_values[2])), image_width))
    y2_value = max(y1_value + 1, min(int(math.ceil(bbox_values[3])), image_height))
    return [x1_value, y1_value, x2_value, y2_value]


def build_search_roi_overlay(search_roi: ResolvedSearchRoi) -> dict[str, object] | None:
    """把搜索 ROI 转为图片面板 bbox overlay。"""

    if search_roi.bbox_xyxy is None:
        return None
    return {
        "kind": "search-roi",
        "id": "search-roi",
        "label": "Search ROI",
        "bbox_xyxy": [float(value) for value in search_roi.bbox_xyxy],
        "target_parameters": ["search_bbox_xyxy"],
    }


def build_search_roi_summary(search_roi: ResolvedSearchRoi) -> dict[str, object]:
    """构造 summary 中使用的搜索 ROI 信息。"""

    summary: dict[str, object] = {
        "search_roi_source": search_roi.source,
    }
    if search_roi.bbox_xyxy is not None:
        summary["search_bbox_xyxy"] = search_roi.bbox_xyxy
    if search_roi.roi_id is not None:
        summary["roi_id"] = search_roi.roi_id
    if search_roi.roi_kind is not None:
        summary["roi_kind"] = search_roi.roi_kind
        summary["roi_polygon_bbox_only"] = search_roi.polygon_bbox_only
    return summary


def _build_resolved_search_roi(
    *,
    image_matrix: Any,
    bbox_xyxy: list[int],
    source: str,
    roi_id: str | None = None,
    roi_kind: str | None = None,
    polygon_bbox_only: bool = False,
) -> ResolvedSearchRoi:
    """按 bbox 裁剪图像并保留原图坐标偏移。"""

    x1_value, y1_value, x2_value, y2_value = bbox_xyxy
    return ResolvedSearchRoi(
        image_matrix=image_matrix[y1_value:y2_value, x1_value:x2_value],
        bbox_xyxy=bbox_xyxy,
        offset_x=x1_value,
        offset_y=y1_value,
        source=source,
        roi_id=roi_id,
        roi_kind=roi_kind,
        polygon_bbox_only=polygon_bbox_only,
    )
