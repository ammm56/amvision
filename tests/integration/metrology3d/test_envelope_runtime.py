"""可见包络从真实拟面/位姿到资源、尺寸、保存恢复的组合回归。"""

from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.boundary3d import ExtractBoundaryParameters
from backend.contracts.workflows.envelope3d import PROFILE_SIDES
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.lineage import validate_lineage
from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_boundary
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from tests.point_cloud_support import policy, create_resource_service
from tests.test_point_cloud_assets import POLICY
from tests.test_metrology3d_envelope import points, settings
from tests.test_metrology3d_pose_query import tilted_fixture, query
from tests.test_metrology3d_measurement_contracts import step_parameters
from tests.test_metrology3d_dimension_contracts import extent_parameters


def fixture():
    """解析长宽 4/6，原始行号前置162个独立拟面支持，不从输出生成真值。"""
    values = tilted_fixture(
        extra=points() + [10, 0, 2.525],
        limits=policy(
            max_working_bytes=16_000_000,
            max_live_array_bytes=8_000_000,
            max_decoded_bytes=8_000_000,
        ),
    )
    scope, runtime, cloud, groups, pose, _, rotation, origin = values
    measured = measure_step(
        runtime,
        step_parameters(query=query()),
        groups=groups,
        pose=pose,
        cancel=lambda: None,
    ).items[0]
    config = settings(
        grid=dict(origin=[10, 0]), selection=dict(seed_min=[14, 5], seed_max=[15, 6])
    )
    region = dict(
        roi_id="target",
        rois=[
            dict(
                roi_id="target",
                frame_id="fixture",
                length_unit="mm",
                kind="box",
                geometry=dict(
                    center=origin + rotation @ [15, 6, 2.525],
                    rotation=rotation,
                    size=[12, 14, 4],
                ),
            )
        ],
    )
    p = ExtractBoundaryParameters(
        feature_id="envelope",
        evaluation=dict(
            kind="pose",
            frame_id="fixture",
            length_unit="mm",
            pose_id="datum",
            target_frame_id="part",
        ),
        region=region,
        surface=None,
        targets=[],
        method=dict(
            kind="visible-envelope",
            reference_feature_id="reference",
            height=dict(
                kind="measurement-ratio",
                item_id="step",
                reference_feature_id="reference",
                target_feature_id="target",
                ratio=0.5,
                order="target-above",
            ),
            numeric_tolerance=1e-8,
            envelope=config,
        ),
        quality_policy=dict(
            policy_id="envelope-test",
            policy_version=1,
            rules=[
                dict(item_id="support_count", unit="1", lower=2),
                dict(item_id="length", unit="mm", lower=0.1),
                dict(item_id="profile_coverage", unit="1", lower=0.5),
                dict(item_id="estimated_fraction", unit="1", upper=1),
                dict(item_id="profile_max_gap", unit="mm", upper=3),
                dict(item_id="max_cell_span", unit="mm", upper=0.1),
            ],
        ),
    )
    return values, p, measured


def extract(values, p, measured):
    """不替换准入或伪造 PlaneFeature，复用真实运行链路。"""
    _, runtime, cloud, groups, pose, *_ = values
    return extract_boundary(
        runtime,
        cloud,
        p,
        contour_plane=groups[0].items[0],
        pose=pose,
        measurement=measured,
        measurement_planes=tuple(g.items[0] for g in groups),
        cancel=lambda: None,
    )


def extents(runtime, group):
    """同一稳定四侧来源，U/V 标签不随长短改变。"""
    p = extent_parameters(
        evaluation=dict(kind="feature", frame_id="fixture", length_unit="mm"),
        source=dict(
            kind="boundary",
            selection=dict(feature_id="envelope", segment_ids=PROFILE_SIDES),
        ),
        mode=dict(
            kind="robust-profile-spans",
            lower_quantile=0.02,
            upper_quantile=0.98,
            quantile_method="linear",
        ),
    )
    return measure_extents(runtime, p, groups=[group], cancel=lambda: None)


def test_true_pose_sources_original_rows_and_dimension_evidence():
    values, p, measured = fixture()
    scope, runtime, *_ = values
    try:
        group = extract(values, p, measured)
        feature = group.items[0]
        assert feature.valid, feature.reason
        assert feature.support.sample_origin == "estimated"
        with runtime.borrow(feature.support) as view:
            lineage = view.profile_lineage_snapshot()
            assert lineage["cell_sources"].min() >= 162
            assert lineage["cell_sources"].max() < 282
        result = extents(runtime, group)
        assert all(i.valid for i in result.items)
        assert [i.value for i in result.items] == pytest.approx([4, 6], abs=1e-12)
        assert all(i.sample_origin == "estimated" for i in result.items)
        assert all(
            c.statistic.method == "linear" for c in result.items[0].geometry.contacts
        )
        raw = result.model_dump(mode="json")
        assert type(result).model_validate(raw) == result
        raw["items"][0]["geometry"]["contacts"][0]["statistic"]["vertex_indices"] = [
            1000,
            1001,
        ]
        with pytest.raises(ValidationError, match="剖面来源"):
            type(result).model_validate(raw)
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_profile_save_restore_keeps_all_lineage_quality_and_dimensions(tmp_path):
    values, p, measured = fixture()
    scope, runtime, *_ = values
    limits = runtime.policy
    service = create_resource_service(tmp_path)
    assets = replace(
        POLICY,
        max_asset_bytes=1024 * 1024,
        max_archive_bytes=2 * 1024 * 1024,
        chunk_bytes=128,
    )
    try:
        group = extract(values, p, measured)
        feature = group.items[0]
        assert feature.valid
        with runtime.borrow(feature.support) as view:
            original = {
                key: value.copy()
                for key, value in view.profile_lineage_snapshot().items()
            }
        asset = save_cloud(
            runtime,
            feature.support,
            features=group,
            service=service,
            project_id="test",
            mode="derived",
            name="visible-envelope",
            write_identity="e" * 64,
            policy=assets,
            cancel=lambda: None,
        )
        content = service.read(asset, project_id="test").content.point_cloud
        assert content.lineage.kind == "grid-profile"
    finally:
        assert not scope.close() and runtime.budget.used == 0
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="restored-envelope", policy=limits)
    try:
        cloud = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=assets,
            cancel=lambda: None,
        )
        assert cloud.sample_origin == "estimated"
        with runtime.borrow(cloud) as view:
            restored = view.profile_lineage_snapshot()
            for key, array in original.items():
                np.testing.assert_array_equal(array, restored[key])
        group = restore_boundary(cloud, content.boundary)
        assert group.items[0].method == feature.method
        assert [i.value for i in extents(runtime, group).items] == pytest.approx(
            [4, 6], abs=1e-12
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_stale_source_and_conflicting_legacy_parameters_rejected():
    values, p, measured = fixture()
    scope, runtime, *_ = values
    try:
        raw = p.model_dump(mode="json")
        raw["targets"] = [
            dict(segment_id="edge", region=raw["region"], closed=True, role="outer")
        ]
        with pytest.raises(ValidationError, match="闭合段"):
            ExtractBoundaryParameters.model_validate(raw)
        changed = list(values)
        changed[2] = values[2].model_copy(update={"run_id": "wrong"})
        with pytest.raises(InvalidRequestError):
            extract(changed, p, measured)
    finally:
        assert not scope.close() and runtime.budget.used == 0


@pytest.mark.parametrize(
    "field",
    [
        "cell_sources",
        "profile_weights",
        "profile_cells",
        "profile_stations",
        "cell_indices",
    ],
)
def test_corrupt_profile_lineage_rejected(field):
    values, p, measured = fixture()
    scope, runtime, *_ = values
    try:
        cloud = extract(values, p, measured).items[0].support
        with runtime.borrow(cloud) as view:
            arrays = {
                key: value.copy()
                for key, value in view.profile_lineage_snapshot().items()
            }
        if field == "cell_indices":
            arrays[field] += np.uint64(2**63)
        else:
            arrays[field][0, 0] = 999999
        for array in arrays.values():
            array.setflags(write=False)
        with pytest.raises(InvalidRequestError):
            validate_lineage(
                arrays,
                point_count=cloud.point_count,
                source_point_count=282,
                policy=runtime.policy,
                cancel=lambda: None,
                kind="grid-profile",
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_preview_uses_explicit_profile_kinds_and_no_runtime_reference():
    """显示完整剖面和断点，不带释放权或伪造实测行号。"""
    from custom_nodes.metrology3d_nodes.shared.boundary_preview import curve_display
    from backend.contracts.workflows.boundary3d_preview import BoundaryDisplay
    from tests.test_metrology3d_preview import preview_policy

    values, p, measured = fixture()
    scope, runtime, *_ = values
    try:
        feature = extract(values, p, measured).items[0]
        display = BoundaryDisplay.model_validate(
            curve_display(
                runtime,
                feature,
                policy=preview_policy(),
                remaining_points=1000,
                cancel=lambda: None,
            )
        )
        assert len(display.profile_kinds) == feature.support.point_count
        assert all(k == 0 for k in display.profile_kinds)
        assert "run_id" not in display.model_dump_json()
        raw = display.model_dump(mode="json")
        raw["profile_kinds"] = []
        with pytest.raises(ValidationError):
            BoundaryDisplay.model_validate(raw)
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_generated_owners_released_when_registration_is_cancelled(monkeypatch):
    """保留异常对象仍不能持有已取消输出；不依靠下一次垃圾回收才释放计费。"""
    import weakref
    import custom_nodes.metrology3d_nodes.shared.boundary_runtime as module

    values, p, measured = fixture()
    scope, runtime, *_ = values
    refs, original = [], module.own_output

    def capture(runtime, arrays, keys):
        refs.extend(weakref.ref(a) for a in arrays.values())
        return original(runtime, arrays, keys)

    def cancelled(**kwargs):
        raise InterruptedError("register-cancel")

    monkeypatch.setattr(module, "own_output", capture)
    monkeypatch.setattr(runtime, "register_generated", cancelled)
    try:
        with pytest.raises(InterruptedError) as saved:
            extract(values, p, measured)
        assert str(saved.value) == "register-cancel"
        assert refs and all(ref() is None for ref in refs)
    finally:
        assert not scope.close() and runtime.budget.used == 0
