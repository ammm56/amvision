"""孔位模式检查节点。"""

from __future__ import annotations

from statistics import mean

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.nodes.core_nodes.support.logic import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes.support.region import (
    compute_region_bbox_metrics,
    filter_region_items,
    require_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "hole-pattern-check"


def _hole_pattern_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """检查孔位数量、节距和轴向排列是否符合预期。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    hole_filter = _read_hole_filter(request.parameters.get("hole_filter"))
    axis_mode = _read_axis_mode(request.parameters.get("axis"))
    expected_count = _read_expected_count(request.parameters.get("expected_count"))
    expected_pitch = _read_optional_number(request.parameters.get("expected_pitch"), field_name="expected_pitch")
    max_abs_pitch_error = _read_optional_non_negative_number(
        request.parameters.get("max_abs_pitch_error"),
        field_name="max_abs_pitch_error",
    )
    max_pitch_cv = _read_optional_non_negative_number(
        request.parameters.get("max_pitch_cv"),
        field_name="max_pitch_cv",
    )
    max_orthogonal_deviation = _read_optional_non_negative_number(
        request.parameters.get("max_orthogonal_deviation"),
        field_name="max_orthogonal_deviation",
    )
    if expected_pitch is not None and max_abs_pitch_error is None:
        raise InvalidRequestError(f"{NODE_NAME} 节点提供 expected_pitch 时必须同时提供 max_abs_pitch_error")

    matched_items = filter_region_items(
        regions_payload["items"],
        min_score=hole_filter["min_score"],
        max_score=hole_filter["max_score"],
        min_area=hole_filter["min_area"],
        max_area=hole_filter["max_area"],
        class_ids={hole_filter["class_id"]} if hole_filter["class_id"] is not None else None,
        class_names={hole_filter["class_name"]} if hole_filter["class_name"] is not None else None,
        prompt_ids={hole_filter["prompt_id"]} if hole_filter["prompt_id"] is not None else None,
        track_ids={hole_filter["track_id"]} if hole_filter["track_id"] is not None else None,
        states={hole_filter["state"]} if hole_filter["state"] is not None else None,
    )

    ordered_items, resolved_axis = _order_hole_items(matched_items, axis_mode=axis_mode)
    ordered_metrics = [compute_region_bbox_metrics(item) for item in ordered_items]
    center_positions = [
        float(metric_item["center_x"] if resolved_axis == "x" else metric_item["center_y"])
        for metric_item in ordered_metrics
    ]
    orthogonal_positions = [
        float(metric_item["center_y"] if resolved_axis == "x" else metric_item["center_x"])
        for metric_item in ordered_metrics
    ]
    pitches = [
        round(float(center_positions[index + 1] - center_positions[index]), 4)
        for index in range(max(0, len(center_positions) - 1))
    ]
    mean_pitch = round(float(mean(pitches)), 4) if pitches else None
    pitch_errors = (
        [round(float(pitch_value - expected_pitch), 4) for pitch_value in pitches]
        if expected_pitch is not None
        else []
    )
    pitch_cv = _compute_pitch_cv(pitches)
    orthogonal_baseline = float(mean(orthogonal_positions)) if orthogonal_positions else 0.0
    orthogonal_deviations = [
        round(float(abs(position_value - orthogonal_baseline)), 4)
        for position_value in orthogonal_positions
    ]
    max_actual_orthogonal_deviation = round(max(orthogonal_deviations, default=0.0), 4)

    failure_reasons: list[str] = []
    if len(ordered_items) != expected_count:
        failure_reasons.append("hole-count-mismatch")
    if expected_pitch is not None and max_abs_pitch_error is not None:
        if any(abs(float(error_value)) > max_abs_pitch_error for error_value in pitch_errors):
            failure_reasons.append("pitch-error-too-large")
    if max_pitch_cv is not None and pitch_cv is not None and pitch_cv > max_pitch_cv:
        failure_reasons.append("pitch-variation-too-large")
    if (
        max_orthogonal_deviation is not None
        and max_actual_orthogonal_deviation > max_orthogonal_deviation
    ):
        failure_reasons.append("holes-off-axis")
    result_value = len(failure_reasons) == 0
    return {
        "result": build_boolean_payload(result_value),
        "metrics": build_value_payload(
            {
                "result": result_value,
                "failure_reasons": failure_reasons,
                "hole_filter": hole_filter,
                "requested_axis": axis_mode,
                "resolved_axis": resolved_axis,
                "expected_count": expected_count,
                "matched_count": len(ordered_items),
                "matched_region_ids": [metric_item["region_id"] for metric_item in ordered_metrics],
                "expected_pitch": expected_pitch,
                "pitches": pitches,
                "mean_pitch": mean_pitch,
                "pitch_errors": pitch_errors,
                "pitch_cv": pitch_cv,
                "max_pitch_cv": max_pitch_cv,
                "orthogonal_baseline": round(orthogonal_baseline, 4) if orthogonal_positions else None,
                "orthogonal_deviations": orthogonal_deviations,
                "max_actual_orthogonal_deviation": max_actual_orthogonal_deviation,
                "max_orthogonal_deviation": max_orthogonal_deviation,
                "items": ordered_metrics,
            }
        ),
    }


def _read_hole_filter(raw_value: object) -> dict[str, object]:
    """读取孔位过滤条件。"""

    if not isinstance(raw_value, dict):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 hole_filter 必须是对象")
    class_name = _read_optional_text(raw_value.get("class_name"), field_name="hole_filter.class_name")
    class_id = _read_optional_non_negative_int(raw_value.get("class_id"), field_name="hole_filter.class_id")
    prompt_id = _read_optional_text(raw_value.get("prompt_id"), field_name="hole_filter.prompt_id")
    track_id = _read_optional_text(raw_value.get("track_id"), field_name="hole_filter.track_id")
    state = _read_optional_text(raw_value.get("state"), field_name="hole_filter.state")
    if class_name is None and class_id is None and prompt_id is None and track_id is None and state is None:
        raise InvalidRequestError(
            f"{NODE_NAME} 节点的 hole_filter 至少需要提供 class_name、class_id、prompt_id、track_id 或 state 之一"
        )
    min_score = _read_optional_non_negative_number(raw_value.get("min_score"), field_name="hole_filter.min_score")
    max_score = _read_optional_non_negative_number(raw_value.get("max_score"), field_name="hole_filter.max_score")
    min_area = _read_optional_non_negative_int(raw_value.get("min_area"), field_name="hole_filter.min_area")
    max_area = _read_optional_non_negative_int(raw_value.get("max_area"), field_name="hole_filter.max_area")
    if min_score is not None and max_score is not None and max_score < min_score:
        raise InvalidRequestError("hole_filter.max_score 不能小于 min_score")
    if min_area is not None and max_area is not None and max_area < min_area:
        raise InvalidRequestError("hole_filter.max_area 不能小于 min_area")
    return {
        "class_name": class_name,
        "class_id": class_id,
        "prompt_id": prompt_id,
        "track_id": track_id,
        "state": state,
        "min_score": min_score,
        "max_score": max_score,
        "min_area": min_area,
        "max_area": max_area,
    }


def _read_axis_mode(raw_value: object) -> str:
    """读取孔位排序轴。"""

    if raw_value is None:
        return "auto"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 axis 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"x", "y", "auto"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 axis 仅支持 x、y 或 auto")
    return normalized_value


def _read_expected_count(raw_value: object) -> int:
    """读取期望孔位数量。"""

    if isinstance(raw_value, bool) or not isinstance(raw_value, int):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 expected_count 必须是整数")
    if raw_value < 1:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 expected_count 必须大于等于 1")
    return int(raw_value)


def _read_optional_text(raw_value: object, *, field_name: str) -> str | None:
    """读取可选文本。"""

    if raw_value is None:
        return None
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{field_name} 必须是字符串")
    normalized_value = raw_value.strip()
    return normalized_value or None


def _read_optional_non_negative_int(raw_value: object, *, field_name: str) -> int | None:
    """读取可选非负整数。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value < 0:
        raise InvalidRequestError(f"{field_name} 必须是非负整数")
    return int(raw_value)


def _read_optional_number(raw_value: object, *, field_name: str) -> float | None:
    """读取可选数值。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    return float(raw_value)


def _read_optional_non_negative_number(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负数值。"""

    normalized_value = _read_optional_number(raw_value, field_name=field_name)
    if normalized_value is None:
        return None
    if normalized_value < 0:
        raise InvalidRequestError(f"{field_name} 不能小于 0")
    return normalized_value


def _order_hole_items(
    items: list[dict[str, object]],
    *,
    axis_mode: str,
) -> tuple[list[dict[str, object]], str]:
    """按指定或自动轴对孔位排序。"""

    if not items:
        return [], "x" if axis_mode == "auto" else axis_mode
    metric_items = [compute_region_bbox_metrics(item) for item in items]
    if axis_mode == "auto":
        span_x = max(float(item["center_x"]) for item in metric_items) - min(float(item["center_x"]) for item in metric_items)
        span_y = max(float(item["center_y"]) for item in metric_items) - min(float(item["center_y"]) for item in metric_items)
        resolved_axis = "x" if span_x >= span_y else "y"
    else:
        resolved_axis = axis_mode
    sort_key = "center_x" if resolved_axis == "x" else "center_y"
    ordered_metric_items = sorted(metric_items, key=lambda item: float(item[sort_key]))
    metrics_by_region_id = {str(item["region_id"]): item for item in items}
    return [metrics_by_region_id[str(item["region_id"])] for item in ordered_metric_items], resolved_axis


def _compute_pitch_cv(pitches: list[float]) -> float | None:
    """计算节距变异系数。"""

    if not pitches:
        return None
    mean_pitch_value = float(mean(pitches))
    if mean_pitch_value <= 0:
        return 0.0
    if len(pitches) == 1:
        return 0.0
    variance = sum((float(pitch_value) - mean_pitch_value) ** 2 for pitch_value in pitches) / len(pitches)
    standard_deviation = variance ** 0.5
    return round(float(standard_deviation / mean_pitch_value), 6)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.hole-pattern-check",
        display_name="Hole Pattern Check",
        category="vision.assembly",
        description="检查孔位数量、节距和轴向排列是否符合预期，适合安装孔、定位孔、针脚孔列和孔位换型检查。",
        implementation_kind=NODE_IMPLEMENTATION_CORE,
        runtime_kind=NODE_RUNTIME_PYTHON_CALLABLE,
        input_ports=(
            NodePortDefinition(
                name="regions",
                display_name="Regions",
                payload_type_id="regions.v1",
            ),
        ),
        output_ports=(
            NodePortDefinition(
                name="result",
                display_name="Result",
                payload_type_id="boolean.v1",
            ),
            NodePortDefinition(
                name="metrics",
                display_name="Metrics",
                payload_type_id="value.v1",
            ),
        ),
        parameter_schema={
            "type": "object",
            "properties": {
                "hole_filter": {
                    "type": "object",
                    "properties": {
                        "class_name": {"type": "string"},
                        "class_id": {"type": "integer", "minimum": 0},
                        "prompt_id": {"type": "string"},
                        "track_id": {"type": "string"},
                        "state": {"type": "string"},
                        "min_score": {"type": "number", "minimum": 0},
                        "max_score": {"type": "number", "minimum": 0},
                        "min_area": {"type": "integer", "minimum": 0},
                        "max_area": {"type": "integer", "minimum": 0},
                    },
                },
                "axis": {
                    "type": "string",
                    "enum": ["x", "y", "auto"],
                    "default": "auto",
                    "title": "排序轴",
                },
                "expected_count": {
                    "type": "integer",
                    "minimum": 1,
                    "title": "期望孔数",
                },
                "expected_pitch": {
                    "type": "number",
                    "title": "期望节距",
                },
                "max_abs_pitch_error": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最大节距误差",
                },
                "max_pitch_cv": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最大节距变异系数",
                },
                "max_orthogonal_deviation": {
                    "type": "number",
                    "minimum": 0,
                    "title": "最大离轴偏差",
                },
            },
            "required": ["hole_filter", "expected_count"],
        },
        capability_tags=("vision.assembly", "inspection.hole-pattern", "inspection.spacing"),
    ),
    handler=_hole_pattern_check_handler,
)
