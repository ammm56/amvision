"""RF-DETR core 验收工具测试。"""

from __future__ import annotations

import pytest
import torch

from backend.service.application.models.validation.model_core_validation import (
    analyze_state_dict_coverage,
    build_model_core_snapshot,
)
from backend.service.application.models.rfdetr_core.detection import build_rfdetr_model
from backend.service.application.models.rfdetr_core.factory import (
    align_rfdetr_full_core_input_size,
    build_rfdetr_full_core_config,
    build_rfdetr_full_core_namespace,
    is_rfdetr_full_core_input_size_aligned,
    normalize_rfdetr_full_core_scale,
    resolve_rfdetr_full_core_default_input_size,
    resolve_rfdetr_full_core_input_divisor,
)
from backend.service.application.models.rfdetr_core.segmentation import (
    build_rfdetr_segmentation_model,
)
from backend.service.application.models.rfdetr_core.models.weights import (
    _validate_warm_start_partial_load,
    analyze_rfdetr_checkpoint_coverage,
    load_rfdetr_checkpoint_state_dict,
    load_rfdetr_deployment_weights,
)
from backend.service.domain.models.model_task_types import (
    DETECTION_TASK_TYPE,
    SEGMENTATION_TASK_TYPE,
)


def test_rfdetr_full_core_namespace_disables_implicit_pretrain_loading() -> None:
    """验证 RF-DETR full core builder 默认不触发隐式 DINOv2 权重加载。"""

    namespace = build_rfdetr_full_core_namespace(
        task_type=DETECTION_TASK_TYPE,
        model_scale="nano",
        num_classes=3,
    )

    assert namespace.pretrain_weights is None
    assert namespace.force_no_pretrain is True
    assert namespace.num_classes == 3
    assert namespace.segmentation_head is False


def test_rfdetr_full_core_segmentation_config_uses_segmentation_head() -> None:
    """验证 RF-DETR segmentation full core 会解析到 segmentation 配置。"""

    config = build_rfdetr_full_core_config(
        task_type=SEGMENTATION_TASK_TYPE,
        model_scale="x",
        num_classes=3,
    )

    assert config.segmentation_head is True
    assert config.num_classes == 3
    assert config.pretrain_weights is None


def test_rfdetr_full_core_input_divisor_matches_backbone_config() -> None:
    """验证 RF-DETR full core 导出输入尺寸倍数来自对应配置。"""

    assert (
        resolve_rfdetr_full_core_input_divisor(
            task_type=DETECTION_TASK_TYPE,
            model_scale="nano",
        )
        == 32
    )
    assert (
        resolve_rfdetr_full_core_input_divisor(
            task_type=SEGMENTATION_TASK_TYPE,
            model_scale="nano",
        )
        == 12
    )


@pytest.mark.parametrize(
    ("task_type", "model_scale", "expected_size"),
    (
        (DETECTION_TASK_TYPE, "nano", (384, 384)),
        (DETECTION_TASK_TYPE, "s", (512, 512)),
        (DETECTION_TASK_TYPE, "m", (576, 576)),
        (DETECTION_TASK_TYPE, "l", (704, 704)),
        (SEGMENTATION_TASK_TYPE, "nano", (312, 312)),
        (SEGMENTATION_TASK_TYPE, "s", (384, 384)),
        (SEGMENTATION_TASK_TYPE, "m", (432, 432)),
        (SEGMENTATION_TASK_TYPE, "l", (504, 504)),
        (SEGMENTATION_TASK_TYPE, "x", (624, 624)),
    ),
)
def test_rfdetr_full_core_default_input_size_matches_scale_resolution(
    task_type: str,
    model_scale: str,
    expected_size: tuple[int, int],
) -> None:
    """每个公开 scale 默认使用自身的原生 resolution。"""

    assert resolve_rfdetr_full_core_default_input_size(
        task_type=task_type,
        model_scale=model_scale,
    ) == expected_size


@pytest.mark.parametrize(
    ("task_type", "model_scale", "input_size", "expected_size"),
    (
        (DETECTION_TASK_TYPE, "nano", (640, 640), (640, 640)),
        (DETECTION_TASK_TYPE, "base", (640, 640), (672, 672)),
        (SEGMENTATION_TASK_TYPE, "nano", (64, 64), (72, 72)),
        (SEGMENTATION_TASK_TYPE, "m", (640, 640), (648, 648)),
    ),
)
def test_rfdetr_full_core_input_size_alignment(
    task_type: str,
    model_scale: str,
    input_size: tuple[int, int],
    expected_size: tuple[int, int],
) -> None:
    """验证 RF-DETR full core 输入尺寸会按 patch_size * num_windows 上取整。"""

    aligned_size = align_rfdetr_full_core_input_size(
        task_type=task_type,
        model_scale=model_scale,
        input_size=input_size,
    )

    assert aligned_size == expected_size
    assert is_rfdetr_full_core_input_size_aligned(
        task_type=task_type,
        model_scale=model_scale,
        input_size=aligned_size,
    )


@pytest.mark.parametrize(
    ("raw_scale", "expected_scale"),
    (
        ("n", "nano"),
        ("small", "s"),
        ("medium", "m"),
        ("xl", "x"),
        ("xxlarge", "xxl"),
    ),
)
def test_rfdetr_full_core_scale_aliases(raw_scale: str, expected_scale: str) -> None:
    """验证 RF-DETR full core scale 别名会先统一归一化。"""

    assert normalize_rfdetr_full_core_scale(raw_scale) == expected_scale


@pytest.mark.parametrize(
    ("task_type", "builder", "expected_extra_keys", "expects_hidden_states"),
    (
        (DETECTION_TASK_TYPE, build_rfdetr_model, ("aux_outputs", "enc_outputs"), False),
        (SEGMENTATION_TASK_TYPE, build_rfdetr_segmentation_model, ("pred_masks",), False),
    ),
)
def test_rfdetr_core_snapshot_records_forward_output_shapes(
    task_type: str,
    builder,
    expected_extra_keys: tuple[str, ...],
    expects_hidden_states: bool,
) -> None:
    """验证 RF-DETR detection/segmentation 可以生成结构和输出形状快照。"""

    model = builder(model_scale="nano", num_classes=3)

    example_input_size = 72 if task_type == SEGMENTATION_TASK_TYPE else 64
    snapshot = build_model_core_snapshot(
        model=model,
        model_type="rfdetr",
        task_type=task_type,
        model_scale="nano",
        num_classes=3,
        example_input=torch.randn(1, 3, example_input_size, example_input_size),
    )

    assert snapshot.model_type == "rfdetr"
    assert snapshot.task_type == task_type
    assert snapshot.parameters.total_parameter_count > 0
    assert snapshot.parameters.trainable_parameter_count == snapshot.parameters.total_parameter_count
    assert snapshot.parameters.state_dict_key_count == len(model.state_dict())
    assert snapshot.parameters.leaf_module_counts["Linear"] > 0
    assert snapshot.output_summary is not None
    assert snapshot.output_summary["kind"] == "dict"

    output_items = snapshot.output_summary["items"]
    expected_query_count = 100 if task_type == SEGMENTATION_TASK_TYPE else 300
    assert output_items["pred_logits"] == {
        "kind": "tensor",
        "shape": (1, expected_query_count, 4),
        "dtype": "torch.float32",
    }
    assert output_items["pred_boxes"] == {
        "kind": "tensor",
        "shape": (1, expected_query_count, 4),
        "dtype": "torch.float32",
    }
    if expects_hidden_states:
        assert output_items["hs"]["kind"] == "list"
        assert output_items["hs"]["items"][0] == {
            "kind": "tensor",
            "shape": (1, expected_query_count, 256),
            "dtype": "torch.float32",
        }
    else:
        assert "hs" not in output_items
    for key in expected_extra_keys:
        assert key in output_items


@pytest.mark.parametrize(
    ("task_type", "builder"),
    (
        (DETECTION_TASK_TYPE, build_rfdetr_model),
        (SEGMENTATION_TASK_TYPE, build_rfdetr_segmentation_model),
    ),
)
def test_rfdetr_state_dict_coverage_accepts_project_state_dict(task_type: str, builder) -> None:
    """验证 RF-DETR 项目内 detection/segmentation state_dict 可以完整覆盖。"""

    model = builder(model_scale="nano", num_classes=3)

    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=dict(model.state_dict()),
    )

    assert coverage.model_key_count == len(model.state_dict())
    assert coverage.source_key_count == len(model.state_dict())
    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0
    assert coverage.missing_keys == ()
    assert coverage.unexpected_keys == ()
    assert coverage.shape_mismatch_keys == ()


def test_rfdetr_state_dict_coverage_strips_outer_checkpoint_prefixes() -> None:
    """验证 RF-DETR checkpoint 外层 model/module 前缀不会影响覆盖率判断。"""

    model = build_rfdetr_model(model_scale="nano", num_classes=3)
    prefixed_state_dict = {
        f"module.model.{key}": value for key, value in model.state_dict().items()
    }

    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=prefixed_state_dict,
    )

    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0
    assert coverage.missing_keys == ()
    assert coverage.unexpected_keys == ()


def test_rfdetr_state_dict_coverage_reports_shape_mismatch() -> None:
    """验证 RF-DETR 权重 shape 不一致时会给出明确覆盖率结果。"""

    model = build_rfdetr_segmentation_model(model_scale="nano", num_classes=3)
    source_state_dict = dict(model.state_dict())
    mismatch_key = next(iter(source_state_dict))
    source_state_dict[mismatch_key] = torch.zeros(1)

    coverage = analyze_state_dict_coverage(
        model=model,
        source_state_dict=source_state_dict,
    )

    assert coverage.shape_mismatch_keys == (mismatch_key,)
    assert mismatch_key not in coverage.missing_keys
    assert coverage.loadable_key_count == coverage.model_key_count - 1
    assert coverage.loadable_ratio < 1.0


def test_rfdetr_local_checkpoint_coverage_accepts_model_payload(tmp_path) -> None:
    """验证 RF-DETR 本地 checkpoint 的 model payload 可以生成完整覆盖率。"""

    model = build_rfdetr_model(model_scale="nano", num_classes=3)
    checkpoint_path = tmp_path / "rfdetr-model.pth"
    torch.save(
        {
            "model": model.state_dict(),
            "args": {
                "num_queries": model.num_queries,
                "group_detr": model.group_detr,
                "class_names": ["defect", "part"],
            },
        },
        checkpoint_path,
    )

    coverage = analyze_rfdetr_checkpoint_coverage(
        model=model,
        checkpoint_path=checkpoint_path,
    )

    assert coverage.model_key_count == len(model.state_dict())
    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0
    assert coverage.missing_keys == ()
    assert coverage.unexpected_keys == ()


def test_rfdetr_local_checkpoint_coverage_normalizes_lightning_payload(tmp_path) -> None:
    """验证 RF-DETR Lightning checkpoint 会剥离 model 和 _orig_mod 前缀。"""

    model = build_rfdetr_model(model_scale="nano", num_classes=3)
    checkpoint_path = tmp_path / "rfdetr-lightning.ckpt"
    prefixed_state_dict = {
        f"model._orig_mod.{key}": value for key, value in model.state_dict().items()
    }
    torch.save({"state_dict": prefixed_state_dict}, checkpoint_path)

    state_dict = load_rfdetr_checkpoint_state_dict(checkpoint_path)
    coverage = analyze_rfdetr_checkpoint_coverage(
        model=model,
        checkpoint_path=checkpoint_path,
    )

    assert set(state_dict) == set(model.state_dict())
    assert coverage.loadable_key_count == coverage.model_key_count
    assert coverage.loadable_ratio == 1.0


def test_rfdetr_deployment_loader_prefers_platform_model_payload(tmp_path) -> None:
    """平台 hybrid checkpoint 的部署链必须读取 model，而不是 resume state_dict。"""

    model = torch.nn.Linear(3, 2)
    deployment_state = {
        key: torch.full_like(value, 2.0) for key, value in model.state_dict().items()
    }
    resume_state = {
        f"model.{key}": torch.full_like(value, 1.0)
        for key, value in model.state_dict().items()
    }
    checkpoint_path = tmp_path / "platform-best.pth"
    torch.save(
        {
            "model": deployment_state,
            "state_dict": resume_state,
            "optimizer_states": [{"state": {}, "param_groups": []}],
            "epoch": 1,
        },
        checkpoint_path,
    )

    report = load_rfdetr_deployment_weights(
        model=model,
        checkpoint_path=checkpoint_path,
    )

    assert report.source_name == "model"
    assert report.key_coverage == pytest.approx(1.0)
    assert report.numel_coverage == pytest.approx(1.0)
    assert all(
        torch.equal(value, deployment_state[key])
        for key, value in model.state_dict().items()
    )


def test_rfdetr_deployment_loader_accepts_legacy_model_state_dict(tmp_path) -> None:
    """旧部署产物的 model_state_dict 仍可严格加载，但不影响 resume 策略。"""

    source_model = torch.nn.Linear(3, 2)
    target_model = torch.nn.Linear(3, 2)
    checkpoint_path = tmp_path / "legacy-deploy.pth"
    torch.save({"model_state_dict": source_model.state_dict()}, checkpoint_path)

    report = load_rfdetr_deployment_weights(
        model=target_model,
        checkpoint_path=checkpoint_path,
    )

    assert report.key_coverage == pytest.approx(1.0)
    assert report.source_name == "model_state_dict"
    assert all(
        torch.equal(value, source_model.state_dict()[key])
        for key, value in target_model.state_dict().items()
    )


def test_rfdetr_warm_start_reports_allowed_head_and_query_differences() -> None:
    """warm-start 只可忽略明确列出的 head/query 差异。"""

    report = _validate_warm_start_partial_load(
        type(
            "IncompatibleKeys",
            (),
            {
                "missing_keys": ["class_embed.weight", "refpoint_embed.weight"],
                "unexpected_keys": ["transformer.enc_out_bbox_embed.0.weight"],
            },
        )(),
        "warm-start.pth",
    )

    assert report.allowed_missing_keys == (
        "class_embed.weight",
        "refpoint_embed.weight",
    )
    assert report.allowed_unexpected_keys == (
        "transformer.enc_out_bbox_embed.0.weight",
    )


def test_rfdetr_warm_start_rejects_non_head_parameter_differences() -> None:
    """backbone 等非白名单差异不能只告警后继续训练。"""

    incompatible = type(
        "IncompatibleKeys",
        (),
        {
            "missing_keys": ["backbone.encoder.weight"],
            "unexpected_keys": ["projector.layers.0.weight"],
        },
    )()

    with pytest.raises(ValueError, match="白名单之外"):
        _validate_warm_start_partial_load(incompatible, "warm-start.pth")


@pytest.mark.parametrize("fault_kind", ("missing", "unexpected", "shape"))
def test_rfdetr_deployment_loader_rejects_incomplete_weights(
    tmp_path,
    fault_kind: str,
) -> None:
    """部署权重存在缺键、多键或 shape 不一致时必须在写入模型前失败。"""

    model = torch.nn.Linear(3, 2)
    original_state = {
        key: value.detach().clone() for key, value in model.state_dict().items()
    }
    source_state = {
        key: torch.full_like(value, 4.0) for key, value in original_state.items()
    }
    if fault_kind == "missing":
        source_state.pop("bias")
    elif fault_kind == "unexpected":
        source_state["unknown"] = torch.ones(1)
    else:
        source_state["weight"] = torch.ones(1)
    checkpoint_path = tmp_path / f"invalid-{fault_kind}.pth"
    torch.save({"model": source_state}, checkpoint_path)

    with pytest.raises(ValueError, match="不完全匹配"):
        load_rfdetr_deployment_weights(
            model=model,
            checkpoint_path=checkpoint_path,
        )

    assert all(
        torch.equal(value, original_state[key])
        for key, value in model.state_dict().items()
    )
