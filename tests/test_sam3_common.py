"""SAM3 公共资产解析与 prompt 规范化测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.graph_executor import WorkflowNodeExecutionRequest
from custom_nodes.sam3_segment_nodes.backend.payloads.inputs import (
    merge_text_prompt_items,
    read_interactive_prompt_items,
    read_text_prompt_items,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.pretrained import (
    resolve_sam3_pretrained_variant,
)


def test_resolve_sam3_pretrained_variant_reads_local_manifest() -> None:
    """验证 SAM3 本地 manifest 可以被公共 helper 正确解析。"""

    variant = resolve_sam3_pretrained_variant(model_scale="l")

    assert variant.model_name == "sam3"
    assert variant.model_scale == "l"
    assert variant.task_type == "segmentation"
    assert variant.variant_name == "default"
    assert variant.checkpoint_path.name == "sam3.pt"


def test_read_interactive_prompt_items_accepts_box_and_point() -> None:
    """验证第一阶段交互 prompt 支持 box 与 point。"""

    payload = {
        "items": [
            {
                "prompt_id": "box-1",
                "prompt_kind": "box",
                "bbox_xyxy": [10, 20, 30, 40],
            },
            {
                "prompt_id": "point-1",
                "prompt_kind": "point",
                "point_xy": [15, 25],
                "point_label": "negative",
            },
        ]
    }

    prompt_items = read_interactive_prompt_items(payload)

    assert len(prompt_items) == 2
    assert prompt_items[0].prompt_kind == "box"
    assert prompt_items[0].bbox_xyxy == (10.0, 20.0, 30.0, 40.0)
    assert prompt_items[1].prompt_kind == "point"
    assert prompt_items[1].point_xy == (15.0, 25.0)
    assert prompt_items[1].point_label == "negative"


def test_read_text_prompt_items_accepts_positive_and_negative_items() -> None:
    """验证 SAM3 semantic 文本提示支持 positive/negative 标记。"""

    prompt_items = read_text_prompt_items(
        {
            "items": [
                {
                    "prompt_id": "prompt-1",
                    "text": "person",
                    "display_name": "person",
                    "negative": False,
                },
                {
                    "prompt_id": "prompt-1",
                    "text": "background",
                    "display_name": "person",
                    "negative": True,
                    "language": "en",
                },
            ]
        }
    )

    assert len(prompt_items) == 2
    assert prompt_items[0].negative is False
    assert prompt_items[1].negative is True
    assert prompt_items[1].language == "en"


def test_merge_text_prompt_items_supports_positive_and_negative_groups() -> None:
    """验证 SAM3 semantic 文本提示会按 prompt_id 聚合正负文本。"""

    prompt_groups = merge_text_prompt_items(
        (
            SimpleNamespace(prompt_id="prompt-1", text="person", display_name="person", negative=False, language=None),
            SimpleNamespace(prompt_id="prompt-1", text="human", display_name="person", negative=False, language="en"),
            SimpleNamespace(prompt_id="prompt-1", text="background", display_name="person", negative=True, language="en"),
            SimpleNamespace(prompt_id="prompt-2", text="car", display_name="car", negative=False, language=None),
        )
    )

    assert len(prompt_groups) == 2
    assert prompt_groups[0].prompt_id == "prompt-1"
    assert prompt_groups[0].positive_texts == ("person", "human")
    assert prompt_groups[0].negative_texts == ("background",)
    assert prompt_groups[0].source_prompt_text == "person | human || !background"
    assert prompt_groups[1].prompt_id == "prompt-2"
    assert prompt_groups[1].positive_texts == ("car",)
    assert prompt_groups[1].negative_texts == ()


def test_read_text_prompt_items_rejects_empty_items() -> None:
    """验证 SAM3 semantic 文本提示会拒绝空 items。"""

    with pytest.raises(InvalidRequestError, match="prompts.items"):
        read_text_prompt_items({"items": []})


def test_read_interactive_prompt_items_accepts_polygon() -> None:
    """验证当前阶段 polygon prompt 会被规整成 rasterized mask。"""

    payload = {
        "items": [
            {
                "prompt_id": "polygon-1",
                "prompt_kind": "polygon",
                "display_name": "poly",
                "polygon_xy": [[4, 4], [28, 6], [24, 18], [8, 20]],
            }
        ]
    }

    prompt_items = read_interactive_prompt_items(
        payload,
        source_image_payload={"width": 32, "height": 24},
    )

    assert len(prompt_items) == 1
    assert prompt_items[0].prompt_kind == "polygon"
    assert prompt_items[0].polygon_xy == ((4.0, 4.0), (28.0, 6.0), (24.0, 18.0), (8.0, 20.0))
    assert prompt_items[0].prompt_mask is not None
    assert tuple(prompt_items[0].prompt_mask.shape) == (24, 32)
    assert int(prompt_items[0].prompt_mask.sum()) > 0


def test_read_interactive_prompt_items_accepts_mask() -> None:
    """验证当前阶段 mask prompt 会被规整为二值 prompt mask。"""

    image_registry = ExecutionImageRegistry()
    mask_payload = _build_test_mask_payload(image_registry=image_registry, width=16, height=12)
    request = WorkflowNodeExecutionRequest(
        node_id="node-sam3-mask-common",
        node_definition=SimpleNamespace(node_type_id="custom.sam3.interactive-segment"),
        parameters={},
        input_values={},
        execution_metadata={"execution_image_registry": image_registry},
    )

    payload = {
        "items": [
            {
                "prompt_id": "prompt-1",
                "prompt_kind": "mask",
                "mask_image": mask_payload,
            }
        ]
    }

    prompt_items = read_interactive_prompt_items(
        payload,
        request=request,
        source_image_payload={"width": 32, "height": 24},
    )

    assert len(prompt_items) == 1
    assert prompt_items[0].prompt_kind == "mask"
    assert prompt_items[0].prompt_mask is not None
    assert tuple(prompt_items[0].prompt_mask.shape) == (24, 32)
    assert int(prompt_items[0].prompt_mask.sum()) > 0


def _build_test_mask_payload(
    *,
    image_registry: ExecutionImageRegistry,
    width: int,
    height: int,
) -> dict[str, object]:
    """构造测试用 mask image payload。"""

    import io

    from PIL import Image, ImageDraw

    image = Image.new("L", (width, height), color=0)
    draw = ImageDraw.Draw(image)
    draw.rectangle((2, 2, width - 3, height - 3), fill=255)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    registered_image = image_registry.register_image_bytes(
        content=buffer.getvalue(),
        media_type="image/png",
        width=width,
        height=height,
        created_by_node_id="fixture-mask",
    )
    return build_memory_image_payload(
        image_handle=registered_image.image_handle,
        media_type="image/png",
        width=width,
        height=height,
    )
