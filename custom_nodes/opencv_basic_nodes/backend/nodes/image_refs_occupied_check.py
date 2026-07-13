"""Image refs 批量有料检查节点。"""

from __future__ import annotations

from dataclasses import dataclass

from backend.nodes.core_nodes.support.logic import build_value_payload
from backend.nodes.runtime_support import load_image_matrix_from_payload
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes._opencv_shared.backend.runtime.imports import require_opencv_imports
from custom_nodes._opencv_shared.backend.runtime.payloads import require_image_refs_payload
from custom_nodes.opencv_basic_nodes.backend.nodes.image_refs_slot_metrics import (
    ImageRefsSlotMetricConfig,
    build_min_check,
    build_slot_metric_item,
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
        "total_count": int(image_refs_payload.get("count", len(image_refs_payload["items"]))),
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
    }


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

    metric_config = config.metric_config
    return {
        "max_items": metric_config.max_items,
        "dark_threshold": metric_config.dark_threshold,
        "bright_threshold": metric_config.bright_threshold,
        "canny_low_threshold": metric_config.canny_low_threshold,
        "canny_high_threshold": metric_config.canny_high_threshold,
        "dark_morph_kernel_size": metric_config.dark_morph_kernel_size,
        "dark_component_min_area": metric_config.dark_component_min_area,
        "std_gray_occupied_min": config.std_gray_occupied_min,
        "dark_ratio_occupied_min": config.dark_ratio_occupied_min,
        "edge_density_occupied_min": config.edge_density_occupied_min,
        "dark_component_area_ratio_occupied_min": config.dark_component_area_ratio_occupied_min,
        "largest_dark_component_area_ratio_occupied_min": config.largest_dark_component_area_ratio_occupied_min,
        "occupied_min_pass_count": config.occupied_min_pass_count,
    }


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
