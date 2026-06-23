"""workflow service node 平台参数 schema 构造。"""

from __future__ import annotations

from backend.nodes.core_nodes.support.platform.constants import (
    WORKFLOW_SERVICE_MODEL_TYPES,
    WORKFLOW_SERVICE_TASK_TYPES,
)
from backend.nodes.core_nodes.support.platform.parameters import (
    get_supported_platform_model_types,
)


def build_platform_task_type_parameter_schema() -> dict[str, object]:
    """返回统一 task_type 参数 schema。"""

    return {
        "type": "string",
        "enum": list(WORKFLOW_SERVICE_TASK_TYPES),
    }


def build_platform_model_type_parameter_schema(
    *,
    task_type: str | None = None,
) -> dict[str, object]:
    """返回统一 model_type 参数 schema。"""

    model_types = (
        WORKFLOW_SERVICE_MODEL_TYPES
        if task_type is None
        else get_supported_platform_model_types(task_type)
    )
    return {
        "type": "string",
        "enum": list(model_types),
    }


def build_platform_task_model_type_schema_guards() -> list[dict[str, object]]:
    """返回 task_type -> model_type 的条件 schema。"""

    return [
        {
            "if": {
                "properties": {
                    "task_type": {"const": task_type},
                }
            },
            "then": {
                "properties": {
                    "model_type": build_platform_model_type_parameter_schema(
                        task_type=task_type
                    ),
                }
            },
        }
        for task_type in WORKFLOW_SERVICE_TASK_TYPES
    ]

