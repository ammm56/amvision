"""完整工件的敏感性和平台无损资产往返检查。"""

from dataclasses import replace

import numpy as np

from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_boundary
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.envelope_profiles import (
    extract_envelope_profiles,
)
from custom_nodes.metrology3d_nodes.shared.envelope_statistics import profile_spans
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from tests.integration.metrology3d.envelope_audit import independent_envelope
from tests.integration.metrology3d.workpiece_recipe import profile_extents
from tests.test_point_cloud_assets import POLICY


def sensitivity(points, feature, config, budget):
    """只改变明确的格相位/分辨率/截面比例，不修改质量门禁或正式配方。"""
    original = config.method.envelope
    evaluation = feature.method.resolution.evaluation
    resolution = feature.method.resolution
    results = []
    for name, step, phase, ratio in (
        ("nominal", 0.03, 0, 0.5),
        ("coarse", 0.06, 0, 0.5),
        ("half-phase", 0.03, 0.5, 0.5),
        ("lower", 0.03, 0, 0.35),
        ("upper", 0.03, 0, 0.65),
    ):
        data = original.model_dump()
        data["grid"]["origin"] = [v + phase * step for v in original.grid.origin]
        data["grid"]["step"] = step
        data["grid"]["shape"] = [
            int(np.ceil(v * original.grid.step / step)) for v in original.grid.shape
        ]
        settings = type(original).model_validate(data)
        # 两端已核实沿同一台面法向；只在本次解析截面上移动。
        normal = np.asarray(evaluation.rotation)[:, 2]
        endpoints = np.asarray(resolution.measurement.geometry.endpoints)
        delta = (ratio - 0.5) * float((endpoints[1] - endpoints[0]) @ normal)
        plane = evaluation.model_copy(
            update={"origin": tuple(np.asarray(evaluation.origin) + delta * normal)}
        )
        extracted = extract_envelope_profiles(
            points,
            plane,
            settings,
            region=config.region,
            max_working_bytes=budget,
            cancel=lambda: None,
        )
        row = dict(
            name=name, step=step, phase=phase, ratio=ratio, reason=extracted.reason
        )
        if extracted.reason is None:
            expected_points, expected_values = independent_envelope(
                points, plane, settings
            )
            np.testing.assert_allclose(
                extracted.positions, expected_points, rtol=0, atol=1e-10
            )
            actual = profile_spans(
                extracted.positions,
                extracted.profiles,
                plane,
                profile_extents("A_top_L").mode,
                max_working_bytes=budget,
                cancel=lambda: None,
            )
            np.testing.assert_allclose(
                [actual["span_u"], actual["span_v"]],
                expected_values,
                rtol=0,
                atol=1e-10,
            )
            # 独立分位值保留，不作为质量通过或物理准确率证明。
            row.update(
                width=expected_values[0],
                length=expected_values[1],
                metrics=extracted.metrics,
            )
        results.append(row)
    return results


def save_restore(runtime, boundary, service, name):
    """完整实测剖面的九个来源数组、方法/质量和统计端点均应无损恢复。"""
    feature = boundary.items[0]
    policy = replace(
        POLICY,
        max_asset_bytes=16 * 1024**2,
        max_archive_bytes=32 * 1024**2,
        chunk_bytes=1048576,
    )
    with runtime.borrow(feature.support) as view:
        original = {k: v.copy() for k, v in view.profile_lineage_snapshot().items()}
    before = measure_extents(
        runtime, profile_extents(name), groups=[boundary], cancel=lambda: None
    )
    asset = save_cloud(
        runtime,
        feature.support,
        features=boundary,
        service=service,
        project_id="test",
        mode="derived",
        name="F3-real-profile",
        write_identity="f" * 64,
        policy=policy,
        cancel=lambda: None,
    )
    scope = ResourceScope(kind="workflow")
    restored = get_cloud_runtime(
        scope, run_id="f3-real-restored", policy=runtime.policy
    )
    try:
        cloud = read_asset(
            restored,
            asset,
            service=service,
            project_id="test",
            policy=policy,
            cancel=lambda: None,
        )
        content = service.read(asset, project_id="test").content.point_cloud
        group = restore_boundary(cloud, content.boundary)
        assert group.items[0].method == feature.method
        expected_quality = feature.quality.model_dump(mode="json")
        expected_quality["metrics"]["observation_id"] = cloud.observation_id
        assert group.items[0].quality.model_dump(mode="json") == expected_quality
        assert cloud.observation_id != feature.support.observation_id
        with restored.borrow(cloud) as view:
            arrays = view.profile_lineage_snapshot()
            for key, array in original.items():
                np.testing.assert_array_equal(array, arrays[key])
        after = measure_extents(
            restored, profile_extents(name), groups=[group], cancel=lambda: None
        )
        assert [i.value for i in after.items] == [i.value for i in before.items]
        assert after.items[0].geometry.contacts == before.items[0].geometry.contacts
        return dict(
            values=[i.value for i in after.items],
            lineage_fields=list(original),
            released=True,
        )
    finally:
        assert not scope.close() and restored.budget.used == 0
