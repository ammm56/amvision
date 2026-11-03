"""三种边界方法的真实内核组合，不替代节点/发布准入验收。"""

import numpy as np
import pytest

from backend.contracts.workflows.boundary3d import ExtractBoundaryParameters
from backend.contracts.workflows.geometry3d import PlaneGeometry
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.extract_boundary import (
    extract_boundary_array,
)
from tests.test_metrology3d_boundary_contracts import evaluation


def region(*, center=(0, 0, 0), size=(100, 100, 100)):
    """完全明确的测试选择区，不从候选序号生成。"""
    return dict(
        roi_id="window",
        rois=[
            dict(
                roi_id="window",
                frame_id="fixture",
                length_unit="mm",
                kind="box",
                geometry=dict(center=center, rotation=np.eye(3).tolist(), size=size),
            )
        ],
    )


def extract_parameters(**changes):
    """当前参数只用于解析测试，不进入生产 Catalog。"""
    return ExtractBoundaryParameters(
        **{
            **dict(
                feature_id="boundary",
                evaluation=evaluation(),
                region=region(),
                surface=dict(
                    alpha_radius=0.8,
                    max_edge_length=1.5,
                    max_normal_step=2,
                    min_projected_area=0.001,
                ),
                method=dict(kind="projection"),
                targets=[
                    dict(
                        segment_id="perimeter",
                        region=region(),
                        closed=True,
                        role="outer",
                    )
                ],
                quality_policy=dict(
                    policy_id="test",
                    policy_version=1,
                    rules=[
                        dict(item_id="support_count", unit="1", lower=2),
                        dict(item_id="length", unit="mm", lower=0.1),
                    ],
                ),
            ),
            **changes,
        }
    )


def extract(points, parameters=None, **changes):
    """完整局部数组输入，测试预算显式固定。"""
    opts = dict(max_working_bytes=10_000_000, cancel=lambda: None)
    opts.update(changes)
    return extract_boundary_array(
        np.asarray(points), parameters or extract_parameters(), **opts
    )


def test_projection_keeps_actual_positions_precision_and_parent_rows():
    """投影只用于拓扑，不把实测 Z 坐标改成评价平面。"""
    original = np.array(
        [(x, y, 0.25 * x) for x in range(4) for y in range(4)], dtype=np.float32
    )
    points = original[np.random.default_rng(9).permutation(len(original))]
    snapshot = points.tobytes()
    result = extract(points)
    assert result.reason is None and result.positions.dtype == np.dtype("float32")
    np.testing.assert_array_equal(result.positions, points[result.source_rows])
    assert set(map(tuple, result.positions)) == {
        tuple(p) for p in original if p[0] in (0, 3) or p[1] in (0, 3)
    }
    assert (
        len(result.source_rows) == 12
        and result.source_edges is None
        and points.tobytes() == snapshot
    )


@pytest.mark.parametrize("method_kind", ["section", "contour"])
@pytest.mark.parametrize("sign", [1, -1])
def test_section_and_contour_map_real_parent_edges_faces_and_weights(method_kind, sign):
    """独立斜面 z=x，截面 x=0.5；法向反转不丢线。"""
    points = np.array([(x, y, x) for x in range(3) for y in range(3)], dtype=float)
    method = dict(
        kind="section", origin=[0, 0, 0.5], normal=[0, 0, sign], numeric_tolerance=1e-10
    )
    extra = {}
    if method_kind == "contour":
        method = dict(
            kind="contour",
            reference_feature_id="datum",
            positive_normal=[0, 0, sign],
            min_orientation_cosine=0.1,
            height=0.5 * sign,
            numeric_tolerance=1e-10,
        )
        extra["contour_plane"] = PlaneGeometry(normal=[0, 0, 1], offset=0)
    params = extract_parameters(
        method=method,
        targets=[
            dict(segment_id="section", region=region(), closed=False, role="open")
        ],
    )
    result = extract(points, params, **extra)
    assert result.reason is None, result
    np.testing.assert_allclose(result.positions[:, [0, 2]], 0.5, atol=1e-12)
    np.testing.assert_allclose(
        [result.positions[:, 1].min(), result.positions[:, 1].max()], [0, 2], atol=1e-12
    )
    assert result.source_rows is None and result.source_edges.shape == (
        len(result.positions),
        2,
    )
    reconstructed = (points[result.source_edges] * result.weights[..., None]).sum(
        axis=1
    )
    np.testing.assert_allclose(result.positions, reconstructed, atol=1e-12)
    for row, (a, b) in enumerate(result.source_edges):
        faces = result.source_faces[
            result.face_offsets[row] : result.face_offsets[row + 1]
        ]
        assert len(faces) and all(a in face and b in face for face in faces)


def test_ambiguous_targets_do_not_pick_first_or_bind_candidate_order():
    """两块支持匹配同一区域时无效，明确选择后各自保留稳定 ID。"""
    points = np.array([(x, y, 0) for x in (0, 1, 5, 6) for y in (0, 1)], dtype=float)
    ambiguous = extract(points)
    assert (
        ambiguous.reason == "target_ambiguous"
        and ambiguous.failed_segment_id == "perimeter"
    )
    targets = [
        dict(
            segment_id=name,
            region=region(center=(center, 0.5, 0), size=(2, 2, 2)),
            closed=True,
            role="outer",
        )
        for name, center in (("left", 0.5), ("right", 5.5))
    ]
    expected = None
    for seed in range(4):
        shuffled = points[np.random.default_rng(seed).permutation(len(points))]
        result = extract(shuffled, extract_parameters(targets=targets))
        assert result.reason is None
        actual = {
            seg.segment_id: frozenset(
                map(tuple, result.positions[seg.start : seg.start + seg.count])
            )
            for seg in result.topology.segments
        }
        expected = expected or actual
        assert actual == expected
    targets[1]["region"] = targets[0]["region"]
    assert (
        extract(points, extract_parameters(targets=targets)).reason == "target_conflict"
    )


def test_coplanar_region_and_missing_target_have_no_partial_geometry():
    """整片共面不会变成边界外框，丢失目标不返回剩余候选假成功。"""
    points = np.array([(x, y, 0) for x in (0, 1) for y in (0, 1)], dtype=float)
    method = dict(
        kind="section", origin=[0, 0, 0], normal=[0, 0, 1], numeric_tolerance=1e-10
    )
    result = extract(points, extract_parameters(method=method))
    assert result.reason == "coplanar_region" and result.positions is None
    result = extract(
        points,
        extract_parameters(
            targets=[
                dict(
                    segment_id="absent",
                    region=region(center=(50, 50, 50), size=(1, 1, 1)),
                    closed=True,
                    role="unknown",
                )
            ]
        ),
    )
    assert result.reason == "target_not_found" and result.topology is None
    assert result.failed_segment_id == "absent"


def test_extraction_budget_and_reference_plane_are_strict():
    """没有已确认基准不能偷偷把源 XY 当等高基准。"""
    points = np.array([[0, 0, 0], [1, 0, 1], [0, 1, 0]], dtype=float)
    with pytest.raises(InvalidRequestError, match="预算"):
        extract(points, max_working_bytes=1)
    with pytest.raises(InvalidRequestError, match="基准"):
        extract(points, contour_plane=PlaneGeometry(normal=[0, 0, 1], offset=0))
