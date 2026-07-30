"""SAM3.1 Multiplex bucket、位置编码与资源生命周期测试。"""

from __future__ import annotations

from types import SimpleNamespace

import torch
from torch import nn

from custom_nodes.sam3_segment_nodes.backend.core.checkpoint.loader import (
    Sam3CheckpointBranches,
    build_sam3_multiplex_propagation_state_dict,
)
from custom_nodes.sam3_segment_nodes.backend.core.models.shared_owner import (
    Sam3SharedModelOwner,
)
from custom_nodes.sam3_segment_nodes.backend.core.nn.common import (
    get_1d_sine_pe,
)
from custom_nodes.sam3_segment_nodes.backend.core.nn.multiplex_mask_decoder import (
    Sam3MultiplexMaskDecoder,
)
from custom_nodes.sam3_segment_nodes.backend.core.nn.multiplex_memory import (
    Sam3MultiplexMaskDownsampler,
)
from custom_nodes.sam3_segment_nodes.backend.core.nn.multiplex_transformer import (
    Sam3SimpleRoPEAttention,
)
from custom_nodes.sam3_segment_nodes.backend.core.state.multiplex import (
    build_sam3_multiplex_state,
)


def test_multiplex_state_round_trips_multiple_buckets() -> None:
    """验证超过 16 个对象时 mux/demux 不改变顺序或数据。"""

    object_ids = tuple(f"object-{index}" for index in range(19))
    state = build_sam3_multiplex_state(
        object_ids=object_ids,
        device=torch.device("cpu"),
        dtype=torch.float32,
    )
    source = torch.arange(19 * 3, dtype=torch.float32).reshape(19, 3)

    multiplexed = state.mux(source)
    restored = state.demux(multiplexed)

    assert tuple(multiplexed.shape) == (2, 16, 3)
    assert torch.equal(restored, source)
    assert int(state.get_valid_object_mask().sum()) == 19
    assert state.layout.assignments[1][3:] == (-1,) * 13


def test_multiplex_state_rejects_duplicate_object_ids() -> None:
    """验证重复对象 id 不会静默覆盖 bucket slot。"""

    try:
        build_sam3_multiplex_state(
            object_ids=("same", "same"),
            device=torch.device("cpu"),
            dtype=torch.float32,
        )
    except ValueError as error:
        assert "不能重复" in str(error)
    else:  # pragma: no cover - 防止错误路径静默通过
        raise AssertionError("重复 object id 应当被拒绝")


def test_sam3_temporal_sine_position_encoding_matches_reference_layout() -> None:
    """验证 object pointer 时序编码使用官方 sin-half/cos-half 排列。"""

    encoded = get_1d_sine_pe(
        torch.tensor([1.0], dtype=torch.float32),
        dim=8,
    )
    angular = torch.tensor(
        [[1.0, 1.0, 0.01, 0.01]],
        dtype=torch.float32,
    )
    expected = torch.cat((angular.sin(), angular.cos()), dim=-1)

    assert torch.allclose(encoded, expected, atol=1e-7, rtol=1e-7)


def test_multiplex_decoder_uses_three_checkpoint_candidates_only() -> None:
    """验证 propagation decoder 不创建未训练的 single-mask token。"""

    decoder = Sam3MultiplexMaskDecoder()

    assert decoder.num_mask_output_per_object == 3
    assert decoder.num_mask_tokens == 16 * 3
    assert decoder.dynamic_multimask_via_stability is False


def test_mask_downsampler_restores_runtime_dtype_after_interpolation() -> None:
    """验证 resize 的 FP32 计算不会污染 FP16/FP64 模型输入类型。"""

    downsampler = Sam3MultiplexMaskDownsampler(
        embed_dim=8,
        total_stride=2,
        interpol_size=(8, 8),
        multiplex_count=2,
        starting_out_channels=2,
        input_channel_multiplier=2,
    ).to(dtype=torch.float64)

    output = downsampler(torch.ones((1, 4, 4, 4), dtype=torch.float64))

    assert output.dtype == torch.float64


def test_multiplex_state_dict_selects_only_propagation_branch() -> None:
    """验证映射只接收 propagation neck、memory、pointer 和 bucket decoder。"""

    scalar = torch.ones(1)
    branches = Sam3CheckpointBranches(
        full_state_dict={},
        detector_state_dict={
            "detector.backbone.vision_backbone.trunk.patch_embed.proj.weight": scalar,
            "detector.backbone.vision_backbone.interactive_convs.0.conv_1x1.weight": scalar,
            "detector.backbone.vision_backbone.propagation_convs.0.conv_1x1.weight": scalar,
            "detector.language_backbone.encoder.weight": scalar,
        },
        tracker_state_dict={
            "tracker.model.transformer.memory_attention.norm1.weight": scalar,
            "tracker.model.maskmem_backbone.mask_downsampler.encoder.0.weight": scalar,
            "tracker.model.sam_mask_decoder.iou_token.weight": scalar,
            "tracker.model.interactive_sam_mask_decoder.iou_token.weight": scalar,
            "tracker.model.obj_ptr_proj.weight": scalar,
            "tracker.model.no_obj_ptr_linear.weight": scalar,
            "tracker.model.maskmem_tpos_enc": scalar,
        },
    )

    mapped = build_sam3_multiplex_propagation_state_dict(branches)

    assert (
        "image_encoder.vision_backbone.trunk.patch_embed.proj.weight"
        in mapped
    )
    assert (
        "image_encoder.vision_backbone.propagation_convs.0.conv_1x1.weight"
        in mapped
    )
    assert "transformer.memory_attention.norm1.weight" in mapped
    assert "maskmem_backbone.mask_downsampler.encoder.0.weight" in mapped
    assert "sam_mask_decoder.iou_token.weight" in mapped
    assert "obj_ptr_proj.weight" in mapped
    assert "no_obj_ptr_linear.weight" in mapped
    assert "maskmem_tpos_enc" in mapped
    assert not any("interactive_convs" in key for key in mapped)
    assert not any("interactive_sam_mask_decoder" in key for key in mapped)
    assert not any("language_backbone" in key for key in mapped)


def test_complex_rope_cache_is_not_cast_to_fp16() -> None:
    """验证模型精度迁移不会丢弃 complex RoPE 虚部。"""

    attention = Sam3SimpleRoPEAttention()
    original = attention._initial_freqs.clone()

    attention.to(dtype=torch.float16)

    assert attention._initial_freqs.dtype == torch.complex64
    assert torch.equal(attention._initial_freqs, original)


class _DummyCapabilityModel(nn.Module):
    """提供 SharedOwner 测试所需的最小视觉能力视图。"""

    def __init__(self, trunk: nn.Module, rotary: nn.Module) -> None:
        super().__init__()
        self.trunk = trunk
        self.rotary = rotary
        self.image_encoder = SimpleNamespace(
            vision_backbone=SimpleNamespace(trunk=trunk)
        )


def test_shared_owner_close_releases_feature_and_rotary_caches() -> None:
    """验证 owner close 同时释放图像特征和非 Parameter RoPE cache。"""

    trunk = nn.Linear(2, 2)
    rotary = Sam3SimpleRoPEAttention()
    interactive = _DummyCapabilityModel(trunk, rotary)
    propagation = _DummyCapabilityModel(trunk, rotary)
    owner = Sam3SharedModelOwner(
        interactive_model=interactive,
        multiplex_model=propagation,
    )
    owner.feature_cache._image_identity = "image"
    owner.feature_cache._trunk_feature = torch.ones(1)

    owner.close()

    assert owner.feature_cache.diagnostics()["has_value"] is False
    assert rotary._initial_freqs.device.type == "cpu"
