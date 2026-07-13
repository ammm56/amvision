"""Image refs 批量空槽检查节点。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import require_image_refs_payload
from custom_nodes.opencv_basic_nodes.backend.nodes.image_refs_slot_metrics import (
    ImageRefsSlotMetricConfig,
    build_max_check,
    build_min_check,
    build_slot_metric_item,
    read_bool_with_default,
    read_optional_non_negative_float,
    read_optional_positive_int,
    read_optional_ratio,
    read_slot_metric_config,
)


NODE_TYPE_ID = "custom.opencv.image-refs-empty-check"
NODE_DISPLAY_NAME = "image-refs-empty-check"


@dataclass(frozen=True)
class EmptyCheckConfig:
    """描述批量空槽检查的参数。"""

    expected_count: int | None
    metric_config: ImageRefsSlotMetricConfig
    std_gray_empty_max: float | None
    dark_ratio_empty_max: float | None
    bright_ratio_empty_min: float | None
    edge_density_empty_max: float | None
    dark_component_area_ratio_empty_max: float | None
    largest_dark_component_area_ratio_empty_max: float | None
    empty_when_all_rules_pass: bool


def handle_node(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """对 image-refs.v1 中每张槽位图片执行多指标 empty / non-empty 判断。"""

    cv2_module, np_module = require_opencv_imports()
    image_refs_payload = require_image_refs_payload(request.input_values.get("images"))
    config = _read_config(request)
    source_items = list(image_refs_payload["items"])
    if config.metric_config.max_items is not None:
        source_items = source_items[: config.metric_config.max_items]

    check_items: list[dict[str, object]] = []
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
            config=config.metric_config,
            node_display_name=NODE_DISPLAY_NAME,
        )
        check_items.append(_build_check_item(metric_item, config=config))

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
        "total_count": int(image_refs_payload.get("count", len(image_refs_payload["items"]))),
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
    }


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

    metric_config = config.metric_config
    return {
        "max_items": metric_config.max_items,
        "dark_threshold": metric_config.dark_threshold,
        "bright_threshold": metric_config.bright_threshold,
        "canny_low_threshold": metric_config.canny_low_threshold,
        "canny_high_threshold": metric_config.canny_high_threshold,
        "dark_morph_kernel_size": metric_config.dark_morph_kernel_size,
        "dark_component_min_area": metric_config.dark_component_min_area,
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
        metric_config=read_slot_metric_config(request, node_display_name=NODE_DISPLAY_NAME),
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
