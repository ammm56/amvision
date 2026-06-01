"""SAM3 公共资产解析与 prompt 规范化测试。"""

from __future__ import annotations

import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.sam3_segment_nodes.backend.nodes._common import (
    read_interactive_prompt_items,
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


@pytest.mark.parametrize("prompt_kind", ["polygon", "mask"])
def test_read_interactive_prompt_items_rejects_later_stage_prompt_kinds(prompt_kind: str) -> None:
    """验证第一阶段会明确拒绝 polygon 与 mask prompt。"""

    payload = {
        "items": [
            {
                "prompt_id": "prompt-1",
                "prompt_kind": prompt_kind,
                "polygon_xy": [[1, 2], [3, 4], [5, 6]],
            }
        ]
    }

    with pytest.raises(InvalidRequestError, match="第一阶段只支持 box 与 point prompt"):
        read_interactive_prompt_items(payload)
