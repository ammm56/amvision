"""SAM3 runtime_support 基础模块测试。"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path

import numpy as np
from PIL import Image
import torch

from backend.nodes.sam3_runtime_support import (
    Sam3InteractiveFrameContext,
    Sam3RegionItem,
    Sam3VideoTrackState,
    build_sam3_interactive_prompt_tensors,
    build_memory_prompt_mask,
    build_sam3_interactive_state_dict,
    load_sam3_checkpoint_branches,
    postprocess_sam3_interactive_masks,
    preprocess_sam3_image,
    update_track_state_from_region,
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
    prompt_mask: np.ndarray | None = None


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
    assert prepared_prompts.prompt_masks is None
    assert prepared_prompts.point_labels[0].tolist() == [2, 3]
    assert prepared_prompts.point_labels[1].tolist() == [0, -1]


def test_build_sam3_interactive_prompt_tensors_supports_polygon_mask_prompt() -> None:
    """验证 polygon prompt 会编码成 PromptEncoder 可消费的 dense mask。"""

    polygon_mask = np.zeros((32, 48), dtype=np.uint8)
    polygon_mask[8:24, 10:36] = 1
    prompt_items = (
        _PromptItem(
            prompt_id="poly-1",
            prompt_kind="polygon",
            display_name="polygon",
            prompt_mask=polygon_mask,
        ),
    )

    prepared_prompts = build_sam3_interactive_prompt_tensors(
        prompt_items,
        source_width=48,
        source_height=32,
        target_width=1008,
        target_height=1008,
        mask_prompt_width=288,
        mask_prompt_height=288,
    )

    assert prepared_prompts.point_coords is None
    assert prepared_prompts.point_labels is None
    assert prepared_prompts.prompt_masks is not None
    assert tuple(prepared_prompts.prompt_masks.shape) == (1, 1, 288, 288)
    assert float(prepared_prompts.prompt_masks.sum().item()) > 0.0


def test_build_sam3_interactive_prompt_tensors_supports_mask_prompt() -> None:
    """验证 mask prompt 也会编码成 PromptEncoder 可消费的 dense mask。"""

    prompt_mask = np.zeros((30, 40), dtype=np.uint8)
    prompt_mask[6:26, 8:32] = 1
    prompt_items = (
        _PromptItem(
            prompt_id="mask-1",
            prompt_kind="mask",
            display_name="mask",
            prompt_mask=prompt_mask,
        ),
    )

    prepared_prompts = build_sam3_interactive_prompt_tensors(
        prompt_items,
        source_width=40,
        source_height=30,
        target_width=1008,
        target_height=1008,
        mask_prompt_width=288,
        mask_prompt_height=288,
    )

    assert prepared_prompts.point_coords is None
    assert prepared_prompts.point_labels is None
    assert prepared_prompts.prompt_masks is not None
    assert tuple(prepared_prompts.prompt_masks.shape) == (1, 1, 288, 288)
    assert float(prepared_prompts.prompt_masks.sum().item()) > 0.0


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
    assert 0.0 <= region.score <= 1.0


def test_postprocess_sam3_interactive_masks_filters_small_components() -> None:
    """验证后处理会过滤掉面积过小的碎片连通域。"""

    mask_logits = torch.full((1, 1, 16, 16), fill_value=-2.0, dtype=torch.float32)
    mask_logits[0, 0, 4:8, 5:9] = 3.0
    mask_logits[0, 0, 0, 0] = 3.0
    prompt_items = (
        _PromptItem(
            prompt_id="box-1",
            prompt_kind="box",
            display_name="target-box",
            bbox_xyxy=(0.0, 0.0, 15.0, 15.0),
        ),
    )

    region_items = postprocess_sam3_interactive_masks(
        mask_logits,
        source_width=16,
        source_height=16,
        prompt_items=prompt_items,
        min_component_area=4,
        min_region_area=4,
    )

    assert len(region_items) == 1
    region = region_items[0]
    assert region.area == 16
    assert region.bbox_xyxy == (5.0, 4.0, 8.0, 7.0)


def test_sam3_video_memory_tracker_builds_prompt_from_state() -> None:
    """验证视频 memory tracker 会基于对象状态生成新的 prompt mask。"""

    frame_context = Sam3InteractiveFrameContext(
        prepared_image=preprocess_sam3_image(_build_test_png_bytes(width=64, height=32)),
        features={"image_embed": torch.ones((1, 8, 8, 8), dtype=torch.float32), "high_res_feats": [], "low_res_feature_map": torch.ones((1, 8, 8, 8), dtype=torch.float32)},
        low_res_feature_map=torch.ones((1, 8, 8, 8), dtype=torch.float32),
        mask_prompt_width=32,
        mask_prompt_height=32,
    )
    low_res_mask = torch.zeros((8, 8), dtype=torch.float32)
    low_res_mask[2:6, 2:6] = 1.0
    track_state = Sam3VideoTrackState(
        prompt_id="track-1",
        display_name="tracked",
        feature_prototype=torch.ones((8,), dtype=torch.float32),
        low_res_mask_history=[low_res_mask],
    )

    memory_prompt = build_memory_prompt_mask(
        frame_context=frame_context,
        track_state=track_state,
    )

    assert memory_prompt.history_length == 1
    assert memory_prompt.prototype_ready is True
    assert memory_prompt.prompt_mask.shape == (32, 64)
    assert int(memory_prompt.prompt_mask.sum()) > 0


def test_sam3_video_memory_tracker_updates_track_state_from_region() -> None:
    """验证视频 memory tracker 会用当前帧 region 更新状态。"""

    prepared_image = preprocess_sam3_image(_build_test_png_bytes(width=48, height=40))
    frame_context = Sam3InteractiveFrameContext(
        prepared_image=prepared_image,
        features={"image_embed": torch.ones((1, 8, 8, 8), dtype=torch.float32), "high_res_feats": [], "low_res_feature_map": torch.ones((1, 8, 8, 8), dtype=torch.float32)},
        low_res_feature_map=torch.ones((1, 8, 8, 8), dtype=torch.float32),
        mask_prompt_width=32,
        mask_prompt_height=32,
    )
    region_mask = np.zeros((40, 48), dtype=np.uint8)
    region_mask[10:28, 12:30] = 1
    region = Sam3RegionItem(
        region_id="region-1",
        score=0.92,
        class_id=0,
        class_name="tracked",
        bbox_xyxy=(12.0, 10.0, 29.0, 27.0),
        polygon_xy=((12.0, 10.0), (29.0, 10.0), (29.0, 27.0), (12.0, 27.0)),
        area=int(region_mask.sum()),
        prompt_id="track-1",
        mask_png_bytes=_encode_mask_png_for_test(region_mask),
        mask_width=48,
        mask_height=40,
    )
    track_state = Sam3VideoTrackState(prompt_id="track-1", display_name="tracked")

    update_track_state_from_region(
        track_state=track_state,
        frame_context=frame_context,
        region=region,
        frame_index=3,
    )

    assert track_state.feature_prototype is not None
    assert len(track_state.low_res_mask_history) == 1
    assert track_state.last_score == 0.92
    assert track_state.last_frame_index == 3


def test_sam3_video_memory_tracker_supports_large_displacement() -> None:
    """验证对象大位移时 memory prompt 会跟着特征相似区域迁移。"""

    prepared_image = preprocess_sam3_image(_build_test_png_bytes(width=64, height=64))
    feature_map = torch.zeros((1, 2, 8, 8), dtype=torch.float32)
    feature_map[:, 1, :, :] = 1.0
    feature_map[:, 0, 5:8, 5:8] = 4.0
    feature_map[:, 1, 5:8, 5:8] = 0.0
    track_state = Sam3VideoTrackState(
        prompt_id="track-shift",
        display_name="shifted-object",
        feature_prototype=torch.tensor([1.0, 0.0], dtype=torch.float32),
        low_res_mask_history=[],
    )
    frame_context = Sam3InteractiveFrameContext(
        prepared_image=prepared_image,
        features={"image_embed": feature_map, "high_res_feats": [], "low_res_feature_map": feature_map},
        low_res_feature_map=feature_map,
        mask_prompt_width=32,
        mask_prompt_height=32,
    )

    memory_prompt = build_memory_prompt_mask(
        frame_context=frame_context,
        track_state=track_state,
    )

    ys, xs = np.nonzero(memory_prompt.prompt_mask)
    assert len(xs) > 0
    assert float(xs.mean()) > 32.0
    assert float(ys.mean()) > 32.0


def _encode_mask_png_for_test(binary_mask: np.ndarray) -> bytes:
    """把测试二值 mask 编码成 PNG。"""

    buffer = io.BytesIO()
    Image.fromarray((binary_mask > 0).astype(np.uint8) * 255, mode="L").save(buffer, format="PNG")
    return buffer.getvalue()
