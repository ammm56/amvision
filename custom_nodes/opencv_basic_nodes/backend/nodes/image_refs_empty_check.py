"""Image refs 批量空槽检查节点。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.nodes.core_nodes.support.logic import build_value_payload, require_value_payload
from backend.nodes.debug_image_panel import build_checkbox_control, build_number_control, build_numeric_control, is_debug_image_panel_enabled
from backend.nodes.parameter_utils import is_empty_parameter
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import require_image_refs_payload
from custom_nodes.opencv_basic_nodes.backend.nodes.image_refs_slot_metrics import (
    build_max_check,
    build_min_check,
    build_slot_metric_debug_preview_output,
    read_bool_with_default,
    read_optional_non_negative_float,
    read_optional_positive_int,
    read_optional_ratio,
)


NODE_TYPE_ID = "custom.opencv.image-refs-empty-check"
NODE_DISPLAY_NAME = "image-refs-empty-check"


@dataclass(frozen=True)
class EmptyCheckConfig:
    """描述批量空槽检查的参数。"""

    expected_count: int | None
    std_gray_empty_max: float | None
    dark_ratio_empty_max: float | None
    bright_ratio_empty_min: float | None
    edge_density_empty_max: float | None
    dark_component_area_ratio_empty_max: float | None
    largest_dark_component_area_ratio_empty_max: float | None
    empty_when_all_rules_pass: bool


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 slot metrics 中每个槽位执行多指标 empty / non-empty 判断。"""

    cv2_module, np_module = require_opencv_imports()
    config = _read_config(request)
    image_refs_payload = _read_optional_image_refs_payload(request.input_values.get("images"))
    metrics_payload = _read_required_slot_metrics_payload(request.input_values.get("metrics"))
    metric_items, total_count, debug_records = _resolve_metric_items(
        request,
        cv2_module=cv2_module,
        np_module=np_module,
        image_refs_payload=image_refs_payload,
        metrics_payload=metrics_payload,
    )
    check_items = [_build_check_item(metric_item, config=config) for metric_item in metric_items]

    empty_count = sum(1 for item in check_items if item.get("is_empty") is True)
    non_empty_count = sum(1 for item in check_items if item.get("is_empty") is False)
    unknown_count = sum(1 for item in check_items if item.get("is_empty") is None)
    expected_count_matched = (
        None
        if config.expected_count is None
        else len(check_items) == config.expected_count
    )
    all_empty = bool(check_items) and unknown_count == 0 and non_empty_count == 0
    state = _build_overall_state(
        count=len(check_items),
        expected_count_matched=expected_count_matched,
        unknown_count=unknown_count,
        non_empty_count=non_empty_count,
    )
    payload = {
        "format_id": "amvision.image-refs-empty-check.v1",
        "count": len(check_items),
        "total_count": total_count,
        "expected_count": config.expected_count,
        "expected_count_matched": expected_count_matched,
        "empty_count": empty_count,
        "non_empty_count": non_empty_count,
        "unknown_count": unknown_count,
        "all_empty": all_empty,
        "state": state,
        "rules": _build_rule_summary(config),
        "items": check_items,
    }
    return {
        "summary": build_value_payload(payload),
        "body": {
            "type": "image-refs-empty-check",
            **payload,
        },
        **build_slot_metric_debug_preview_output(
            request,
            cv2_module=cv2_module,
            np_module=np_module,
            image_records=_attach_check_items_to_debug_records(debug_records, check_items),
            title="Image Refs Empty Check",
            controls=_build_empty_check_controls(config),
            artifact_name="empty-check-debug-preview",
            ok_decisions=("empty",),
            bad_decisions=("non-empty",),
        ),
    }


def _resolve_metric_items(
    request: WorkflowNodeExecutionRequest,
    *,
    cv2_module: object,
    np_module: object,
    image_refs_payload: dict[str, object] | None,
    metrics_payload: dict[str, object],
) -> tuple[list[dict[str, object]], int, list[dict[str, object]]]:
    """从 Image Refs Slot Metrics.summary 得到统一的槽位指标列表。"""

    metric_items = list(metrics_payload.get("items") or ())
    debug_records = _load_debug_records_from_images(
        request,
        cv2_module=cv2_module,
        np_module=np_module,
        image_refs_payload=image_refs_payload,
        limit=len(metric_items),
        metric_items=metric_items,
    )
    return metric_items, int(metrics_payload.get("total_count", len(metric_items))), debug_records


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
    """把最终判断结果写入 debug record，contact sheet 才能显示 empty/non-empty。"""

    if not debug_records:
        return []
    merged_records: list[dict[str, object]] = []
    for record, check_item in zip(debug_records, check_items, strict=False):
        merged_record = dict(record)
        merged_record["item"] = check_item
        merged_records.append(merged_record)
    return merged_records


def _build_check_item(metric_item: dict[str, object], *, config: EmptyCheckConfig) -> dict[str, object]:
    """按 empty 规则补充单槽判断。"""

    metrics = metric_item["metrics"]
    checks = _evaluate_checks(metrics, config=config)
    enabled_checks = [check for check in checks.values() if check["enabled"] is True]
    is_empty = _resolve_empty_decision(enabled_checks, config=config)
    return {
        **metric_item,
        "checks": checks,
        "is_empty": is_empty,
        "decision": "empty" if is_empty is True else "non-empty" if is_empty is False else "unknown",
        "failed_rules": [
            rule_name
            for rule_name, check in checks.items()
            if check["enabled"] is True and check["passed"] is False
        ],
    }


def _evaluate_checks(metrics: dict[str, object], *, config: EmptyCheckConfig) -> dict[str, dict[str, object]]:
    """按启用阈值生成每条 empty 规则的判断结果。"""

    return {
        "std_gray_empty_max": build_max_check(metrics["std_gray"], config.std_gray_empty_max),
        "dark_ratio_empty_max": build_max_check(metrics["dark_ratio"], config.dark_ratio_empty_max),
        "bright_ratio_empty_min": build_min_check(metrics["bright_ratio"], config.bright_ratio_empty_min),
        "edge_density_empty_max": build_max_check(metrics["edge_density"], config.edge_density_empty_max),
        "dark_component_area_ratio_empty_max": build_max_check(
            metrics["dark_component_area_ratio"],
            config.dark_component_area_ratio_empty_max,
        ),
        "largest_dark_component_area_ratio_empty_max": build_max_check(
            metrics["largest_dark_component_area_ratio"],
            config.largest_dark_component_area_ratio_empty_max,
        ),
    }


def _resolve_empty_decision(
    enabled_checks: list[dict[str, object]],
    *,
    config: EmptyCheckConfig,
) -> bool | None:
    """把多条规则合并为最终 empty 判断。"""

    if not enabled_checks:
        return None
    if config.empty_when_all_rules_pass:
        return all(check["passed"] is True for check in enabled_checks)
    return any(check["passed"] is True for check in enabled_checks)


def _build_overall_state(
    *,
    count: int,
    expected_count_matched: bool | None,
    unknown_count: int,
    non_empty_count: int,
) -> str:
    """生成整批槽位检查状态。"""

    if count <= 0:
        return "failed"
    if expected_count_matched is False:
        return "failed"
    if unknown_count > 0:
        return "unknown"
    if non_empty_count > 0:
        return "ng"
    return "ok"


def _build_rule_summary(config: EmptyCheckConfig) -> dict[str, object]:
    """返回本次检查实际使用的规则配置。"""

    return {
        "std_gray_empty_max": config.std_gray_empty_max,
        "dark_ratio_empty_max": config.dark_ratio_empty_max,
        "bright_ratio_empty_min": config.bright_ratio_empty_min,
        "edge_density_empty_max": config.edge_density_empty_max,
        "dark_component_area_ratio_empty_max": config.dark_component_area_ratio_empty_max,
        "largest_dark_component_area_ratio_empty_max": config.largest_dark_component_area_ratio_empty_max,
        "empty_when_all_rules_pass": config.empty_when_all_rules_pass,
    }


def _read_config(request: WorkflowNodeExecutionRequest) -> EmptyCheckConfig:
    """读取节点参数。"""

    return EmptyCheckConfig(
        expected_count=read_optional_positive_int(request.parameters.get("expected_count"), field_name="expected_count"),
        std_gray_empty_max=read_optional_ratio_or_number(
            request.parameters.get("std_gray_empty_max"),
            field_name="std_gray_empty_max",
            default_value=56,
        ),
        dark_ratio_empty_max=read_optional_ratio(
            request.parameters.get("dark_ratio_empty_max"),
            field_name="dark_ratio_empty_max",
            default_value=0.02,
        ),
        bright_ratio_empty_min=read_optional_ratio(
            request.parameters.get("bright_ratio_empty_min"),
            field_name="bright_ratio_empty_min",
        ),
        edge_density_empty_max=read_optional_ratio(
            request.parameters.get("edge_density_empty_max"),
            field_name="edge_density_empty_max",
            default_value=0.18,
        ),
        dark_component_area_ratio_empty_max=read_optional_ratio(
            request.parameters.get("dark_component_area_ratio_empty_max"),
            field_name="dark_component_area_ratio_empty_max",
            default_value=0.02,
        ),
        largest_dark_component_area_ratio_empty_max=read_optional_ratio(
            request.parameters.get("largest_dark_component_area_ratio_empty_max"),
            field_name="largest_dark_component_area_ratio_empty_max",
            default_value=0.012,
        ),
        empty_when_all_rules_pass=read_bool_with_default(
            request.parameters.get("empty_when_all_rules_pass"),
            default_value=True,
            field_name="empty_when_all_rules_pass",
        ),
    )


def _build_empty_check_controls(config: EmptyCheckConfig) -> list[dict[str, object]]:
    """构造 ImageViewer 中用于空槽检查的算法调参控件。"""

    return [
        build_number_control("expected_count", "Expected Count", config.expected_count, min_value=1, step=1),
        build_number_control("std_gray_empty_max", "Std Gray Empty Max", config.std_gray_empty_max, min_value=0, step=1),
        build_numeric_control(
            "dark_ratio_empty_max",
            "Dark Ratio Empty Max",
            config.dark_ratio_empty_max if config.dark_ratio_empty_max is not None else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_number_control(
            "bright_ratio_empty_min",
            "Bright Ratio Empty Min",
            config.bright_ratio_empty_min,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_numeric_control(
            "edge_density_empty_max",
            "Edge Density Empty Max",
            config.edge_density_empty_max if config.edge_density_empty_max is not None else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_numeric_control(
            "dark_component_area_ratio_empty_max",
            "Dark Component Area Ratio Empty Max",
            config.dark_component_area_ratio_empty_max if config.dark_component_area_ratio_empty_max is not None else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_numeric_control(
            "largest_dark_component_area_ratio_empty_max",
            "Largest Dark Component Ratio Empty Max",
            config.largest_dark_component_area_ratio_empty_max
            if config.largest_dark_component_area_ratio_empty_max is not None
            else 0,
            min_value=0,
            max_value=1,
            step=0.001,
        ),
        build_checkbox_control("empty_when_all_rules_pass", "All Rules Required", config.empty_when_all_rules_pass),
    ]


def _read_optional_image_refs_payload(raw_payload: object) -> dict[str, object] | None:
    """读取可选 image-refs 输入。"""

    if is_empty_parameter(raw_payload):
        return None
    return require_image_refs_payload(raw_payload)


def _read_required_slot_metrics_payload(raw_payload: object) -> dict[str, object]:
    """读取必填槽位指标 value 输入。"""

    if is_empty_parameter(raw_payload):
        raise InvalidRequestError(f"{NODE_DISPLAY_NAME} 节点需要连接 Image Refs Slot Metrics.summary 到 metrics 输入")
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


def read_optional_ratio_or_number(
    raw_value: object,
    *,
    field_name: str,
    default_value: float | None = None,
) -> float | None:
    """读取可选非负数。

    `std_gray` 这类指标不是 0-1 比例，单独保留该 helper，避免误用 ratio 校验。
    """

    return read_optional_non_negative_float(raw_value, field_name=field_name, default_value=default_value)
