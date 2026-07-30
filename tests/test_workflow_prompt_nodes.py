"""共享 Prompt 输入节点和 payload 边界测试。"""

from __future__ import annotations

import numpy as np
import pytest

from backend.nodes.core_catalog import get_core_workflow_node_definitions
from backend.nodes.core_nodes.input.prompt.box_prompt import _handle_box_prompt
from backend.nodes.core_nodes.input.prompt.mask_prompt import _handle_mask_prompt
from backend.nodes.core_nodes.input.prompt.mask_editor import _handle_mask_editor
import backend.nodes.core_nodes.input.prompt.mask_editor as mask_editor_module
import backend.nodes.core_nodes.input.prompt.mask_prompt as mask_prompt_module
from backend.nodes.core_nodes.input.prompt.point_prompt import _handle_point_prompt
from backend.nodes.core_nodes.input.prompt.polygon_prompt import (
    _handle_polygon_prompt,
)
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
        "core.input.mask-editor",
        "core.input.prompt-regions-merge",
    } <= node_type_ids
    prompt_editor_node_type_ids = {
        definition.node_type_id
        for definition in get_core_workflow_node_definitions()
        if "prompt.editor" in definition.capability_tags
    }
    assert {
        "core.input.point-prompt",
        "core.input.box-prompt",
        "core.input.polygon-prompt",
        "core.input.mask-editor",
    } <= prompt_editor_node_type_ids


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


def test_visual_prompt_nodes_build_and_merge_shared_payload(monkeypatch) -> None:
    """验证 Point、Box、Mask Prompt 可合并为 prompt-regions.v1。"""

    point = _handle_point_prompt(
        _request(
            node_id="point",
            parameters={
                "prompt_id": "part",
                "positive_points_xy": [[12, 24]],
                "prompt_applied": True,
            },
        )
    )["prompts"]
    box = _handle_box_prompt(
        _request(
            node_id="box",
            parameters={
                "prompt_id": "part-box",
                "bboxes_xyxy": [[2, 3, 20, 30]],
                "prompt_applied": True,
            },
        )
    )["prompts"]
    mask_image = {
        "transport_kind": "storage",
        "object_key": "project/files/mask.png",
        "media_type": "image/png",
    }
    monkeypatch.setattr(
        mask_prompt_module,
        "load_image_matrix_from_payload",
        lambda _request, *, image_payload, **_kwargs: (
            dict(image_payload),
            np.ones((8, 8), dtype=np.uint8),
        ),
    )
    mask = _handle_mask_prompt(
        _request(
            node_id="mask",
            parameters={"prompt_id": "part-mask"},
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


def test_point_prompt_rejects_missing_positive_point() -> None:
    """验证已应用节点缺少 Positive 点时不会构造无效 Prompt。"""

    with pytest.raises(InvalidRequestError, match="Positive"):
        _handle_point_prompt(
            _request(
                node_id="invalid-point",
                parameters={
                    "prompt_id": "part",
                    "positive_points_xy": [],
                    "prompt_applied": True,
                },
            )
        )


def test_mask_editor_invalidates_mask_after_source_image_changes(
    monkeypatch,
) -> None:
    """验证换图后旧 Mask 不再输出，但源图编辑 Preview 仍可打开。"""

    monkeypatch.setattr(
        mask_editor_module,
        "build_debug_image_preview_output",
        lambda *_args, **kwargs: {
            "debug_preview": {
                "type": "image-preview",
                "title": "Mask Editor",
                "interaction": kwargs["interaction"],
            }
        },
    )
    outputs = _handle_mask_editor(
        _request(
            node_id="mask-editor",
            parameters={
                "mask_object_key": "projects/project-1/inputs/mask.png",
                "mask_source_identity": "object_key:projects/project-1/a.png",
            },
            input_values={
                "image": {
                    "transport_kind": "storage",
                    "object_key": "projects/project-1/b.png",
                    "media_type": "image/png",
                    "width": 64,
                    "height": 64,
                }
            },
        )
    )

    assert "mask_image" not in outputs
    assert outputs["debug_preview"]["type"] == "image-preview"
    tool = outputs["debug_preview"]["interaction"]["tools"][0]
    assert tool["mask_object_key"] == ""
    assert tool["source_identity"] == "object_key:projects/project-1/b.png"
    assert tool["source_changed"] is True
    assert tool["applied"] is False


def test_mask_editor_without_applied_mask_only_outputs_debug_preview(
    monkeypatch,
) -> None:
    """验证浏览器空草稿不会变成运行时 Mask 输出。"""

    monkeypatch.setattr(
        mask_editor_module,
        "build_debug_image_preview_output",
        lambda *_args, **kwargs: {
            "debug_preview": {
                "type": "image-preview",
                "interaction": kwargs["interaction"],
            }
        },
    )
    outputs = _handle_mask_editor(
        _request(
            node_id="mask-editor",
            input_values={
                "image": {
                    "transport_kind": "storage",
                    "object_key": "projects/project-1/source.png",
                    "media_type": "image/png",
                    "width": 64,
                    "height": 64,
                }
            },
        )
    )

    assert set(outputs) == {"debug_preview"}
    tool = outputs["debug_preview"]["interaction"]["tools"][0]
    assert tool["source_identity"] == ("object_key:projects/project-1/source.png")
    assert "apply_parameters" not in tool


def test_mask_editor_prefers_stable_content_sha_over_execution_image_handle(
    monkeypatch,
) -> None:
    """验证 memory 图片换临时 handle 后仍使用稳定内容 SHA 关联 Mask。"""

    monkeypatch.setattr(
        mask_editor_module,
        "build_debug_image_preview_output",
        lambda *_args, **kwargs: {
            "debug_preview": {
                "type": "image-preview",
                "interaction": kwargs["interaction"],
            }
        },
    )
    outputs = _handle_mask_editor(
        _request(
            node_id="mask-editor",
            input_values={
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "img-new-run",
                    "content_sha256": "abc123",
                    "media_type": "image/png",
                    "width": 64,
                    "height": 64,
                }
            },
        )
    )

    tool = outputs["debug_preview"]["interaction"]["tools"][0]
    assert tool["source_identity"] == "content_sha256:abc123"
    assert "apply_parameters" not in tool


def test_mask_editor_restores_applied_mask_for_reediting(
    monkeypatch,
) -> None:
    """验证相同源图再次打开时会返回已有 Mask 和编辑器绑定信息。"""

    normalized_mask = {
        "transport_kind": "storage",
        "object_key": "projects/project-1/mask.png",
        "media_type": "image/png",
        "width": 64,
        "height": 64,
    }
    mask_matrix = np.zeros((64, 64), dtype=np.uint8)
    mask_matrix[10:20, 10:20] = 255
    monkeypatch.setattr(
        mask_editor_module,
        "load_image_matrix_from_payload",
        lambda *_args, **_kwargs: (normalized_mask, mask_matrix),
    )
    monkeypatch.setattr(
        mask_editor_module,
        "build_debug_image_preview_output",
        lambda *_args, **kwargs: {
            "debug_preview": {
                "type": "image-preview",
                "interaction": kwargs["interaction"],
            }
        },
    )

    outputs = _handle_mask_editor(
        _request(
            node_id="mask-editor",
            parameters={
                "mask_object_key": "projects/project-1/mask.png",
                "mask_source_identity": "content_sha256:abc123",
            },
            input_values={
                "image": {
                    "transport_kind": "memory",
                    "image_handle": "img-current-run",
                    "content_sha256": "abc123",
                    "media_type": "image/png",
                    "width": 64,
                    "height": 64,
                }
            },
        )
    )

    assert outputs["mask_image"] == normalized_mask
    tool = outputs["debug_preview"]["interaction"]["tools"][0]
    assert tool["mask_object_key"] == "projects/project-1/mask.png"
    assert tool["source_identity"] == "content_sha256:abc123"
    assert tool["applied"] is True
    assert tool["source_changed"] is False


@pytest.mark.parametrize(
    ("handler", "parameters"),
    (
        (
            _handle_point_prompt,
            {
                "prompt_id": "part",
                "positive_points_xy": [[12, 24]],
                "prompt_applied": True,
            },
        ),
        (
            _handle_box_prompt,
            {
                "prompt_id": "part",
                "bboxes_xyxy": [[2, 3, 20, 30]],
                "prompt_applied": True,
            },
        ),
        (
            _handle_polygon_prompt,
            {
                "prompt_id": "part",
                "polygons_xy": [[[2, 3], [20, 3], [20, 30], [2, 30]]],
                "prompt_applied": True,
            },
        ),
    ),
)
def test_applied_geometry_prompt_rejects_changed_source_image(
    handler,
    parameters: dict[str, object],
) -> None:
    """验证已应用几何不能静默迁移到新图。"""

    with pytest.raises(InvalidRequestError, match="源图已变化"):
        handler(
            _request(
                node_id="prompt",
                parameters={
                    **parameters,
                    "prompt_source_identity": ("object_key:projects/project-1/old.png"),
                },
                input_values={
                    "image": {
                        "transport_kind": "storage",
                        "object_key": "projects/project-1/new.png",
                        "media_type": "image/png",
                        "width": 64,
                        "height": 64,
                    }
                },
            )
        )


def test_point_prompt_supports_positive_and_negative_point_arrays() -> None:
    """验证单个节点可为同一对象同时构造多个 Positive/Negative 点。"""

    prompts = _handle_point_prompt(
        _request(
            node_id="points",
            parameters={
                "prompt_id": "part",
                "positive_points_xy": [[12, 24], [16, 28]],
                "negative_points_xy": [[30, 40]],
                "prompt_applied": True,
            },
        )
    )["prompts"]

    assert [item["point_label"] for item in prompts["items"]] == [
        "positive",
        "positive",
        "negative",
    ]
    assert [item["point_xy"] for item in prompts["items"]] == [
        [12.0, 24.0],
        [16.0, 28.0],
        [30.0, 40.0],
    ]


def test_box_and_polygon_prompt_support_multiple_objects() -> None:
    """验证单个 Box/Polygon 节点可产生多个独立对象。"""

    boxes = _handle_box_prompt(
        _request(
            node_id="boxes",
            parameters={
                "prompt_id": "part",
                "display_name": "Part",
                "bboxes_xyxy": [
                    [2, 3, 20, 30],
                    [32, 33, 50, 60],
                ],
                "prompt_applied": True,
            },
        )
    )["prompts"]
    polygons = _handle_polygon_prompt(
        _request(
            node_id="polygons",
            parameters={
                "prompt_id": "region",
                "display_name": "Region",
                "polygons_xy": [
                    [[2, 3], [20, 3], [20, 30], [2, 30]],
                    [[32, 33], [50, 33], [50, 60], [32, 60]],
                ],
                "prompt_applied": True,
            },
        )
    )["prompts"]

    assert [item["prompt_id"] for item in boxes["items"]] == [
        "part",
        "part-2",
    ]
    assert [item["display_name"] for item in boxes["items"]] == [
        "Part 1",
        "Part 2",
    ]
    assert [item["prompt_id"] for item in polygons["items"]] == [
        "region",
        "region-2",
    ]


def test_prompt_regions_merge_rejects_mixed_kinds_for_same_object() -> None:
    """验证同一对象 id 不能混合 Point 与 Box。"""

    point = _handle_point_prompt(
        _request(
            node_id="point",
            parameters={
                "prompt_id": "part",
                "positive_points_xy": [[12, 24]],
                "prompt_applied": True,
            },
        )
    )["prompts"]
    box = _handle_box_prompt(
        _request(
            node_id="box",
            parameters={
                "prompt_id": "part",
                "bboxes_xyxy": [[2, 3, 20, 30]],
                "prompt_applied": True,
            },
        )
    )["prompts"]

    with pytest.raises(InvalidRequestError, match="不能混合"):
        _handle_prompt_regions_merge(
            _request(
                node_id="merge",
                input_values={"prompts": (point, box)},
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
