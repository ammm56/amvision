"""共享 Prompt 输入节点和 payload 边界测试。"""

from __future__ import annotations

import pytest

from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.core_nodes.input.prompt.box_prompt import _handle_box_prompt
from backend.nodes.core_nodes.input.prompt.mask_prompt import _handle_mask_prompt
from backend.nodes.core_nodes.input.prompt.point_prompt import _handle_point_prompt
from backend.nodes.core_nodes.input.prompt.prompt_regions_merge import (
    _handle_prompt_regions_merge,
)
from backend.nodes.core_nodes.input.prompt.text_prompt import _handle_text_prompt
from backend.nodes.core_nodes.input.prompt.text_prompts_merge import (
    _handle_text_prompts_merge,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)


def test_core_catalog_contains_prompt_input_nodes() -> None:
    """验证共享 Prompt 节点完整进入 Core Catalog。"""

    node_type_ids = {
        definition.node_type_id for definition in get_core_workflow_node_definitions()
    }

    assert {
        "core.input.text-prompt",
        "core.input.text-prompts-merge",
        "core.input.point-prompt",
        "core.input.box-prompt",
        "core.input.polygon-prompt",
        "core.input.mask-prompt",
        "core.input.prompt-regions-merge",
    } <= node_type_ids


def test_text_prompt_and_merge_build_shared_payload() -> None:
    """验证文本 Prompt 可构造并合并为 text-prompts.v1。"""

    positive = _handle_text_prompt(
        _request(
            node_id="positive",
            parameters={"prompt_id": "part", "text": "metal part"},
        )
    )["prompts"]
    negative = _handle_text_prompt(
        _request(
            node_id="negative",
            parameters={
                "prompt_id": "part",
                "text": "background",
                "negative": True,
            },
        )
    )["prompts"]

    merged = _handle_text_prompts_merge(
        _request(
            node_id="merge",
            input_values={"prompts": (positive, negative)},
        )
    )["prompts"]

    assert merged["items"] == [
        {
            "prompt_id": "part",
            "text": "metal part",
            "display_name": "metal part",
            "negative": False,
        },
        {
            "prompt_id": "part",
            "text": "background",
            "display_name": "background",
            "negative": True,
        },
    ]


def test_visual_prompt_nodes_build_and_merge_shared_payload() -> None:
    """验证 Point、Box、Mask Prompt 可合并为 prompt-regions.v1。"""

    point = _handle_point_prompt(
        _request(
            node_id="point",
            parameters={
                "prompt_id": "part",
                "x": 12,
                "y": 24,
                "point_label": "positive",
            },
        )
    )["prompts"]
    box = _handle_box_prompt(
        _request(
            node_id="box",
            parameters={
                "prompt_id": "part",
                "x1": 2,
                "y1": 3,
                "x2": 20,
                "y2": 30,
            },
        )
    )["prompts"]
    mask_image = {
        "transport_kind": "object-store",
        "object_key": "project/files/mask.png",
        "media_type": "image/png",
    }
    mask = _handle_mask_prompt(
        _request(
            node_id="mask",
            parameters={"prompt_id": "part"},
            input_values={"mask_image": mask_image},
        )
    )["prompts"]

    merged = _handle_prompt_regions_merge(
        _request(
            node_id="merge",
            input_values={"prompts": (point, box, mask)},
        )
    )["prompts"]

    assert [item["prompt_kind"] for item in merged["items"]] == [
        "point",
        "box",
        "mask",
    ]
    assert merged["items"][0]["point_xy"] == [12.0, 24.0]
    assert merged["items"][1]["bbox_xyxy"] == [2.0, 3.0, 20.0, 30.0]
    assert merged["items"][2]["mask_image"] == mask_image


def test_point_prompt_rejects_missing_coordinate() -> None:
    """验证缺少坐标时不会构造无效视觉 Prompt。"""

    with pytest.raises(InvalidRequestError, match="point_xy"):
        _handle_point_prompt(
            _request(
                node_id="invalid-point",
                parameters={"prompt_id": "part", "x": 12},
            )
        )


def _request(
    *,
    node_id: str,
    parameters: dict[str, object] | None = None,
    input_values: dict[str, object] | None = None,
) -> WorkflowNodeExecutionRequest:
    """构造 Prompt 节点测试请求。"""

    return WorkflowNodeExecutionRequest(
        node_id=node_id,
        node_definition=object(),
        parameters=parameters or {},
        input_values=input_values or {},
        execution_metadata={},
    )
