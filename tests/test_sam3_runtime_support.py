"""SAM3 runtime_support 基础模块测试。"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path

from PIL import Image
import torch

from backend.nodes.sam3_runtime_support import (
    build_sam3_interactive_prompt_tensors,
    build_sam3_interactive_state_dict,
    load_sam3_checkpoint_branches,
    postprocess_sam3_interactive_masks,
    preprocess_sam3_image,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
SAM3_CHECKPOINT_PATH = (
    REPO_ROOT
    / "data"
    / "files"
    / "models"
    / "pretrained"
    / "sam3"
    / "segmentation"
    / "l"
    / "default"
    / "checkpoints"
    / "sam3.pt"
)


@dataclass(frozen=True)
class _PromptItem:
    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None = None
    point_xy: tuple[float, float] | None = None
    point_label: str | None = None


def _build_test_png_bytes(width: int = 64, height: int = 32) -> bytes:
    image = Image.new("RGB", (width, height), color=(120, 140, 160))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_load_sam3_checkpoint_branches_and_build_interactive_state_dict() -> None:
    """验证 SAM3 checkpoint 可以拆分分支并映射 interactive state_dict。"""

    branches = load_sam3_checkpoint_branches(SAM3_CHECKPOINT_PATH)
    interactive_state_dict = build_sam3_interactive_state_dict(branches)

    assert len(branches.detector_state_dict) > 0
    assert len(branches.tracker_state_dict) > 0
    assert any(key.startswith("image_encoder.vision_backbone.") for key in interactive_state_dict)
    assert any(key.startswith("memory_attention.") for key in interactive_state_dict)
    assert any(key.startswith("memory_encoder.") for key in interactive_state_dict)
    assert any(key.startswith("sam_mask_decoder.") for key in interactive_state_dict)


def test_preprocess_sam3_image_resizes_to_1008_square() -> None:
    """验证 SAM3 图像预处理会固定到 1008x1008。"""

    prepared_image = preprocess_sam3_image(_build_test_png_bytes())

    assert tuple(prepared_image.image_tensor.shape) == (1, 3, 1008, 1008)
    assert prepared_image.original_width == 64
    assert prepared_image.original_height == 32
    assert prepared_image.target_width == 1008
    assert prepared_image.target_height == 1008


def test_build_sam3_interactive_prompt_tensors_supports_box_and_point() -> None:
    """验证第一阶段 box/point prompt 会转换成 tracker 需要的点坐标与标签。"""

    prompt_items = (
        _PromptItem(
            prompt_id="box-1",
            prompt_kind="box",
            display_name="box",
            bbox_xyxy=(10.0, 20.0, 30.0, 40.0),
        ),
        _PromptItem(
            prompt_id="point-1",
            prompt_kind="point",
            display_name="point",
            point_xy=(5.0, 8.0),
            point_label="negative",
        ),
    )

    prepared_prompts = build_sam3_interactive_prompt_tensors(
        prompt_items,
        source_width=100,
        source_height=50,
        target_width=1008,
        target_height=1008,
    )

    assert tuple(prepared_prompts.point_coords.shape) == (2, 2, 2)
    assert tuple(prepared_prompts.point_labels.shape) == (2, 2)
    assert prepared_prompts.point_labels[0].tolist() == [2, 3]
    assert prepared_prompts.point_labels[1].tolist() == [0, -1]


def test_postprocess_sam3_interactive_masks_builds_regions() -> None:
    """验证 mask logits 可以规整成 regions.v1 所需的 region 条目。"""

    mask_logits = torch.full((1, 1, 16, 16), fill_value=-1.0, dtype=torch.float32)
    mask_logits[0, 0, 4:12, 5:13] = 2.0
    prompt_items = (
        _PromptItem(
            prompt_id="box-1",
            prompt_kind="box",
            display_name="target-box",
            bbox_xyxy=(4.0, 4.0, 12.0, 12.0),
        ),
    )

    region_items = postprocess_sam3_interactive_masks(
        mask_logits,
        source_width=64,
        source_height=64,
        prompt_items=prompt_items,
    )

    assert len(region_items) == 1
    region = region_items[0]
    assert region.prompt_id == "box-1"
    assert region.class_name == "target-box"
    assert region.area > 0
    assert region.mask_width == 64
    assert region.mask_height == 64
    assert region.mask_png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
