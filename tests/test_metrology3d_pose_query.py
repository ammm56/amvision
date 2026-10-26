"""固定 U/V 和本次位姿的独立真值、失效来源与持久证据回归。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes._metrology3d_nodes.shared.height_query import height_query
from custom_nodes._metrology3d_nodes.shared.measure_step import measure_step
from tests.test_metrology3d_frame import frame_parameters
from tests.test_metrology3d_measurement_contracts import (
    height_parameters,
    step_parameters,
)
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.point_cloud_support import policy


def tilted_fixture(dtype=np.float64):
    """独立构造旋转后的 z=0 / z=5+0.2x；不调用测量解算产生真值。"""
    a, b = 0.37, -0.28
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    ry = np.array([[np.cos(b), 0, np.sin(b)], [0, 1, 0], [-np.sin(b), 0, np.cos(b)]])
    rotation, origin = rz @ ry, np.array([12.0, -8.0, 3.0])
    local = np.array(
        [
            (x, y, z + 0.2 * x if z else 0)
            for z in (0, 5)
            for x in np.linspace(-2, 2, 9)
            for y in np.linspace(-2, 2, 9)
        ]
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=(local @ rotation.T + origin).astype(dtype),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    groups = []
    for name, z in (("reference", 0), ("target", 5)):
        roi = CropCloudParameters(
            roi_id=name,
            rois=[
                dict(
                    roi_id=name,
                    frame_id="fixture",
                    length_unit="mm",
                    kind="box",
                    geometry=dict(
                        center=origin + rotation @ [0, 0, z],
                        size=[6, 6, 2],
                        rotation=rotation,
                    ),
                )
            ],
        )
        child, _ = crop_roi(runtime, cloud, roi, cancel=lambda: None)
        groups.append(
            fit_plane(
                runtime,
                child,
                plane_parameters(feature_id=name, positive_normal=rotation[:, 2]),
                cancel=lambda: None,
            )
        )
    config = frame_parameters(
        primary_feature_id="reference",
        origin=dict(kind="anchor-projection", anchor=origin),
        x_axis=dict(kind="direction", direction=rotation[:, 0]),
        positive_z=rotation[:, 2],
    )
    pose = build_frame(runtime, groups[:1], config, cancel=lambda: None)
    return scope, runtime, cloud, groups, pose, config, rotation, origin


def query(uv=(0.25, -0.25)):
    """测试固定坐标，仅用于已知姿态和解析曲面。"""
    return dict(kind="pose-uv", pose_id="datum", target_frame_id="part", uv=uv)


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_pose_uv_tilted_truth_and_persistent_evidence(dtype, tmp_path):
    scope, runtime, cloud, groups, pose, _, rotation, origin = tilted_fixture(dtype)
    try:
        result = measure_step(
            runtime,
            step_parameters(query=query()),
            groups=groups,
            pose=pose,
            cancel=lambda: None,
        )
        height, local = height_query(
            runtime,
            cloud,
            groups[:1],
            height_parameters(
                query=query(),
                plane_fit=plane_parameters(
                    feature_id="target", positive_normal=rotation[:, 2]
                ),
            ),
            pose=pose,
            cancel=lambda: None,
        )
        tolerance = 2e-6 if dtype == np.float32 else 1e-10
        expected = [origin + rotation @ [0.25, -0.25, z] for z in (0, 5.05)]
        assert local.items[0].valid
        for evidence in (result, height):
            item = evidence.items[0]
            assert item.valid and item.value == pytest.approx(5.05, abs=tolerance)
            np.testing.assert_allclose(
                item.geometry.endpoints, expected, atol=tolerance, rtol=0
            )
            np.testing.assert_allclose(
                item.geometry.direction, rotation[:, 2], atol=tolerance, rtol=0
            )
            raw = evidence.model_dump_json()
            assert (
                '"run_id"' not in raw
                and '"cloud_id"' not in raw
                and '"lease"' not in raw
            )
            path = tmp_path / f"{item.kind}.json"
            path.write_text(raw, encoding="utf-8")
            assert (
                MeasurementEvidence3d.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                == evidence
            )
        raw = result.model_dump(mode="json")
        raw["items"][0]["method"]["query_resolution"]["line"]["query_position"][0] += (
            0.01
        )
        with pytest.raises(ValidationError, match="U/V"):
            MeasurementEvidence3d.model_validate(raw)
    finally:
        assert not scope.close() and runtime.budget.used == 0
    # 持久证据仍可读，但不会产生有效的历史运行支持权限。
    assert (
        MeasurementEvidence3d.model_validate_json(path.read_text(encoding="utf-8"))
        .items[0]
        .valid
    )


def test_failed_pose_does_not_fit_target_or_fallback():
    scope, runtime, cloud, groups, _, config, rotation, _ = tilted_fixture()
    try:
        bad_config = config.model_copy(
            update={
                "x_axis": config.x_axis.model_copy(
                    update={"direction": tuple(rotation[:, 2])}
                )
            }
        )
        pose = build_frame(runtime, groups[:1], bad_config, cancel=lambda: None)
        assert pose.state != "found"
        for extended in (False, True):
            changes = (
                {
                    "reference_policy": dict(
                        kind="plane-extension", max_extension_distance=3
                    )
                }
                if extended
                else {}
            )
            evidence = measure_step(
                runtime,
                step_parameters(query=query(), **changes),
                groups=groups,
                pose=pose,
                cancel=lambda: None,
            )
            height, features = height_query(
                runtime,
                cloud,
                groups[:1],
                height_parameters(query=query(), **changes),
                pose=pose,
                cancel=lambda: None,
            )
            assert (
                not features.items[0].valid
                and features.items[0].support.state == "unavailable"
            )
            for output in (evidence, height):
                item = output.items[0]
                assert not item.valid and item.value is None and item.geometry is None
                assert item.reason == "query_pose_unavailable"
                assert item.method.query_resolution.line is None
                assert item.method.query_resolution.pose.reason == pose.reason
                assert all(
                    s.coverage is None and s.extension is None for s in item.support
                )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_pose_query_rejects_source_frame_and_cancel_releases():
    """配置不混淆源/目标坐标；取消不留下本次查询新增资源。"""
    for constructor in (height_parameters, step_parameters):
        with pytest.raises(ValidationError, match="源坐标系"):
            constructor(query={**query(), "target_frame_id": "fixture"})
    scope, runtime, cloud, groups, pose, _, _, _ = tilted_fixture()
    used = runtime.budget.used

    def cancel():
        raise InterruptedError("cancelled")

    try:
        with pytest.raises(InterruptedError):
            height_query(
                runtime,
                cloud,
                groups[:1],
                height_parameters(query=query()),
                pose=pose,
                cancel=cancel,
            )
        assert runtime.budget.used == used
        with pytest.raises(InterruptedError):
            measure_step(
                runtime,
                step_parameters(query=query()),
                groups=groups,
                pose=pose,
                cancel=cancel,
            )
        assert runtime.budget.used == used
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize(
    "change", ["missing", "extra", "id", "frame", "run", "observation", "unit", "stale"]
)
def test_pose_source_admission(change):
    scope, runtime, cloud, groups, pose, _, _, _ = tilted_fixture()
    try:
        p = step_parameters(query=query())
        if change == "missing":
            pose = None
        elif change == "extra":
            p = step_parameters()
        elif change in {"id", "frame"}:
            p = step_parameters(
                query={
                    **query(),
                    "pose_id" if change == "id" else "target_frame_id": "wrong",
                }
            )
        elif change != "stale":
            field = {
                "run": "run_id",
                "observation": "observation_id",
                "unit": "length_unit",
            }[change]
            pose = pose.model_copy(update={field: "m" if change == "unit" else "other"})
        else:
            # 保留相同运行 ID，替换当前注册身份，不能只靠字符串 ID 放行。
            source = pose.support[0].model_copy(
                update={"revision": pose.support[0].revision + 1}
            )
            pose = pose.model_copy(update={"support": (source,)})
        with pytest.raises(InvalidRequestError):
            measure_step(runtime, p, groups=groups, pose=pose, cancel=lambda: None)
    finally:
        assert not scope.close() and runtime.budget.used == 0
