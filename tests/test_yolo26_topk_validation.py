"""端到端 TopK 必须验证完整候选，不能以分数相等掩盖几何错误。"""

from __future__ import annotations

import numpy as np
import pytest

from backend.service.application.models.yolo26_core.export.topk_validation import (
    validate_topk_outputs,
)


def _candidates(*, anchors: int = 302, classes: int = 1, extras: int = 0) -> np.ndarray:
    """生成框唯一但分数严格相同的候选张量。"""
    raw = np.zeros((1, anchors, 4 + classes + extras), dtype=np.float32)
    raw[0, :, :4] = np.arange(anchors)[:, None] * 10 + [0, 0, 2, 2]
    raw[:, :, 4 : 4 + classes] = 0.003
    if extras:
        raw[:, :, 4 + classes :] = np.arange(anchors)[:, None] / 100
    return raw


def _rows(raw: np.ndarray, pairs: list[tuple[int, int]], classes: int) -> np.ndarray:
    """根据完整 anchor/class 对生成 processed 行。"""
    return np.array(
        [
            [
                [
                    *raw[0, anchor, :4],
                    raw[0, anchor, 4 + category],
                    category,
                    *raw[0, anchor, 4 + classes :],
                ]
                for anchor, category in pairs
            ]
        ],
        dtype=np.float32,
    )


def _compare(
    raw: np.ndarray,
    left: np.ndarray,
    right: np.ndarray,
    classes: int = 1,
    proto: bool = False,
) -> dict:
    """执行真实数值策略，并可附带 segmentation proto。"""
    suffix = [np.ones((1, 2, 8, 8), dtype=np.float32)] if proto else []
    return validate_topk_outputs(
        source_candidates=raw,
        target_candidates=raw.copy(),
        source_outputs=[left, *suffix],
        target_outputs=[right, *suffix],
        class_count=classes,
        build_precision="fp32",
        np_module=np,
    )


@pytest.mark.parametrize("extras", [0, 1, 6, 32])
def test_topk_accepts_different_tied_sets_with_all_fields_verified(extras: int) -> None:
    """同分候选集合不同也可合法，但框与所有附加字段必须来自真实候选。"""
    raw = _candidates(extras=extras)
    left = _rows(raw, [(a, 0) for a in range(300)], 1)
    right = _rows(raw, [(a, 0) for a in range(301, 1, -1)], 1)
    result = _compare(raw, left, right, proto=extras == 32)
    assert result["passed"] is True
    assert result["raw_row_allclose"] is False


@pytest.mark.parametrize(
    "column,value", [(0, 10000), (5, 0.5), (5, 1), (6, 10000), (0, float("nan"))]
)
def test_topk_rejects_corrupt_geometry_class_and_extra(
    column: int, value: float
) -> None:
    """框、类别、关键点或 mask 系数错误不能被相同分数放行。"""
    raw = _candidates(extras=6)
    left = _rows(raw, [(a, 0) for a in range(300)], 1)
    right = left.copy()
    right[0, 0, column] = value
    assert _compare(raw, left, right)["passed"] is False


def test_topk_rejects_duplicate_pair() -> None:
    """同一个 anchor/class 不得重复占用两个输出名额。"""
    raw = _candidates()
    left = _rows(raw, [(a, 0) for a in range(300)], 1)
    right = left.copy()
    right[0, 0] = right[0, 1]
    assert _compare(raw, left, right)["passed"] is False


def test_topk_allows_same_anchor_different_classes() -> None:
    """两阶段算法允许同一 anchor 的不同类别占用多个名额。"""
    raw = _candidates(anchors=4, classes=2)
    left = _rows(raw, [(0, 0), (0, 1), (1, 0), (1, 1)], 2)
    right = _rows(raw, [(2, 0), (2, 1), (3, 0), (3, 1)], 2)
    assert _compare(raw, left, right, classes=2)["passed"] is True


def test_topk_rejects_missing_high_score_candidate() -> None:
    """低分的合法框也不能替换明显更高分的候选。"""
    raw = _candidates()
    raw[0, :, 4] = np.linspace(0.9, 0.1, 302)
    left = _rows(raw, [(a, 0) for a in range(300)], 1)
    right = _rows(raw, [(a, 0) for a in [*range(299), 301]], 1)
    assert _compare(raw, left, right)["passed"] is False


def test_topk_rejects_proto_mismatch() -> None:
    """匹配 detection 行不能代替 segmentation proto 的数值比较。"""
    raw = _candidates(anchors=2, extras=32)
    rows = _rows(raw, [(0, 0), (1, 0)], 1)
    result = validate_topk_outputs(
        source_candidates=raw,
        target_candidates=raw,
        source_outputs=[rows, np.zeros((1, 32, 8, 8))],
        target_outputs=[rows, np.ones((1, 32, 8, 8))],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    assert result["passed"] is False


def test_topk_observation_bridges_cannot_accumulate_proto_tolerance() -> None:
    """两个交接阶段的容差不能叠加后放宽正式 proto 的跨后端比较。"""
    raw = _candidates(anchors=2, extras=32)
    rows = _rows(raw, [(0, 0), (1, 0)], 1)
    proto = np.ones((1, 32, 2, 2), dtype=np.float32)
    result = validate_topk_outputs(
        source_candidates=raw,
        target_candidates=raw,
        source_outputs=[rows, proto],
        target_outputs=[rows, proto * 1.003],
        source_observed_outputs=[rows, proto * 1.001],
        target_observed_outputs=[rows, proto * 1.002],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    assert result["candidate_validation"]["passed"] is True
    assert all(item["passed"] for item in result["public_observation_validation"])
    assert result["passed"] is False


def test_topk_checks_every_batch() -> None:
    """多个 batch 分别验证完整候选，不漏掉第二张图片的错误。"""
    raw = _candidates(anchors=4, classes=2, extras=6)
    rows = _rows(raw, [(0, 0), (0, 1), (1, 0), (1, 1)], 2)
    raw = np.concatenate([raw, raw], axis=0)
    rows = np.concatenate([rows, rows], axis=0)
    assert _compare(raw, rows, rows.copy(), classes=2)["passed"] is True
    broken = rows.copy()
    broken[1, 3, 6] = 10000
    assert _compare(raw, rows, broken, classes=2)["passed"] is False


def test_topk_accepts_near_tie_boundary_when_each_backend_selects_correctly() -> None:
    """微小数值差异可交换临界候选，但不得替换明显更高分的候选。"""
    source = _candidates()
    source[0, :299, 4] = 0.9
    source[0, 299:, 4] = [0.00300001, 0.003, 0.002]
    target = source.copy()
    target[0, 299:301, 4] = [0.003, 0.00300001]
    left = _rows(source, [(a, 0) for a in range(300)], 1)
    right = _rows(target, [(a, 0) for a in [*range(299), 300]], 1)
    arguments = dict(
        source_candidates=source,
        target_candidates=target,
        source_outputs=[left],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    result = validate_topk_outputs(**arguments, target_outputs=[right])
    assert result["passed"] is True
    assert 0 < result["candidate_score_max_abs_diff"] < 2e-8
    right = _rows(target, [(a, 0) for a in [*range(299), 301]], 1)
    assert validate_topk_outputs(**arguments, target_outputs=[right])["passed"] is False


def test_topk_rejects_invalid_unselected_probability() -> None:
    """没有被选中的非法概率也必须拒绝。"""
    raw = _candidates()
    raw[0, -1, 4] = -0.1
    rows = _rows(raw, [(a, 0) for a in range(300)], 1)
    assert _compare(raw, rows, rows)["passed"] is False


def test_topk_does_not_borrow_another_candidates_error_for_selection() -> None:
    """其他候选的跨后端误差不能放行本后端漏选更高分候选。"""
    source = _candidates()
    source[0, :299, 4] = 0.9
    source[0, 299:, 4] = [0.8005, 0.8004, 0.1]
    target = source.copy()
    target[0, 0, 4] = 0.9005
    result = validate_topk_outputs(
        source_candidates=source,
        target_candidates=target,
        source_outputs=[_rows(source, [(a, 0) for a in range(300)], 1)],
        target_outputs=[_rows(target, [(a, 0) for a in [*range(299), 300]], 1)],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    assert result["candidate_validation"]["passed"] is True
    assert result["passed"] is False


def test_topk_gather_cannot_change_geometry_within_model_tolerance() -> None:
    """同次执行的 Gather 不得借模型级容差修改原候选的坐标。"""
    raw = _candidates(anchors=2)
    rows = _rows(raw, [(0, 0), (1, 0)], 1)
    broken = rows.copy()
    broken[0, 1, 0] += 0.005
    assert _compare(raw, rows, broken)["passed"] is False


@pytest.mark.parametrize(
    "corrupt", ["geometry", "score", "class", "extra", "proto", "duplicate"]
)
def test_topk_valid_observation_does_not_hide_corrupt_public_output(
    corrupt: str,
) -> None:
    """候选观测完全正确时，正式产物的错误仍必须拒绝。"""
    raw = _candidates(anchors=4, extras=6)
    rows = _rows(raw, [(a, 0) for a in range(4)], 1)
    proto = np.ones((1, 2, 8, 8), dtype=np.float32)
    public = rows.copy()
    public_proto = proto.copy()
    if corrupt == "proto":
        public_proto *= 2
    elif corrupt == "duplicate":
        public[0, 0] = public[0, 1]
    else:
        public[0, 0, {"geometry": 0, "score": 4, "class": 5, "extra": 6}[corrupt]] += 1
    result = validate_topk_outputs(
        source_candidates=raw,
        target_candidates=raw,
        source_outputs=[rows, proto],
        target_outputs=[public, public_proto],
        target_observed_outputs=[rows, proto],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    assert all(item["passed"] for item in result["selection_validation"])
    assert result["passed"] is False


def test_topk_observation_bridge_accepts_only_complete_numeric_equivalence() -> None:
    """分开编译的正式结果允许完整实例数值容差，但明确记录其证据类别。"""
    raw = _candidates(anchors=2, extras=6)
    rows = _rows(raw, [(0, 0), (1, 0)], 1)
    public = rows.copy()
    public[0, 1, 0] += 0.005
    result = validate_topk_outputs(
        source_candidates=raw,
        target_candidates=raw,
        source_outputs=[rows],
        target_outputs=[public],
        target_observed_outputs=[rows],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    assert result["passed"] is True
    assert (
        result["public_observation_validation"][1]["method"]
        == "complete-output-equivalence"
    )


def test_topk_public_probability_cannot_exceed_one_within_tolerance() -> None:
    """跨观测图的数值容差也不能接受越界的公开概率。"""
    raw = _candidates(anchors=2)
    raw[:, :, 4] = 1
    rows = _rows(raw, [(0, 0), (1, 0)], 1)
    public = rows.copy()
    public[0, 0, 4] += 0.0001
    result = validate_topk_outputs(
        source_candidates=raw,
        target_candidates=raw,
        source_outputs=[rows],
        target_outputs=[public],
        target_observed_outputs=[rows],
        class_count=1,
        build_precision="fp32",
        np_module=np,
    )
    assert result["passed"] is False


@pytest.mark.parametrize("seed", range(10))
def test_topk_accepts_actual_core_selection_with_repeated_candidates(seed: int) -> None:
    """实际 core 的多类、重复坐标与大量同分组合不能被校验器误判。"""
    import torch
    from backend.service.application.models.yolo26_core.postprocess.export import (
        postprocess_yolo26_detection_export_tensor,
    )

    rng = np.random.default_rng(seed)
    raw = rng.integers(0, 4, size=(2, 302, 7)).astype(np.float32)
    raw[:, :, 4:] /= 4
    rows = postprocess_yolo26_detection_export_tensor(
        torch_module=torch,
        prediction=torch.from_numpy(raw),
        num_classes=3,
        max_detections=300,
    ).numpy()
    assert _compare(raw, rows, rows, classes=3)["passed"] is True


def test_topk_observation_preserves_public_graph_and_fails_closed() -> None:
    """观测只修改内存副本；丢失候选映射时不允许跳过验证。"""
    import onnx
    from backend.service.application.errors import ServiceConfigurationError
    from backend.service.application.models.yolo26_core.export.validation_graph import (
        CANDIDATE_TENSOR_NAME,
        TopkGraphContract,
        instrument_topk_graph,
        read_topk_contract,
        TOPK_METADATA_KEY,
    )
    import json

    h = onnx.helper
    graph = h.make_graph(
        [
            h.make_node("Identity", ["input"], [CANDIDATE_TENSOR_NAME]),
            h.make_node("Identity", [CANDIDATE_TENSOR_NAME], ["output"]),
        ],
        "observation",
        [h.make_tensor_value_info("input", onnx.TensorProto.FLOAT, [1, 2, 5])],
        [h.make_tensor_value_info("output", onnx.TensorProto.FLOAT, [1, 2, 5])],
    )
    model = h.make_model(graph)
    assert read_topk_contract(model) is None
    h.set_model_props(
        model,
        {TOPK_METADATA_KEY: json.dumps({"task_type": "detection", "class_count": 1})},
    )
    contract = read_topk_contract(model)
    assert contract is not None
    original = model.SerializeToString()
    observed = instrument_topk_graph(model, contract)
    assert [v.name for v in observed.graph.output] == ["output", CANDIDATE_TENSOR_NAME]
    assert model.SerializeToString() == original
    with pytest.raises(ServiceConfigurationError, match="丢失"):
        instrument_topk_graph(model, TopkGraphContract("detection", 1, "missing"))
    h.set_model_props(
        model, {TOPK_METADATA_KEY: '{"task_type": "pose", "class_count": 0}'}
    )
    with pytest.raises(ServiceConfigurationError, match="不合法"):
        read_topk_contract(model)
