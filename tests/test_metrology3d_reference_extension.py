"""基准延伸独立解析真值；所有距离与预算仅为显式测试配置。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.contracts.workflows.measurement3d_parameters import HeightQueryParameters
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.height_query import height_query
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from tests.test_metrology3d_height_step import roi, two_planes
from tests.test_metrology3d_measurement_contracts import (
    height_parameters,
    step_parameters,
    measurement_policy,
)
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.point_cloud_support import policy
from backend.contracts.workflows.geometry3d import CropCloudParameters


def extension(limit=1.0):
    """到最近投影实测点的上限，不是到无限平面的距离。"""
    return dict(kind="plane-extension", max_extension_distance=limit)


def offset_planes(
    *, transform=None, scale=1.0, unit="mm", reverse=False, nonuniform=False
):
    """基准 x=-3..-1，目标 x=-.1..+.1；查询轴到基准最近点恰为 1。"""
    a = np.array([(x, y, 0) for x in (-3, -2, -1) for y in (-1, 0, 1)])
    if nonuniform:
        a = np.concatenate((a, np.repeat([[-3, 0, 0]], 40, axis=0)))
    b = np.array([(x, y, 5) for x in (-0.1, 0, 0.1) for y in (-0.1, 0, 0.1)])
    matrix, shift = transform or (np.eye(3), np.zeros(3))
    points = np.concatenate((a, b)) * scale @ matrix.T + shift
    scope, runtime, cloud = make_cloud(
        unit=unit,
        coordinates=points.astype(np.float64),
        runtime_policy=policy(max_working_bytes=1024 * 1024),
    )
    groups = []
    for name, center, size in (
        ("reference", (-2, 0, 0), (2.5, 2.5, 1)),
        ("target", (0, 0, 5), (1, 1, 1)),
    ):
        region = CropCloudParameters(
            roi_id=name,
            rois=[
                dict(
                    roi_id=name,
                    kind="box",
                    frame_id="fixture",
                    length_unit=unit,
                    geometry=dict(
                        center=np.asarray(center) * scale @ matrix.T + shift,
                        size=np.asarray(size) * scale,
                        rotation=matrix,
                    ),
                )
            ],
        )
        part, _ = crop_roi(runtime, cloud, region, cancel=lambda: None)
        p = plane_parameters(
            feature_id=name, positive_normal=matrix[:, 2] * (-1 if reverse else 1)
        ).model_dump()
        for rule in p["quality_policy"]["rules"]:
            if rule["unit"] == "mm":
                rule["unit"] = unit
                if rule["upper"] is not None:
                    rule["upper"] *= scale
        groups.append(
            fit_plane(
                runtime,
                part,
                type(plane_parameters()).model_validate(p),
                cancel=lambda: None,
            )
        )
    return scope, runtime, cloud, groups


@pytest.mark.parametrize("limit,valid", [(1.0, True), (0.999, False), (2.0, True)])
def test_actual_support_outside_local_radius_and_explicit_distance_gate(limit, valid):
    scope, runtime, cloud, groups = offset_planes()
    try:
        p = step_parameters(support_radius=0.25, reference_policy=extension(limit))
        result = measure_step(runtime, p, groups=groups, cancel=lambda: None)
        item = result.items[0]
        assert item.valid is valid
        assert item.value == (pytest.approx(5) if valid else None)
        side = item.support[0]
        assert side.coverage.count == 0 and not side.coverage.covered
        assert side.coverage.nearest_distance is None
        assert side.extension.distance == pytest.approx(1)
        assert side.extension.nearest_support_point == (-1, 0, 0)
        assert side.extension.source_index == 7
        assert side.extension.used_extension is valid
        assert side.extension.state == ("used" if valid else "limit-exceeded")
        if not valid:
            assert item.reason == "reference_extension_limit_exceeded"
        assert item.sample_origin == ("mixed" if valid else "interpolated")
        assert (
            MeasurementEvidence3d.model_validate_json(result.model_dump_json())
            == result
        )
        assert {m.item_id for m in item.quality.metrics.items} == {
            "reference_direction_cosine",
            "reference_extension_distance",
            "target_count",
            "target_covered",
            "target_direction_cosine",
            "target_nearest_distance",
            "target_triangle_edge",
            "target_max_residual",
        }
        height, _ = height_query(
            runtime,
            cloud,
            groups[:1],
            height_parameters(
                support_radius=0.25,
                search_radius=0.25,
                reference_policy=extension(limit),
            ),
            cancel=lambda: None,
        )
        assert height.items[0].valid is valid and height.items[0].value == item.value
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("scale,unit", [(1, "mm"), (0.001, "m")])
def test_rigid_frame_normal_sign_and_units_preserve_independent_height(
    reverse, scale, unit
):
    angle = np.pi / 6
    matrix = np.array(
        [
            [np.cos(angle), 0, np.sin(angle)],
            [0, 1, 0],
            [-np.sin(angle), 0, np.cos(angle)],
        ]
    )
    shift = np.array([100, -50, 12]) * scale
    scope, runtime, _, groups = offset_planes(
        transform=(matrix, shift), scale=scale, unit=unit, reverse=reverse
    )
    try:
        raw = step_parameters(reference_policy=extension(1.01 * scale)).model_dump()
        raw["length_unit"] = unit
        raw["mode"].update(
            query=dict(kind="configured", query_position=shift, direction=matrix[:, 2]),
            support_radius=0.25 * scale,
        )
        for rule in raw["mode"]["quality_policy"]["rules"]:
            if rule["unit"] == "mm":
                rule["unit"] = unit
                if rule["upper"] is not None:
                    rule["upper"] *= scale
        result = measure_step(
            runtime,
            type(step_parameters()).model_validate(raw),
            groups=groups,
            cancel=lambda: None,
        )
        assert result.items[0].value == pytest.approx(5 * scale, rel=1e-10)
        assert result.items[0].support[0].extension.distance == pytest.approx(
            scale, rel=1e-10
        )
    finally:
        assert not scope.close()


def test_covered_reference_cannot_escape_failed_triangle_quality_via_extension():
    scope, runtime, _, _, _, groups = two_planes()
    try:
        result = measure_step(
            runtime,
            step_parameters(
                reference_policy=extension(100),
                quality_policy=measurement_policy(
                    reference_triangle_edge={"upper": 0.1}
                ),
            ),
            groups=groups,
            cancel=lambda: None,
        )
        item = result.items[0]
        assert not item.valid and item.support[0].coverage.covered
        assert item.support[0].extension.state == "covered"
        assert not item.support[0].extension.used_extension
        assert any(
            c.item_id == "reference_triangle_edge" and not c.passed
            for c in item.quality.checks
        )
    finally:
        assert not scope.close()


def test_target_missing_and_parallel_reference_remain_invalid():
    scope, runtime, cloud, groups = offset_planes()
    try:
        empty = roi(runtime, cloud, 100)
        missing = fit_plane(
            runtime, empty, plane_parameters(feature_id="target"), cancel=lambda: None
        )
        result = measure_step(
            runtime,
            step_parameters(reference_policy=extension(2)),
            groups=[groups[0], missing],
            cancel=lambda: None,
        )
        assert not result.items[0].valid and result.items[0].value is None
        assert result.items[0].support[0].extension.used_extension
        assert result.items[0].support[1].extension is None
        parallel = measure_step(
            runtime,
            step_parameters(
                query=dict(
                    kind="configured", query_position=(0, 0, 0), direction=(1, 0, 0)
                ),
                reference_policy=extension(2),
            ),
            groups=groups,
            cancel=lambda: None,
        )
        assert not parallel.items[0].valid
        assert parallel.items[0].support[0].extension.state == "unavailable"
    finally:
        assert not scope.close()


def test_nearest_support_is_not_shifted_by_uneven_sampling_and_cancel_releases_borrow(
    monkeypatch,
):
    """远处重复采样不能改变最近距离；取消不能遗留持有者。"""
    from custom_nodes.metrology3d_nodes.shared import measurement_reference

    scope, runtime, _, groups = offset_planes(nonuniform=True)
    p = step_parameters(support_radius=0.25, reference_policy=extension(2))
    try:
        result = measure_step(runtime, p, groups=groups, cancel=lambda: None)
        assert result.items[0].support[0].extension.distance == pytest.approx(1)
        assert result.items[0].support[0].extension.source_index == 7
        calls = 0
        scanning = False
        original_coverage = measurement_reference.plane_coverage

        def coverage(*args, **kwargs):
            nonlocal scanning
            result = original_coverage(*args, **kwargs)
            scanning = True
            return result

        monkeypatch.setattr(measurement_reference, "plane_coverage", coverage)
        monkeypatch.setattr(measurement_reference, "_rows", lambda *args: 2)

        def cancel():
            nonlocal calls
            if scanning:
                calls += 1
            if calls == 2:
                raise InterruptedError("test cancel")

        with pytest.raises(InterruptedError):
            measure_step(runtime, p, groups=groups, cancel=cancel)
        assert calls == 2
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize(
    "change",
    [
        "distance",
        "source",
        "point",
        "role",
        "state",
        "max",
        "policy",
        "quality",
        "datum",
        "projected",
    ],
)
def test_persisted_extension_evidence_cannot_be_forged(change):
    scope, runtime, _, groups = offset_planes()
    try:
        result = measure_step(
            runtime,
            step_parameters(reference_policy=extension(2)),
            groups=groups,
            cancel=lambda: None,
        )
        raw = result.model_dump(mode="json")
        item = raw["items"][0]
        ext = item["support"][0]["extension"]
        if change == "distance":
            ext["distance"] = 0.5
        if change == "source":
            ext["source_index"] = 1000
        if change == "point":
            ext["nearest_support_point"] = [100, 0, 0]
        if change == "role":
            item["support"][1]["extension"] = ext
        if change == "state":
            ext["state"] = "covered"
        if change == "max":
            ext["max_distance"] = 3
        if change == "policy":
            item["method"]["parameters"]["mode"]["reference_policy"] = {
                "kind": "measured-support"
            }
        if change == "quality":
            item["quality"]["metrics"]["items"][0]["value"] = 0.5
        if change == "datum":
            ext["datum_point"] = [0, 0, 1]
        if change == "projected":
            ext["projected_support_point"] = [-1, 1, 0]
        with pytest.raises(ValidationError):
            MeasurementEvidence3d.model_validate(raw)
    finally:
        assert not scope.close()


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"kind": "plane-extension"},
        extension(0),
        extension(-1),
        extension(float("inf")),
        {"kind": "measured-support", "max_extension_distance": 1},
    ],
)
def test_strategy_is_required_and_cannot_guess_distance(value):
    raw = height_parameters().model_dump()
    if value is None:
        del raw["reference_policy"]
    else:
        raw["reference_policy"] = value
    with pytest.raises(ValidationError):
        HeightQueryParameters.model_validate(raw)
    with pytest.raises(ValidationError):
        step_parameters(statistic={"kind": "mean"}, reference_policy=value)
