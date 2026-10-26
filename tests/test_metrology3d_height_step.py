"""高度/高差独立解析真值、缺口、层歧义、质量和资源边界。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes._metrology3d_nodes.shared.height_query import height_query
from custom_nodes._metrology3d_nodes.shared.measure_step import measure_step
from tests.point_cloud_support import policy
from tests.test_metrology3d_measurement_contracts import (
    height_parameters,
    step_parameters,
    measurement_policy,
)
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud


def roi(runtime, cloud, z, *, cancel=lambda: None):
    """测试层使用明确有限盒，所有子集保留同观测与原始行号。"""
    parameters = CropCloudParameters(
        roi_id="layer",
        rois=[
            dict(
                roi_id="layer",
                kind="box",
                frame_id="fixture",
                length_unit="mm",
                geometry=dict(
                    center=[0, 0, z], size=[10, 10, 2], rotation=np.eye(3).tolist()
                ),
            )
        ],
    )
    return crop_roi(runtime, cloud, parameters, cancel=cancel)[0]


def two_planes(*, dtype=np.float64, slope=0, hole=False, mixed=False):
    """解析面 z=0、z=5+slope*x，真值无需调用被测算法构造。"""
    xy = np.array([(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)], dtype=dtype)
    if hole:
        xy = xy[np.any(xy != 0, axis=1)] * 4
    a = np.column_stack((xy, np.zeros(len(xy))))
    b = np.column_stack((xy, 5 + slope * xy[:, 0]))
    points = (
        np.concatenate((a, b, b + [0, 0, 0.2])) if mixed else np.concatenate((a, b))
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points.astype(dtype),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    reference, target = roi(runtime, cloud, 0), roi(runtime, cloud, 5)
    groups = [
        fit_plane(runtime, ref, plane_parameters(feature_id=name), cancel=lambda: None)
        for ref, name in ((reference, "reference"), (target, "target"))
    ]
    return scope, runtime, cloud, reference, target, groups


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
@pytest.mark.parametrize("slope", [0, 0.25])
def test_directional_and_height_independent_truth(dtype, slope):
    scope, runtime, cloud, reference, target, groups = two_planes(
        dtype=dtype, slope=slope
    )
    try:
        result, local = height_query(
            runtime, cloud, groups[:1], height_parameters(), cancel=lambda: None
        )
        assert local.items[0].valid
        assert result.items[0].valid and result.items[0].value == pytest.approx(
            5, abs=1e-10
        )
        np.testing.assert_allclose(
            result.items[0].geometry.endpoints, [[0, 0, 0], [0, 0, 5]], atol=1e-10
        )
        assert all(i >= 9 for i in result.items[0].support[1].coverage.source_indices)
        persisted = MeasurementEvidence3d.model_validate_json(result.model_dump_json())
        assert persisted.numeric_table().items[0].value == result.items[0].value
        assert (
            "cloud_id" not in result.model_dump_json()
            and "run_id" not in result.model_dump_json()
        )
        for direction, expected in (((0, 0, 1), 5), ((0, 0, -1), -5)):
            step = measure_step(
                runtime,
                step_parameters(
                    query=dict(
                        kind="configured", query_position=(0, 0, 0), direction=direction
                    )
                ),
                groups=groups,
                cancel=lambda: None,
            )
            assert step.items[0].value == pytest.approx(expected)
            assert step.items[0].valid
    finally:
        assert not scope.close()


@pytest.mark.parametrize("shift", [0, 1e8])
def test_vertical_planes_with_large_coordinate_translation(shift):
    """沿 X 测距不依赖世界 Z，也不能因整体平移改变尺寸。"""
    yz = np.array([(y, z) for y in (-1, 0, 1) for z in (-1, 0, 1)])
    points = (
        np.concatenate([np.column_stack((np.full(len(yz), x), yz)) for x in (0, 5)])
        + shift
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points.astype(np.float64),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    try:
        groups = []
        for x, name in ((0, "reference"), (5, "target")):
            part, _ = crop_roi(
                runtime,
                cloud,
                CropCloudParameters(
                    roi_id=name,
                    rois=[
                        dict(
                            roi_id=name,
                            kind="box",
                            frame_id="fixture",
                            length_unit="mm",
                            geometry=dict(
                                center=[shift + x, shift, shift],
                                size=[2, 4, 4],
                                rotation=np.eye(3).tolist(),
                            ),
                        )
                    ],
                ),
                cancel=lambda: None,
            )
            groups.append(
                fit_plane(
                    runtime,
                    part,
                    plane_parameters(feature_id=name, positive_normal=(1, 0, 0)),
                    cancel=lambda: None,
                )
            )
        result = measure_step(
            runtime,
            step_parameters(
                query=dict(
                    kind="configured",
                    query_position=(shift, shift, shift),
                    direction=(1, 0, 0),
                )
            ),
            groups=groups,
            cancel=lambda: None,
        )
        assert result.items[0].valid and result.items[0].value == pytest.approx(
            5, abs=1e-8
        )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_parallel_and_empty_support_are_explicitly_invalid():
    """平行测量线和空 ROI 不产生量值，也不借用前一个输出。"""
    scope, runtime, cloud, reference, _, groups = two_planes()
    try:
        result = measure_step(
            runtime,
            step_parameters(
                query=dict(
                    kind="configured", query_position=(0, 0, 0), direction=(1, 0, 0)
                )
            ),
            groups=groups,
            cancel=lambda: None,
        )
        assert not result.items[0].valid and result.items[0].value is None
        empty = roi(runtime, cloud, 100)
        result = measure_step(
            runtime,
            step_parameters(statistic={"kind": "mean"}),
            reference=reference,
            target=empty,
            cancel=lambda: None,
        )
        assert not result.items[0].valid and result.items[0].support[1].point_count == 0
        assert result.items[0].support[1].statistic is None
        result, local = height_query(
            runtime,
            cloud,
            groups[:1],
            height_parameters(search_interval=(99, 101)),
            cancel=lambda: None,
        )
        assert not local.items[0].valid and result.items[0].value is None
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_native_failure_and_work_budget_are_not_silently_downgraded(monkeypatch):
    """原生异常和容量不足作为执行错误传播，并归还全部借用。"""
    import custom_nodes._metrology3d_nodes.shared.measurement_support as support

    scope, runtime, _, _, _, groups = two_planes()
    try:
        before = runtime.budget.used

        def fail(*args, **kwargs):
            raise RuntimeError("native failure")

        with monkeypatch.context() as patch:
            patch.setattr(support, "Delaunay", fail)
            with pytest.raises(RuntimeError, match="native failure"):
                measure_step(
                    runtime, step_parameters(), groups=groups, cancel=lambda: None
                )
        assert runtime.budget.used == before
        with monkeypatch.context() as patch:
            patch.setattr(
                runtime,
                "policy",
                runtime.policy.model_copy(update={"max_working_bytes": 8000}),
            )
            with pytest.raises(InvalidRequestError, match="预算"):
                measure_step(
                    runtime, step_parameters(), groups=groups, cancel=lambda: None
                )
        assert runtime.budget.used == before
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_outside_support_and_hole_are_invalid():
    scope, runtime, cloud, _, _, groups = two_planes()
    try:
        outside = measure_step(
            runtime,
            step_parameters(
                query=dict(
                    kind="configured", query_position=(2, 0, 0), direction=(0, 0, 1)
                ),
                support_radius=5,
            ),
            groups=groups,
            cancel=lambda: None,
        )
        assert not outside.items[0].valid and outside.items[0].geometry is None
        assert not outside.items[0].support[0].coverage.covered
        narrow = measure_step(
            runtime,
            step_parameters(
                quality_policy=measurement_policy(
                    reference_triangle_edge={"upper": 0.5},
                    target_triangle_edge={"upper": 0.5},
                )
            ),
            groups=groups,
            cancel=lambda: None,
        )
        assert not narrow.items[0].valid
    finally:
        assert not scope.close()
    scope, runtime, cloud, _, _, groups = two_planes(hole=True)
    try:
        result = measure_step(
            runtime,
            step_parameters(support_radius=10),
            groups=groups,
            cancel=lambda: None,
        )
        assert not result.items[0].valid and result.items[0].value is None
        assert result.items[0].support[0].coverage.triangle_edge > 2
    finally:
        assert not scope.close()


def test_mixed_layers_are_not_silently_measured():
    scope, runtime, cloud, _, _, groups = two_planes(mixed=True)
    try:
        result, local = height_query(
            runtime, cloud, groups[:1], height_parameters(), cancel=lambda: None
        )
        assert not local.items[0].valid
        assert not result.items[0].valid and result.items[0].value is None
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "statistic",
    [
        {"kind": "mean"},
        {"kind": "median"},
        {"kind": "quantile", "probability": 0.25, "method": "linear"},
    ],
)
def test_statistics_use_all_points_and_do_not_invent_endpoints(statistic):
    scope, runtime, _, reference, target, _ = two_planes(slope=0.25)
    try:
        result = measure_step(
            runtime,
            step_parameters(statistic=statistic),
            reference=reference,
            target=target,
            cancel=lambda: None,
        ).items[0]
        expected = 4.75 if statistic["kind"] == "quantile" else 5
        assert result.valid and result.value == pytest.approx(expected)
        assert result.geometry.endpoints is None
        assert result.sample_origin == "measured"
        assert result.support[1].statistic.count == 9
        assert result.support[1].statistic.std == pytest.approx(np.sqrt(1 / 24))
    finally:
        assert not scope.close()


def test_configuration_identity_budget_cancel_and_tampered_evidence():
    scope, runtime, cloud, reference, target, groups = two_planes()
    try:
        with pytest.raises(InvalidRequestError, match="ID 不存在"):
            measure_step(
                runtime,
                step_parameters(target_feature_id="missing"),
                groups=groups,
                cancel=lambda: None,
            )
        with pytest.raises(InvalidRequestError, match="不能连接"):
            measure_step(
                runtime,
                step_parameters(),
                groups=groups,
                target=target,
                cancel=lambda: None,
            )
        with pytest.raises(InvalidRequestError, match="不一致"):
            height_query(
                runtime,
                cloud,
                groups,
                height_parameters(frame_id="wrong"),
                cancel=lambda: None,
            )
        result = measure_step(
            runtime, step_parameters(), groups=groups, cancel=lambda: None
        )
        wrong = result.model_dump(mode="json")
        wrong["items"][0]["geometry"]["endpoints"][1][2] = 6
        wrong["items"][0]["value"] = 6
        with pytest.raises(ValidationError, match="对应平面"):
            MeasurementEvidence3d.model_validate(wrong)
        before = runtime.budget.used
        calls = 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls > 10:
                raise InterruptedError("cancelled")

        with pytest.raises(InterruptedError):
            measure_step(runtime, step_parameters(), groups=groups, cancel=cancel)
        assert runtime.budget.used == before
    finally:
        assert not scope.close()
