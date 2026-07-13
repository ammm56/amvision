"""Image refs 批量有料检查节点。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.debug_image_panel import build_number_control, build_numeric_control, is_debug_image_panel_enabled
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import require_image_refs_payload
from custom_nodes.opencv_basic_nodes.backend.nodes.image_refs_slot_metrics import (
    ImageRefsSlotMetricConfig,
    build_min_check,
    build_slot_metric_controls,
    build_slot_metric_debug_preview_output,
    build_slot_metric_item,
    build_slot_metric_rule_summary,
    read_optional_non_negative_float,
    read_optional_positive_int,
    read_optional_ratio,
    read_positive_int_with_default,
    read_slot_metric_config,
)


NODE_TYPE_ID = "custom.opencv.image-refs-occupied-check"
NODE_DISPLAY_NAME = "image-refs-occupied-check"


@dataclass(frozen=True)
class OccupiedCheckConfig:
    """描述批量有料检查的参数。"""

    expected_count: int | None
    metric_config: ImageRefsSlotMetricConfig
    std_gray_occupied_min: float | None
    dark_ratio_occupied_min: float | None
    edge_density_occupied_min: float | None
    dark_component_area_ratio_occupied_min: float | None
    largest_dark_component_area_ratio_occupied_min: float | None
    occupied_min_pass_count: int


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 image-refs.v1 中每张槽位图片执行多指标 occupied / empty 判断。"""

    cv2_module, np_module = require_opencv_imports()
    config = _read_config(request)
    image_refs_payload = _read_optional_image_refs_payload(request.input_values.get("images"))
    metrics_payload = _read_optional_slot_metrics_payload(request.input_values.get("metrics"))
    metric_items, total_count, debug_records = _resolve_metric_items(
        request,
        cv2_module=cv2_module,
        np_module=np_module,
        image_refs_payload=image_refs_payload,
        metrics_payload=metrics_payload,
        config=config,
    )
    check_items = [_build_check_item(metric_item, config=config) for metric_item in metric_items]

    occupied_count = sum(1 for item in check_items if item.get("is_occupied") is True)
    empty_count = sum(1 for item in check_items if item.get("is_occupied") is False)
    unknown_count = sum(1 for item in check_items if item.get("is_occupied") is None)
    expected_count_matched = (
        None
        if config.expected_count is None
        else len(check_items) == config.expected_count
    )
    all_occupied = bool(check_items) and unknown_count == 0 and empty_count == 0
    state = _build_overall_state(
        count=len(check_items),
        expected_count_matched=expected_count_matched,
        unknown_count=unknown_count,
        empty_count=empty_count,
    )
    payload = {
        "format_id": "amvision.image-refs-occupied-check.v1",
        "count": len(check_items),
        "total_count": total_count,
        "expected_count": config.expected_count,
        "expected_count_matched": expected_count_matched,
        "occupied_count": occupied_count,
        "empty_count": empty_count,
        "unknown_count": unknown_count,
        "all_occupied": all_occupied,
        "state": state,
        "rules": _build_rule_summary(config),
        "items": check_items,
    }
    return {
        "summary": build_value_payload(payload),
        "body": {
            "type": "image-refs-occupied-check",
            **payload,
        },
        **build_slot_metric_debug_preview_output(
            request,
            cv2_module=cv2_module,
            np_module=np_module,
            image_records=_attach_check_items_to_debug_records(debug_records, check_items),
            title="Image Refs Occupied Check",
            controls=_build_occupied_check_controls(config),
            artifact_name="occupied-check-debug-preview",
            ok_decisions=("occupied",),
            bad_decisions=("empty",),
        ),
    }


def _resolve_metric_items(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: object,
    np_module: object,
    image_refs_payload: dict[str, object] | None,
    metrics_payload: dict[str, object] | None,
    config: OccupiedCheckConfig,
) -> tuple[list[dict[str, object]], int, list[dict[str, object]]]:
    """从 metrics 输入或 images 输入得到统一的槽位指标列表。"""

    if metrics_payload is not None:
        metric_items = list(metrics_payload.get("items") or ())
        if config.metric_config.max_items is not None:
            metric_items = metric_items[: config.metric_config.max_items]
        debug_records = _load_debug_records_from_images(
            request,
            cv2_module=cv2_module,
            np_module=np_module,
            image_refs_payload=image_refs_payload,
            limit=len(metric_items),
            metric_items=metric_items,
        )
        return metric_items, int(metrics_payload.get("total_count", len(metric_items))), debug_records
    if image_refs_payload is None:
        raise InvalidRequestError(f"{NODE_DISPLAY_NAME} 节点需要连接 images 或 metrics 输入")
    return _compute_metrics_from_images(
        request,
        cv2_module=cv2_module,
        np_module=np_module,
        image_refs_payload=image_refs_payload,
        config=config.metric_config,
    )


def _compute_metrics_from_images(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: object,
    np_module: object,
    image_refs_payload: dict[str, object],
    config: ImageRefsSlotMetricConfig,
) -> tuple[list[dict[str, object]], int, list[dict[str, object]]]:
    """直接从 image-refs.v1 计算槽位指标。"""

    source_items = list(image_refs_payload["items"])
    if config.max_items is not None:
        source_items = source_items[: config.max_items]
    metric_items: list[dict[str, object]] = []
    debug_records: list[dict[str, object]] = []
    for item_index, image_item in enumerate(source_items, start=1):
        image_payload, image_matrix = load_image_matrix_from_payload(
            request,
            image_payload=image_item,
            cv2_module=cv2_module,
            np_module=np_module,
            copy_raw=False,
        )
        metric_item = build_slot_metric_item(
            cv2_module=cv2_module,
            np_module=np_module,
            image_payload=image_payload,
            image_matrix=image_matrix,
            item_index=item_index,
            config=config,
            node_display_name=NODE_DISPLAY_NAME,
        )
        metric_items.append(metric_item)
        debug_records.append({"image_payload": image_payload, "image_matrix": image_matrix, "item": metric_item})
    return metric_items, int(image_refs_payload.get("count", len(image_refs_payload["items"]))), debug_records


def _load_debug_records_from_images(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: object,
    np_module: object,
    image_refs_payload: dict[str, object] | None,
    limit: int,
    metric_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    """metrics 链路下按需读取 images，用于编辑态 contact sheet。"""

    if image_refs_payload is None or not is_debug_image_panel_enabled(request):
        return []
    debug_records: list[dict[str, object]] = []
    for image_item, metric_item in zip(list(image_refs_payload["items"])[:limit], metric_items, strict=False):
        image_payload, image_matrix = load_image_matrix_from_payload(
            request,
            image_payload=image_item,
            cv2_module=cv2_module,
            np_module=np_module,
            copy_raw=False,
        )
        debug_records.append({"image_payload": image_payload, "image_matrix": image_matrix, "item": metric_item})
    return debug_records


def _attach_check_items_to_debug_records(
    debug_records: list[dict[str, object]],
    check_items: list[dict[str, object]],
) -> list[dict[str, object]]:
    """把最终判断结果写入 debug record，contact sheet 才能显示 occupied/empty。"""

    if not debug_records:
        return []
    merged_records: list[dict[str, object]] = []
    for record, check_item in zip(debug_records, check_items, strict=False):
        merged_record = dict(record)
        merged_record["item"] = check_item
        merged_records.append(merged_record)
    return merged_records


def _build_check_item(metric_item: dict[str, object], *, config: OccupiedCheckConfig) -> dict[str, object]:
    """按 occupied 规则补充单槽判断。"""

    metrics = metric_item["metrics"]
    checks = _evaluate_checks(metrics, config=config)
    enabled_checks = [check for check in checks.values() if check["enabled"] is True]
    passed_rule_count = sum(1 for check in enabled_checks if check["passed"] is True)
    is_occupied = _resolve_occupied_decision(
        enabled_checks,
        passed_rule_count=passed_rule_count,
        config=config,
    )
    return {
        **metric_item,
        "checks": checks,
        "passed_rule_count": passed_rule_count,
        "is_occupied": is_occupied,
        "decision": "occupied" if is_occupied is True else "empty" if is_occupied is False else "unknown",
        "failed_rules": [
            rule_name
            for rule_name, check in checks.items()
            if check["enabled"] is True and check["passed"] is False
        ],
    }


def _evaluate_checks(metrics: dict[str, object], *, config: OccupiedCheckConfig) -> dict[str, dict[str, object]]:
    """按启用阈值生成每条 occupied 规则的判断结果。"""

    return {
        "std_gray_occupied_min": build_min_check(metrics["std_gray"], config.std_gray_occupied_min),
        "dark_ratio_occupied_min": build_min_check(metrics["dark_ratio"], config.dark_ratio_occupied_min),
        "edge_density_occupied_min": build_min_check(metrics["edge_density"], config.edge_density_occupied_min),
        "dark_component_area_ratio_occupied_min": build_min_check(
            metrics["dark_component_area_ratio"],
            config.dark_component_area_ratio_occupied_min,
        ),
        "largest_dark_component_area_ratio_occupied_min": build_min_check(
            metrics["largest_dark_component_area_ratio"],
            config.largest_dark_component_area_ratio_occupied_min,
        ),
    }


def _resolve_occupied_decision(
    enabled_checks: list[dict[str, object]],
    *,
    passed_rule_count: int,
    config: OccupiedCheckConfig,
) -> bool | None:
    """把多条规则合并为最终 occupied 判断。"""

    if not enabled_checks:
        return None
    return passed_rule_count >= config.occupied_min_pass_count


def _build_overall_state(
    *,
    count: int,
    expected_count_matched: bool | None,
    unknown_count: int,
    empty_count: int,
) -> str:
    """生成整批槽位检查状态。"""

    if count <= 0:
        return "failed"
    if expected_count_matched is False:
        return "failed"
    if unknown_count > 0:
        return "unknown"
    if empty_count > 0:
        return "ng"
    return "ok"


def _build_rule_summary(config: OccupiedCheckConfig) -> dict[str, object]:
    """返回本次检查实际使用的规则配置。"""

    return {
        **build_slot_metric_rule_summary(config.metric_config),
        "std_gray_occupied_min": config.std_gray_occupied_min,
        "dark_ratio_occupied_min": config.dark_ratio_occupied_min,
        "edge_density_occupied_min": config.edge_density_occupied_min,
        "dark_component_area_ratio_occupied_min": config.dark_component_area_ratio_occupied_min,
        "largest_dark_component_area_ratio_occupied_min": config.largest_dark_component_area_ratio_occupied_min,
        "occupied_min_pass_count": config.occupied_min_pass_count,
    }


def _build_occupied_check_controls(config: OccupiedCheckConfig) -> list[dict[str, object]]:
    """构造 ImageViewer 中用于有料检查的算法调参控件。"""

    return [
        *build_slot_metric_controls(config.metric_config),
        build_number_control("expected_count", "Expected Count", config.expected_count, min_value=1, step=1),
        build_number_control(
            "std_gray_occupied_min",
            "Std Gray Occupied Min",
            config.std_gray_occupied_min,
            min_value=0,
            step=1,
        ),
        build_numeric_control(
            "dark_ratio_occupied_min",
            "Dark Ratio Occupied Min",
            config.dark_ratio_occupied_min if config.dark_ratio_occupied_min is not None else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_numeric_control(
            "edge_density_occupied_min",
            "Edge Density Occupied Min",
            config.edge_density_occupied_min if config.edge_density_occupied_min is not None else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_numeric_control(
            "dark_component_area_ratio_occupied_min",
            "Dark Component Area Ratio Occupied Min",
            config.dark_component_area_ratio_occupied_min
            if config.dark_component_area_ratio_occupied_min is not None
            else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_numeric_control(
            "largest_dark_component_area_ratio_occupied_min",
            "Largest Dark Component Ratio Occupied Min",
            config.largest_dark_component_area_ratio_occupied_min
            if config.largest_dark_component_area_ratio_occupied_min is not None
            else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_number_control(
            "occupied_min_pass_count",
            "Min Passed Rules",
            config.occupied_min_pass_count,
            min_value=1,
            step=1,
        ),
    ]


def _read_optional_image_refs_payload(raw_payload: object) -> dict[str, object] | None:
    """读取可选 image-refs 输入。"""

    if is_empty_parameter(raw_payload):
        return None
    return require_image_refs_payload(raw_payload)


def _read_optional_slot_metrics_payload(raw_payload: object) -> dict[str, object] | None:
    """读取可选槽位指标 value 输入。"""

    if is_empty_parameter(raw_payload):
        return None
    value_payload = require_value_payload(raw_payload, field_name="metrics")
    value = value_payload["value"]
    if not isinstance(value, dict):
        raise InvalidRequestError("metrics 输入必须是 Image Refs Slot Metrics.summary 输出")
    if value.get("format_id") != "amvision.image-refs-slot-metrics.v1":
        raise InvalidRequestError("metrics 输入必须来自 Image Refs Slot Metrics 节点")
    items = value.get("items")
    if not isinstance(items, list):
        raise InvalidRequestError("metrics 输入缺少 items 列表")
    return value


def _read_config(request: WorkflowNodeExecutionRequest) -> OccupiedCheckConfig:
    """读取节点参数。"""

    return OccupiedCheckConfig(
        expected_count=read_optional_positive_int(request.parameters.get("expected_count"), field_name="expected_count"),
        metric_config=read_slot_metric_config(request, node_display_name=NODE_DISPLAY_NAME),
        std_gray_occupied_min=read_optional_non_negative_float(
            request.parameters.get("std_gray_occupied_min"),
            field_name="std_gray_occupied_min",
            default_value=42,
        ),
        dark_ratio_occupied_min=read_optional_ratio(
            request.parameters.get("dark_ratio_occupied_min"),
            field_name="dark_ratio_occupied_min",
            default_value=0.018,
        ),
        edge_density_occupied_min=read_optional_ratio(
            request.parameters.get("edge_density_occupied_min"),
            field_name="edge_density_occupied_min",
            default_value=0.16,
        ),
        dark_component_area_ratio_occupied_min=read_optional_ratio(
            request.parameters.get("dark_component_area_ratio_occupied_min"),
            field_name="dark_component_area_ratio_occupied_min",
            default_value=0.015,
        ),
        largest_dark_component_area_ratio_occupied_min=read_optional_ratio(
            request.parameters.get("largest_dark_component_area_ratio_occupied_min"),
            field_name="largest_dark_component_area_ratio_occupied_min",
            default_value=0.008,
        ),
        occupied_min_pass_count=read_positive_int_with_default(
            request.parameters.get("occupied_min_pass_count"),
            field_name="occupied_min_pass_count",
            default_value=2,
        ),
    )
