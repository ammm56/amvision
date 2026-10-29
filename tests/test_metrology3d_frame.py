"""坐标基准解析真值，覆盖两种原点和失败后不携旧矩阵。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d import (
    BuildFrameParameters,
    CropCloudParameters,
    RigidMatrix3d,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud


def frame_parameters(**changes):
    """测试显式门槛，不为配方提供默认值。"""
    return BuildFrameParameters(
        **{
            **dict(
                pose_id="datum",
                target_frame_id="part",
                primary_feature_id="primary",
                positive_z=[0, 0, 1],
                origin=dict(kind="anchor-projection", anchor=[1, 2, 20]),
                x_axis=dict(kind="direction", direction=[1, 0, 0]),
                quality_policy=dict(
                    policy_id="test-frame",
                    policy_version=1,
                    rules=[
                        dict(item_id=name, unit="1", lower=0.01)
                        for name in ("axis_sine", "x_alignment", "z_alignment")
                    ],
                ),
            ),
            **changes,
        }
    )


def datum_cloud():
    """同次观测的三个不相交平面片，解析交点为 (1,2,3)。"""
    points = np.array(
        [(x, y, 3) for x in (5, 6) for y in (5, 6)]
        + [(x, 2, z) for x in (5, 6) for z in (5, 6)]
        + [(1, y, z) for y in (5, 6) for z in (5, 6)],
        dtype=np.float64,
    )
    scope, runtime, cloud = make_cloud(unit="mm", coordinates=points)
    groups = []
    for name, center, normal in (
        ("primary", [5.5, 5.5, 3], [0, 0, 1]),
        ("secondary", [5.5, 2, 5.5], [0, 1, 0]),
        ("tertiary", [1, 5.5, 5.5], [1, 0, 0]),
    ):
        crop, _ = crop_roi(
            runtime,
            cloud,
            CropCloudParameters(
                roi_id=name,
                rois=[
                    dict(
                        roi_id=name,
                        frame_id="fixture",
                        length_unit="mm",
                        kind="box",
                        geometry=dict(
                            center=center, size=[1, 1, 1], rotation=np.eye(3).tolist()
                        ),
                    )
                ],
            ),
            cancel=lambda: None,
        )
        groups.append(
            fit_plane(
                runtime,
                crop,
                plane_parameters(feature_id=name, positive_normal=normal),
                cancel=lambda: None,
            )
        )
    return scope, runtime, cloud, groups


@pytest.mark.parametrize("mode", ["direction", "plane", "three"])
def test_explicit_origin_and_axes(mode):
    scope, runtime, cloud, groups = datum_cloud()
    raw = frame_parameters().model_dump(mode="json")
    if mode != "direction":
        raw["x_axis"] = dict(
            kind="plane-intersection",
            secondary_feature_id="secondary",
            positive_direction=[1, 0, 0],
        )
    if mode == "three":
        raw["origin"] = dict(kind="three-planes", tertiary_feature_id="tertiary")
        raw["quality_policy"]["rules"].append(
            dict(item_id="origin_condition", unit="1", upper=10)
        )
    pose = build_frame(
        runtime,
        list(reversed(groups)),
        BuildFrameParameters(**raw),
        cancel=lambda: None,
    )
    assert pose.state == "found" and pose.quality.usable
    expected = np.eye(4)
    expected[:3, 3] = [-1, -2, -3]
    np.testing.assert_allclose(pose.transform.matrix, expected, atol=1e-12)
    raw["positive_z"] = [0, 0, -1]
    flipped = build_frame(
        runtime, groups, BuildFrameParameters(**raw), cancel=lambda: None
    )
    np.testing.assert_allclose(
        np.asarray(flipped.transform.matrix)[:3, :3],
        np.diag([1, -1, -1]),
        atol=1e-12,
    )
    assert not scope.close() and runtime.budget.used == 0


def test_frame_failure_then_success_has_no_old_matrix():
    scope, runtime, _, groups = datum_cloud()
    good = frame_parameters()
    assert build_frame(runtime, groups, good, cancel=lambda: None).state == "found"
    parallel = frame_parameters(x_axis=dict(kind="direction", direction=[0, 0, 1]))
    bad = build_frame(runtime, groups, parallel, cancel=lambda: None)
    assert bad.state == "underconstrained" and bad.transform is None
    assert bad.reason == "datum_axis_parallel"
    ambiguous = build_frame(
        runtime, groups, frame_parameters(positive_z=[1, 0, 0]), cancel=lambda: None
    )
    assert ambiguous.state == "ambiguous" and ambiguous.transform is None
    assert build_frame(runtime, groups, good, cancel=lambda: None).state == "found"
    assert not scope.close()


def test_frame_rejects_miswiring_and_cancels():
    scope, runtime, _, groups = datum_cloud()
    with pytest.raises(InvalidRequestError, match="不存在"):
        build_frame(
            runtime,
            groups,
            frame_parameters(primary_feature_id="missing"),
            cancel=lambda: None,
        )
    with pytest.raises(InvalidRequestError, match="重复"):
        build_frame(
            runtime, [groups[0], groups[0]], frame_parameters(), cancel=lambda: None
        )
    with pytest.raises(InvalidRequestError, match="不同运行"):
        build_frame(
            runtime,
            [groups[0], groups[1].model_copy(update={"observation_id": "other"})],
            frame_parameters(),
            cancel=lambda: None,
        )
    with pytest.raises(RuntimeError, match="cancelled"):
        build_frame(
            runtime,
            groups,
            frame_parameters(),
            cancel=lambda: (_ for _ in ()).throw(RuntimeError("cancelled")),
        )
    assert not scope.close() and runtime.budget.used == 0


def test_frame_schema_requires_constraints_and_rigid_matrix():
    with pytest.raises(ValidationError, match="次基准"):
        frame_parameters(origin=dict(kind="three-planes", tertiary_feature_id="third"))
    with pytest.raises(ValidationError, match="origin_condition"):
        frame_parameters(
            origin=dict(kind="three-planes", tertiary_feature_id="third"),
            x_axis=dict(
                kind="plane-intersection",
                secondary_feature_id="second",
                positive_direction=[1, 0, 0],
            ),
        )
    for first in (-1, 2):
        matrix = np.eye(4)
        matrix[0, 0] = first
        with pytest.raises(ValidationError):
            RigidMatrix3d(
                source_frame_id="a",
                target_frame_id="b",
                observation_id="obs",
                length_unit="mm",
                matrix=matrix.tolist(),
            )


def test_three_planes_dependent_and_quality_gate_never_emit_matrix():
    scope, runtime, _, groups = datum_cloud()
    raw = frame_parameters().model_dump(mode="json")
    raw["x_axis"] = dict(
        kind="plane-intersection",
        secondary_feature_id="secondary",
        positive_direction=[1, 0, 0],
    )
    raw["origin"] = dict(kind="three-planes", tertiary_feature_id="tertiary")
    raw["quality_policy"]["rules"].append(
        dict(item_id="origin_condition", unit="1", upper=10)
    )
    dependent = fit_plane(
        runtime,
        groups[1].items[0].support,
        plane_parameters(feature_id="tertiary", positive_normal=[0, 1, 0]),
        cancel=lambda: None,
    )
    pose = build_frame(
        runtime,
        [*groups[:2], dependent],
        BuildFrameParameters(**raw),
        cancel=lambda: None,
    )
    assert pose.state == "underconstrained" and pose.transform is None
    assert pose.reason == "datum_planes_dependent" and not pose.quality.usable
    p = frame_parameters(positive_z=[0, 0.6, 0.8]).model_dump(mode="json")
    p["quality_policy"]["rules"][2]["lower"] = 0.9
    pose = build_frame(runtime, groups, BuildFrameParameters(**p), cancel=lambda: None)
    assert pose.state == "insufficient_quality" and pose.transform is None
    assert pose.reason == "datum_quality_failed"
    assert not scope.close()
