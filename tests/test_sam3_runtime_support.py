"""SAM3 custom node core 基础模块测试。"""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path

import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F

from backend.contracts.workflows.workflow_graph import WorkflowGraphNode
from backend.service.application.workflows.model_sessions import (
    WorkflowModelSessionLoadResult,
)
from custom_nodes.sam3_segment_nodes.backend.core import (
    Sam3VideoAttentionMemoryEntry,
    Sam3VideoAttentionTrackState,
    Sam3InteractiveFrameContext,
    Sam3RegionItem,
    Sam3VideoTrackState,
    build_memory_attention_prompt_mask,
    build_sam3_interactive_prompt_tensors,
    build_memory_prompt_mask,
    build_sam3_interactive_state_dict,
    load_sam3_checkpoint_branches,
    postprocess_sam3_interactive_masks,
    preprocess_sam3_image,
    update_attention_track_state_from_region,
    update_track_state_from_region,
)
from custom_nodes.sam3_segment_nodes.backend.payloads.types import (
    Sam3PretrainedVariant,
)
import custom_nodes.sam3_segment_nodes.backend.runtime.workflow_session as workflow_session_module
from custom_nodes.sam3_segment_nodes.backend.core.models import (
    interactive as interactive_model_module,
)
from custom_nodes.sam3_segment_nodes.backend.core.prompts.encoding import (
    PreparedSam3InteractivePrompts,
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
    / "default"
    / "checkpoints"
    / "sam3.pt"
)


def test_workflow_provider_reads_checkpoint_once_for_both_capabilities(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """验证同一 loader 的 Interactive/Semantic 模型复用一次 checkpoint 读取。"""

    checkpoint_path = tmp_path / "sam3.pt"
    checkpoint_path.write_bytes(b"checkpoint")
    variant = Sam3PretrainedVariant(
        model_asset_id="sam3-default",
        architecture_id="sam3",
        manifest_path=tmp_path / "manifest.json",
        checkpoint_path=checkpoint_path,
        model_name="sam3",
        model_version="0.1.3",
        task_type="segmentation",
        metadata={"checkpoint_sha256": "abc123"},
    )
    checkpoint_branches = object()
    checkpoint_loads: list[Path] = []
    built_sessions: list[tuple[str, object, str | None]] = []

    class _FakeRuntimeSession:
        def __init__(self, *, checkpoint_branches, checkpoint_sha256=None, **_kwargs):
            self.device_name = "cpu"
            self.runtime_torch_dtype = torch.float32
            built_sessions.append(
                (self.__class__.__name__, checkpoint_branches, checkpoint_sha256)
            )

        def close(self) -> None:
            return None

    class _FakeInteractiveSession(_FakeRuntimeSession):
        pass

    class _FakeSemanticSession(_FakeRuntimeSession):
        pass

    monkeypatch.setattr(
        workflow_session_module,
        "resolve_sam3_pretrained_variant",
        lambda **_kwargs: variant,
    )
    monkeypatch.setattr(
        workflow_session_module,
        "load_sam3_checkpoint_branches",
        lambda path: checkpoint_loads.append(path) or checkpoint_branches,
    )
    monkeypatch.setattr(
        workflow_session_module,
        "Sam3InteractiveRuntimeSession",
        _FakeInteractiveSession,
    )
    monkeypatch.setattr(
        workflow_session_module,
        "Sam3SemanticRuntimeSession",
        _FakeSemanticSession,
    )

    result = workflow_session_module.Sam3WorkflowModelSessionProvider().load(
        loader_node=WorkflowGraphNode(
            node_id="loader",
            node_type_id="custom.sam3.load-checkpoint",
            parameters={
                "model_asset_id": "sam3-default",
                "device": "cpu",
                "precision": "fp32",
            },
        ),
        consumer_node_type_ids=(
            "custom.sam3.interactive-segment",
            "custom.sam3.semantic-segment",
        ),
        runtime_context=object(),
    )

    assert checkpoint_loads == [checkpoint_path]
    assert len(built_sessions) == 2
    assert all(item[1] is checkpoint_branches for item in built_sessions)
    assert all(item[2] == "abc123" for item in built_sessions)
    assert result.checkpoint_sha256 == "abc123"


def test_workflow_provider_validation_exposes_warmup_timings() -> None:
    """验证 runtime 健康信息包含分能力和总 warmup 耗时。"""

    validation = workflow_session_module.Sam3WorkflowModelSessionProvider().validate(
        load_result=WorkflowModelSessionLoadResult(
            session=workflow_session_module.Sam3WorkflowModelSession(
                interactive=object(),
            ),
            model_family="sam3",
            model_asset_id="sam3-default",
            checkpoint_sha256="abc123",
            resolved_device="cpu",
            resolved_precision="fp32",
            capabilities=("interactive",),
        ),
        warmup_result={
            "interactive": {"project_native": True},
            "_warmup_timings_ms": {"interactive": 12.5, "total": 12.5},
        },
        consumer_node_type_ids=("custom.sam3.interactive-segment",),
        runtime_context=object(),
    )

    assert validation["warmup"] == "passed"
    assert validation["runtime_instance_count"] == 1
    assert validation["runtime_instances"] == ["interactive"]
    assert validation["warmup_timings_ms"] == {
        "interactive": 12.5,
        "total": 12.5,
    }


@dataclass(frozen=True)
class _PromptItem:
    prompt_id: str
    prompt_kind: str
    display_name: str
    bbox_xyxy: tuple[float, float, float, float] | None = None
    point_xy_items: tuple[tuple[float, float], ...] = ()
    point_labels: tuple[str, ...] = ()
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
    assert any(
        key.startswith("image_encoder.vision_backbone.")
        for key in interactive_state_dict
    )
    assert any(key.startswith("memory_attention.") for key in interactive_state_dict)
    assert any(key.startswith("memory_encoder.") for key in interactive_state_dict)
    assert any(key.startswith("sam_mask_decoder.") for key in interactive_state_dict)


def test_preprocess_sam3_image_resizes_to_1008_square() -> None:
    """验证 SAM3 图像预处理会固定到 1008x1008。"""

    prepared_image = preprocess_sam3_image(
        _build_test_png_bytes(),
        image_payload=None,
    )

    assert tuple(prepared_image.image_tensor.shape) == (1, 3, 1008, 1008)
    assert prepared_image.original_width == 64
    assert prepared_image.original_height == 32
    assert prepared_image.target_width == 1008
    assert prepared_image.target_height == 1008


def test_build_sam3_interactive_prompt_tensors_supports_box_and_point() -> None:
    """验证 Box 使用专用输入，Point 使用带正负标签的点输入。"""

    box_prompts = build_sam3_interactive_prompt_tensors(
        (
            _PromptItem(
                prompt_id="box-1",
                prompt_kind="box",
                display_name="box",
                bbox_xyxy=(10.0, 20.0, 30.0, 40.0),
            ),
        ),
        source_width=100,
        source_height=50,
        target_width=1008,
        target_height=1008,
    )
    point_prompts = build_sam3_interactive_prompt_tensors(
        (
            _PromptItem(
                prompt_id="point-1",
                prompt_kind="point",
                display_name="point",
                point_xy_items=((5.0, 8.0), (12.0, 16.0)),
                point_labels=("positive", "negative"),
            ),
        ),
        source_width=100,
        source_height=50,
        target_width=1008,
        target_height=1008,
    )

    assert box_prompts.point_coords is None
    assert box_prompts.point_labels is None
    assert box_prompts.boxes is not None
    assert tuple(box_prompts.boxes.shape) == (1, 2, 2)
    assert box_prompts.prompt_masks is None
    assert point_prompts.boxes is None
    assert tuple(point_prompts.point_coords.shape) == (1, 2, 2)
    assert tuple(point_prompts.point_labels.shape) == (1, 2)
    assert point_prompts.point_labels[0].tolist() == [1, 0]


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
    assert float(prepared_prompts.prompt_masks.max().item()) == 10.0
    assert float(prepared_prompts.prompt_masks.min().item()) == -10.0


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
    assert float(prepared_prompts.prompt_masks.max().item()) == 10.0
    assert float(prepared_prompts.prompt_masks.min().item()) == -10.0


def test_single_positive_point_enables_multimask_candidate_selection() -> None:
    """验证单个正点会启用多候选 Mask，而多点与负点组合保持单候选。"""

    single_positive = PreparedSam3InteractivePrompts(
        point_coords=torch.tensor([[[10.0, 20.0]]]),
        point_labels=torch.tensor([[1]]),
        boxes=None,
        prompt_masks=None,
        prompt_ids=("point-1",),
        prompt_kinds=("point",),
    )
    positive_and_negative = PreparedSam3InteractivePrompts(
        point_coords=torch.tensor([[[10.0, 20.0], [30.0, 40.0]]]),
        point_labels=torch.tensor([[1, 0]]),
        boxes=None,
        prompt_masks=None,
        prompt_ids=("point-1",),
        prompt_kinds=("point",),
    )

    assert (
        interactive_model_module._should_use_multimask_output(single_positive) is True
    )
    assert (
        interactive_model_module._should_use_multimask_output(positive_and_negative)
        is False
    )


def test_box_prompt_batch_size_uses_dedicated_boxes_tensor() -> None:
    """验证多 Box 不会退回 batch=1 并触发 repeat_image 不一致。"""

    box_prompts = PreparedSam3InteractivePrompts(
        point_coords=None,
        point_labels=None,
        boxes=torch.zeros((3, 2, 2), dtype=torch.float32),
        prompt_masks=None,
        prompt_ids=("box-1", "box-2", "box-3"),
        prompt_kinds=("box", "box", "box"),
    )

    assert interactive_model_module._read_prepared_prompt_batch_size(box_prompts) == 3


def test_interactive_box_prompt_uses_padding_point_and_suppresses_no_object() -> None:
    """验证 Box 路径与参考实现一致地补空点，并抑制无对象 Mask。"""

    captured: dict[str, object] = {}

    class _PromptEncoder(torch.nn.Module):
        def forward(self, *, points, boxes, masks):
            captured["points"] = points
            captured["boxes"] = boxes
            batch_size = int(boxes.shape[0])
            return (
                torch.zeros((batch_size, 3, 4), dtype=torch.float32),
                torch.zeros((batch_size, 4, 2, 2), dtype=torch.float32),
            )

        def get_dense_pe(self):
            return torch.zeros((1, 4, 2, 2), dtype=torch.float32)

    class _MaskDecoder(torch.nn.Module):
        def forward(self, **kwargs):
            batch_size = int(kwargs["sparse_prompt_embeddings"].shape[0])
            return (
                torch.full((batch_size, 1, 4, 4), 8.0),
                torch.full((batch_size, 1), 0.9),
                torch.zeros((batch_size, 1, 4)),
                torch.full((batch_size, 1), -0.1),
            )

    model = interactive_model_module.Sam3InteractiveImageModel.__new__(
        interactive_model_module.Sam3InteractiveImageModel
    )
    torch.nn.Module.__init__(model)
    model.sam_prompt_encoder = _PromptEncoder()
    model.sam_mask_decoder = _MaskDecoder()
    prompts = PreparedSam3InteractivePrompts(
        point_coords=None,
        point_labels=None,
        boxes=torch.tensor([[[2.0, 3.0], [12.0, 13.0]]]),
        prompt_masks=None,
        prompt_ids=("box-1",),
        prompt_kinds=("box",),
    )

    mask_logits, _iou_scores, final_scores = model.predict_mask_logits(
        features={
            "image_embed": torch.zeros((1, 4, 2, 2)),
            "high_res_feats": [],
        },
        prompts=prompts,
    )

    point_coords, point_labels = captured["points"]
    assert tuple(point_coords.shape) == (1, 1, 2)
    assert point_labels.tolist() == [[-1]]
    assert torch.all(mask_logits == -1024.0)
    assert final_scores.tolist() == [0.0]


def test_interactive_mask_prompt_uses_reference_prompt_resolution() -> None:
    """验证高分辨率精修 Mask 会按参考实现缩放到 PromptEncoder 输入尺寸。"""

    captured: dict[str, object] = {}

    class _PromptEncoder(torch.nn.Module):
        image_embedding_size = (72, 72)

        def forward(self, *, points, boxes, masks):
            captured["masks"] = masks
            return (
                torch.zeros((1, 2, 4), dtype=torch.float32),
                torch.zeros((1, 4, 2, 2), dtype=torch.float32),
            )

        def get_dense_pe(self):
            return torch.zeros((1, 4, 2, 2), dtype=torch.float32)

    class _MaskDecoder(torch.nn.Module):
        def forward(self, **kwargs):
            return (
                torch.ones((1, 1, 4, 4), dtype=torch.float32),
                torch.ones((1, 1), dtype=torch.float32),
                torch.zeros((1, 1, 4), dtype=torch.float32),
                torch.ones((1, 1), dtype=torch.float32),
            )

    model = interactive_model_module.Sam3InteractiveImageModel.__new__(
        interactive_model_module.Sam3InteractiveImageModel
    )
    torch.nn.Module.__init__(model)
    model.sam_prompt_encoder = _PromptEncoder()
    model.sam_mask_decoder = _MaskDecoder()
    prompts = PreparedSam3InteractivePrompts(
        point_coords=None,
        point_labels=None,
        boxes=None,
        prompt_masks=torch.ones((1, 1, 1008, 1008), dtype=torch.float32),
        prompt_ids=("mask-1",),
        prompt_kinds=("mask",),
    )

    model.predict_mask_logits(
        features={
            "image_embed": torch.zeros((1, 4, 2, 2)),
            "high_res_feats": [],
        },
        prompts=prompts,
    )

    assert tuple(captured["masks"].shape) == (1, 1, 288, 288)


def test_single_point_selects_highest_iou_candidate_without_reindexing_error() -> None:
    """验证单点多候选能选择非首个候选，不会对已收缩分数再次索引。"""

    class _PromptEncoder(torch.nn.Module):
        def forward(self, *, points, boxes, masks):
            return (
                torch.zeros((1, 2, 4), dtype=torch.float32),
                torch.zeros((1, 4, 2, 2), dtype=torch.float32),
            )

        def get_dense_pe(self):
            return torch.zeros((1, 4, 2, 2), dtype=torch.float32)

    class _MaskDecoder(torch.nn.Module):
        def forward(self, **kwargs):
            masks = torch.stack(
                [
                    torch.full((4, 4), 1.0),
                    torch.full((4, 4), 2.0),
                    torch.full((4, 4), 3.0),
                ],
            ).unsqueeze(0)
            return (
                masks,
                torch.tensor([[0.2, 0.95, 0.4]]),
                torch.zeros((1, 3, 4)),
                torch.tensor([[1.0]]),
            )

    model = interactive_model_module.Sam3InteractiveImageModel.__new__(
        interactive_model_module.Sam3InteractiveImageModel
    )
    torch.nn.Module.__init__(model)
    model.sam_prompt_encoder = _PromptEncoder()
    model.sam_mask_decoder = _MaskDecoder()
    prompts = PreparedSam3InteractivePrompts(
        point_coords=torch.tensor([[[5.0, 7.0]]]),
        point_labels=torch.tensor([[1]], dtype=torch.int32),
        boxes=None,
        prompt_masks=None,
        prompt_ids=("point-1",),
        prompt_kinds=("point",),
    )

    mask_logits, iou_scores, final_scores = model.predict_mask_logits(
        features={
            "image_embed": torch.zeros((1, 4, 2, 2)),
            "high_res_feats": [],
        },
        prompts=prompts,
    )

    assert torch.all(mask_logits == 2.0)
    assert iou_scores.tolist() == [[0.949999988079071]]
    assert final_scores.tolist() == [0.949999988079071]


def test_image_feature_identity_prefers_payload_content_sha256() -> None:
    """验证同图缓存优先使用 image-ref 的稳定内容摘要。"""

    identity, identity_source = (
        interactive_model_module._resolve_image_content_identity(
            image_bytes=b"encoded-image",
            image_payload={"content_sha256": "stable-sha"},
        )
    )
    fallback_identity, fallback_source = (
        interactive_model_module._resolve_image_content_identity(
            image_bytes=b"encoded-image",
            image_payload={},
        )
    )

    assert identity == "stable-sha"
    assert identity_source == "payload-content-sha256"
    assert fallback_identity != "stable-sha"
    assert fallback_source == "encoded-bytes-sha256"


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
        prepared_image=preprocess_sam3_image(
            _build_test_png_bytes(width=64, height=32),
            image_payload=None,
        ),
        features={
            "image_embed": torch.ones((1, 8, 8, 8), dtype=torch.float32),
            "high_res_feats": [],
            "low_res_feature_map": torch.ones((1, 8, 8, 8), dtype=torch.float32),
        },
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

    prepared_image = preprocess_sam3_image(
        _build_test_png_bytes(width=48, height=40),
        image_payload=None,
    )
    frame_context = Sam3InteractiveFrameContext(
        prepared_image=prepared_image,
        features={
            "image_embed": torch.ones((1, 8, 8, 8), dtype=torch.float32),
            "high_res_feats": [],
            "low_res_feature_map": torch.ones((1, 8, 8, 8), dtype=torch.float32),
        },
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
        mask_array=region_mask,
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

    prepared_image = preprocess_sam3_image(
        _build_test_png_bytes(width=64, height=64),
        image_payload=None,
    )
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
        features={
            "image_embed": feature_map,
            "high_res_feats": [],
            "low_res_feature_map": feature_map,
        },
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


def test_sam3_video_memory_attention_tracker_builds_prompt_from_state() -> None:
    """验证 memory-attention tracker 会基于对象 token memory 生成 prompt mask。"""

    frame_context = Sam3InteractiveFrameContext(
        prepared_image=preprocess_sam3_image(
            _build_test_png_bytes(width=64, height=32),
            image_payload=None,
        ),
        features={
            "image_embed": torch.ones((1, 8, 8, 8), dtype=torch.float32),
            "high_res_feats": [],
            "low_res_feature_map": torch.ones((1, 8, 8, 8), dtype=torch.float32),
        },
        low_res_feature_map=torch.ones((1, 8, 8, 8), dtype=torch.float32),
        mask_prompt_width=32,
        mask_prompt_height=32,
    )
    low_res_mask = torch.zeros((8, 8), dtype=torch.float32)
    low_res_mask[1:5, 2:6] = 1.0
    object_tokens = torch.ones((12, 8), dtype=torch.float32)
    track_state = Sam3VideoAttentionTrackState(
        prompt_id="track-attention-1",
        display_name="tracked",
    )
    track_state.memory_entries.append(
        video_memory_attention_entry := Sam3VideoAttentionMemoryEntry(
            object_tokens=object_tokens,
            low_res_mask=low_res_mask,
            score=0.88,
            frame_index=0,
        )
    )
    track_state.feature_prototype = torch.ones((8,), dtype=torch.float32)

    memory_prompt = build_memory_attention_prompt_mask(
        frame_context=frame_context,
        track_state=track_state,
    )

    assert video_memory_attention_entry.frame_index == 0
    assert memory_prompt.history_length == 1
    assert memory_prompt.memory_entry_count == 1
    assert memory_prompt.prototype_ready is True
    assert memory_prompt.prompt_mask.shape == (32, 64)
    assert int(memory_prompt.prompt_mask.sum()) > 0


def test_sam3_video_memory_attention_tracker_updates_track_state_from_region() -> None:
    """验证 memory-attention tracker 会写入对象 token memory。"""

    prepared_image = preprocess_sam3_image(
        _build_test_png_bytes(width=48, height=40),
        image_payload=None,
    )
    feature_map = torch.ones((1, 8, 8, 8), dtype=torch.float32)
    frame_context = Sam3InteractiveFrameContext(
        prepared_image=prepared_image,
        features={
            "image_embed": feature_map,
            "high_res_feats": [],
            "low_res_feature_map": feature_map,
        },
        low_res_feature_map=feature_map,
        mask_prompt_width=32,
        mask_prompt_height=32,
    )
    region_mask = np.zeros((40, 48), dtype=np.uint8)
    region_mask[10:28, 12:30] = 1
    region = Sam3RegionItem(
        region_id="region-att-1",
        score=0.93,
        class_id=0,
        class_name="tracked",
        bbox_xyxy=(12.0, 10.0, 29.0, 27.0),
        polygon_xy=((12.0, 10.0), (29.0, 10.0), (29.0, 27.0), (12.0, 27.0)),
        area=int(region_mask.sum()),
        prompt_id="track-attention-1",
        mask_array=region_mask,
        mask_png_bytes=_encode_mask_png_for_test(region_mask),
        mask_width=48,
        mask_height=40,
    )
    track_state = Sam3VideoAttentionTrackState(
        prompt_id="track-attention-1", display_name="tracked"
    )

    update_attention_track_state_from_region(
        track_state=track_state,
        frame_context=frame_context,
        region=region,
        frame_index=5,
    )

    assert track_state.feature_prototype is not None
    assert len(track_state.memory_entries) == 1
    assert track_state.memory_entries[0].object_tokens.ndim == 2
    assert track_state.last_score == 0.93
    assert track_state.last_frame_index == 5


def test_sam3_video_memory_attention_tracker_supports_large_displacement() -> None:
    """验证 memory-attention tracker 在大位移下仍能把 prompt 迁移到目标区域。"""

    prepared_image = preprocess_sam3_image(
        _build_test_png_bytes(width=64, height=64),
        image_payload=None,
    )
    feature_map = torch.zeros((1, 2, 8, 8), dtype=torch.float32)
    feature_map[:, 1, :, :] = 1.0
    feature_map[:, 0, 5:8, 5:8] = 4.0
    feature_map[:, 1, 5:8, 5:8] = 0.0
    track_state = Sam3VideoAttentionTrackState(
        prompt_id="track-attention-shift",
        display_name="shifted-object",
    )
    track_state.feature_prototype = torch.tensor([1.0, 0.0], dtype=torch.float32)
    track_state.memory_entries.append(
        Sam3VideoAttentionMemoryEntry(
            object_tokens=F.normalize(
                torch.tensor([[1.0, 0.0], [1.0, 0.0]], dtype=torch.float32), dim=1
            ),
            low_res_mask=torch.zeros((8, 8), dtype=torch.float32),
            score=0.9,
            frame_index=0,
        )
    )
    track_state.memory_entries[0].low_res_mask[5:8, 5:8] = 1.0
    frame_context = Sam3InteractiveFrameContext(
        prepared_image=prepared_image,
        features={
            "image_embed": feature_map,
            "high_res_feats": [],
            "low_res_feature_map": feature_map,
        },
        low_res_feature_map=feature_map,
        mask_prompt_width=32,
        mask_prompt_height=32,
    )

    memory_prompt = build_memory_attention_prompt_mask(
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
    Image.fromarray((binary_mask > 0).astype(np.uint8) * 255, mode="L").save(
        buffer, format="PNG"
    )
    return buffer.getvalue()
