"""多部件存在性检查节点。"""

from __future__ import annotations

from backend.contracts.workflows.workflow_graph import (
    NODE_IMPLEMENTATION_CORE,
    NODE_RUNTIME_PYTHON_CALLABLE,
    NodeDefinition,
    NodePortDefinition,
)
from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.nodes.core_nodes._logic_node_support import build_boolean_payload, build_value_payload
from backend.nodes.core_nodes._region_node_support import (
    filter_region_items,
    require_regions_payload,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest


NODE_NAME = "multi-part-presence-check"


def _multi_part_presence_check_handler(request: WorkflowNodeExecutionRequest) -> dict[str, object]:
    """按多组零件规则一次性检查区域存在性与数量约束。"""

    regions_payload = require_regions_payload(request.input_values.get("regions"), node_id=request.node_id)
    match_mode = _read_match_mode(request.parameters.get("match_mode"))
    requirements = _read_requirements(request.parameters.get("requirements"))

    checked_items: list[dict[str, object]] = []
    passed_items: list[dict[str, object]] = []
    failed_items: list[dict[str, object]] = []
    for requirement in requirements:
        matched_items = filter_region_items(
            regions_payload["items"],
            min_score=requirement["min_score"],
            max_score=requirement["max_score"],
            min_area=requirement["min_area"],
            max_area=requirement["max_area"],
            class_ids={requirement["class_id"]} if requirement["class_id"] is not None else None,
            class_names={requirement["class_name"]} if requirement["class_name"] is not None else None,
            prompt_ids={requirement["prompt_id"]} if requirement["prompt_id"] is not None else None,
            track_ids=None,
            states={requirement["state"]} if requirement["state"] is not None else None,
        )
        matched_count = len(matched_items)
        failure_reasons: list[str] = []
        if matched_count < requirement["min_count"]:
            failure_reasons.append("missing-required-parts")
        if requirement["max_count"] is not None and matched_count > requirement["max_count"]:
            failure_reasons.append("too-many-parts")
        passed = len(failure_reasons) == 0
        checked_item = {
            "part_name": requirement["part_name"],
            "class_name": requirement["class_name"],
            "class_id": requirement["class_id"],
            "prompt_id": requirement["prompt_id"],
            "state": requirement["state"],
            "min_score": requirement["min_score"],
            "max_score": requirement["max_score"],
            "min_area": requirement["min_area"],
            "max_area": requirement["max_area"],
            "min_count": requirement["min_count"],
            "max_count": requirement["max_count"],
            "matched_count": matched_count,
            "matched_region_ids": [str(item["region_id"]) for item in matched_items],
            "matched_scores": [float(item["score"]) for item in matched_items],
            "result": passed,
            "failure_reasons": failure_reasons,
        }
        checked_items.append(checked_item)
        if passed:
            passed_items.append(checked_item)
        else:
            failed_items.append(checked_item)

    if match_mode == "all":
        result_value = bool(checked_items) and len(failed_items) == 0
    else:
        result_value = len(passed_items) > 0
    return {
        "result": build_boolean_payload(result_value),
        "metrics": build_value_payload(
            {
                "match_mode": match_mode,
                "requirements_count": len(requirements),
                "passed_part_count": len(passed_items),
                "failed_part_count": len(failed_items),
                "passed_part_names": [item["part_name"] for item in passed_items],
                "failed_part_names": [item["part_name"] for item in failed_items],
                "items": checked_items,
                "result": result_value,
            }
        ),
    }


def _read_match_mode(raw_value: object) -> str:
    """读取聚合模式。"""

    if raw_value is None:
        return "all"
    if not isinstance(raw_value, str):
        raise InvalidRequestError(f"{NODE_NAME} 节点的 match_mode 必须是字符串")
    normalized_value = raw_value.strip().lower()
    if normalized_value not in {"all", "any"}:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 match_mode 仅支持 all 或 any")
    return normalized_value


def _read_requirements(raw_value: object) -> list[dict[str, object]]:
    """读取多部件检查规则。"""

    if not isinstance(raw_value, list) or not raw_value:
        raise InvalidRequestError(f"{NODE_NAME} 节点的 requirements 必须是非空数组")
    normalized_requirements: list[dict[str, object]] = []
    for item_index, item_value in enumerate(raw_value, start=1):
        if not isinstance(item_value, dict):
            raise InvalidRequestError(
                f"{NODE_NAME} 节点的 requirements[{item_index}] 必须是对象"
            )
        part_name = _require_non_empty_text(item_value.get("part_name"), field_name=f"requirements[{item_index}].part_name")
        class_name = _read_optional_text(item_value.get("class_name"), field_name=f"requirements[{item_index}].class_name")
        class_id = _read_optional_non_negative_int(item_value.get("class_id"), field_name=f"requirements[{item_index}].class_id")
        prompt_id = _read_optional_text(item_value.get("prompt_id"), field_name=f"requirements[{item_index}].prompt_id")
        state = _read_optional_text(item_value.get("state"), field_name=f"requirements[{item_index}].state")
        if class_name is None and class_id is None and prompt_id is None and state is None:
            raise InvalidRequestError(
                f"{NODE_NAME} 节点的 requirements[{item_index}] 至少需要提供 class_name、class_id、prompt_id 或 state 之一"
            )
        min_score = _read_optional_ratio_like_number(item_value.get("min_score"), field_name=f"requirements[{item_index}].min_score")
        max_score = _read_optional_ratio_like_number(item_value.get("max_score"), field_name=f"requirements[{item_index}].max_score")
        min_area = _read_optional_non_negative_int(item_value.get("min_area"), field_name=f"requirements[{item_index}].min_area")
        max_area = _read_optional_non_negative_int(item_value.get("max_area"), field_name=f"requirements[{item_index}].max_area")
        min_count = _read_non_negative_int_with_default(
            item_value.get("min_count"),
            field_name=f"requirements[{item_index}].min_count",
            default_value=1,
        )
        max_count = _read_optional_non_negative_int(item_value.get("max_count"), field_name=f"requirements[{item_index}].max_count")
        if max_count is not None and max_count < min_count:
            raise InvalidRequestError(
                f"{NODE_NAME} 节点的 requirements[{item_index}] 要求 max_count 不能小于 min_count"
            )
        normalized_requirements.append(
            {
                "part_name": part_name,
                "class_name": class_name,
                "class_id": class_id,
                "prompt_id": prompt_id,
                "state": state,
                "min_score": min_score,
                "max_score": max_score,
                "min_area": min_area,
                "max_area": max_area,
                "min_count": min_count,
                "max_count": max_count,
            }
        )
    return normalized_requirements


def _require_non_empty_text(raw_value: object, *, field_name: str) -> str:
    """读取必填非空文本。"""

    if not isinstance(raw_value, str) or not raw_value.strip():
        raise InvalidRequestError(f"{field_name} 必须是非空字符串")
    return raw_value.strip()


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


def _read_non_negative_int_with_default(raw_value: object, *, field_name: str, default_value: int) -> int:
    """读取带默认值的非负整数。"""

    if raw_value is None:
        return int(default_value)
    normalized_value = _read_optional_non_negative_int(raw_value, field_name=field_name)
    if normalized_value is None:
        return int(default_value)
    return normalized_value


def _read_optional_ratio_like_number(raw_value: object, *, field_name: str) -> float | None:
    """读取可选非负数值。"""

    if raw_value is None:
        return None
    if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
        raise InvalidRequestError(f"{field_name} 必须是数值")
    return float(raw_value)


CORE_NODE_SPEC = CoreNodeSpec(
    node_definition=NodeDefinition(
        node_type_id="core.vision.multi-part-presence-check",
        display_name="Multi Part Presence Check",
        category="vision.assembly",
        description="按多组零件规则一次性检查区域存在性与数量约束，适合装配缺件、多件数量异常和组件组合到位检查。",
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
                "match_mode": {
                    "type": "string",
                    "enum": ["all", "any"],
                    "default": "all",
                    "title": "聚合模式",
                },
                "requirements": {
                    "type": "array",
                    "title": "多部件规则列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "part_name": {"type": "string"},
                            "class_name": {"type": "string"},
                            "class_id": {"type": "integer", "minimum": 0},
                            "prompt_id": {"type": "string"},
                            "state": {"type": "string"},
                            "min_score": {"type": "number"},
                            "max_score": {"type": "number"},
                            "min_area": {"type": "integer", "minimum": 0},
                            "max_area": {"type": "integer", "minimum": 0},
                            "min_count": {"type": "integer", "minimum": 0, "default": 1},
                            "max_count": {"type": "integer", "minimum": 0},
                        },
                        "required": ["part_name"],
                    },
                },
            },
            "required": ["requirements"],
        },
        capability_tags=("vision.assembly", "inspection.presence", "inspection.multi-part"),
    ),
    handler=_multi_part_presence_check_handler,
)
