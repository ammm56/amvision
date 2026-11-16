"""内置 ROI 与独立裁剪拟面等价，异常撤销不破坏共享输入。"""

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.geometry3d import CropCloudParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.geometry_parameters import (
    PlaneNodeParameters,
)
from custom_nodes.metrology3d_nodes.shared.plane_node_support import fit_supported_plane
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preprocess import make_cloud


def support(shift=0):
    """有限测试窗口，不作为生产参数。"""
    return dict(
        kind="parameters",
        roi=dict(
            roi_id="patch",
            frame_id="fixture",
            length_unit="mm",
            kind="box",
            geometry=dict(
                center=[shift, 0, 3], size=[2, 2, 2], rotation=np.eye(3).tolist()
            ),
        ),
        bounds=[],
    )


def configured(**changes):
    """沿用现有算法参数，支持范围属于节点配置。"""
    return PlaneNodeParameters(
        settings=plane_parameters(), support=support(), **changes
    )


@pytest.mark.parametrize("dtype", [np.float32, np.float64])
def test_inline_matches_explicit_support_and_preserves_source(dtype):
    points = np.array(
        [[-1, -1, 3], [-1, 1, 3], [1, -1, 3], [1, 1, 3], [9, 9, 9]], dtype=dtype
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        attributes=[("strength", np.arange(5, dtype=np.uint16), None)],
    )
    try:
        p = configured()
        selected, _ = crop_roi(
            runtime,
            cloud,
            CropCloudParameters(roi_id=p.support.roi.roi_id, rois=(p.support.roi,)),
            cancel=lambda: None,
        )
        expected = fit_plane(runtime, selected, p.settings, cancel=lambda: None).items[
            0
        ]
        actual = fit_supported_plane(runtime, cloud, p, cancel=lambda: None).items[0]
        assert actual.model_dump(exclude={"support"}) == expected.model_dump(
            exclude={"support"}
        )
        assert runtime.source_point_count(actual.support) == runtime.source_point_count(
            cloud
        )
        assert actual.support.observation_id == cloud.observation_id
        assert actual.support.fields == cloud.fields
        with runtime.borrow(actual.support) as view:
            for i in range(4):
                arrays = view.chunk(i, i + 1)
                np.testing.assert_array_equal(arrays["positions"], points[i : i + 1])
                np.testing.assert_array_equal(view.source_indices(i, i + 1), [i])
                np.testing.assert_array_equal(arrays["strength"].ravel(), [i])
        with runtime.borrow(cloud) as view:
            for i in range(5):
                np.testing.assert_array_equal(
                    view.chunk(i, i + 1)["positions"], points[i : i + 1]
                )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


@pytest.mark.parametrize("shift", [0, 100])
def test_empty_and_whole_support_keep_existing_failure_rules(shift):
    scope, runtime, cloud = make_cloud(
        unit="mm", coordinates=np.array([[0, 0, 3], [1, 0, 3]], dtype=np.float64)
    )
    try:
        p = PlaneNodeParameters(settings=plane_parameters(), support=support(shift))
        result = fit_supported_plane(runtime, cloud, p, cancel=lambda: None).items[0]
        assert not result.valid and result.reason == "insufficient_support"
        assert result.support.point_count == (2 if shift == 0 else 0)
        whole = fit_supported_plane(
            runtime,
            cloud,
            PlaneNodeParameters(settings=plane_parameters()),
            cancel=lambda: None,
        )
        assert whole.items[0].support == cloud
    finally:
        assert not scope.close()


@pytest.mark.parametrize("stage", ["fit", "cancel"])
def test_fit_failure_releases_new_subset_and_keeps_existing_cloud(monkeypatch, stage):
    import custom_nodes.metrology3d_nodes.shared.plane_node_support as module

    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array(
            [[-1, -1, 3], [-1, 1, 3], [1, -1, 3], [1, 1, 3]], dtype=np.float32
        ),
    )
    before = runtime.budget.used
    created = []

    def failed_fit(runtime, reference, parameters, *, cancel):
        created.append(reference)
        raise RuntimeError(stage)

    if stage == "fit":
        monkeypatch.setattr(module, "fit_plane", failed_fit)

        def cancel():
            pass
    else:
        original = module.fit_plane

        def completed_fit(*args, **kwargs):
            result = original(*args, **kwargs)
            created.append(result.items[0].support)
            return result

        monkeypatch.setattr(module, "fit_plane", completed_fit)

        def cancel():
            if created:
                raise RuntimeError("cancel")

    try:
        with pytest.raises(RuntimeError, match=stage):
            fit_supported_plane(runtime, cloud, configured(), cancel=cancel)
        assert runtime.budget.used == before
        with runtime.borrow(cloud):
            pass
        with pytest.raises(InvalidRequestError):
            with runtime.borrow(created[0]):
                pass
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def test_inline_rejects_coordinates_dependencies_and_budget_without_leak():
    from tests.point_cloud_support import policy

    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=np.array([[0, 0, 3], [1, 0, 3], [0, 1, 3]], dtype=np.float32),
        runtime_policy=policy().model_copy(update={"max_working_bytes": 1}),
    )
    before = runtime.budget.used
    try:
        with pytest.raises(InvalidRequestError, match="预算"):
            fit_supported_plane(runtime, cloud, configured(), cancel=lambda: None)
        assert runtime.budget.used == before
        wrong = support()
        wrong["roi"]["frame_id"] = "other"
        with pytest.raises(InvalidRequestError, match="坐标"):
            fit_supported_plane(
                runtime,
                cloud,
                PlaneNodeParameters(settings=plane_parameters(), support=wrong),
                cancel=lambda: None,
            )
        with pytest.raises(ValidationError):
            PlaneNodeParameters(settings=plane_parameters(), support={"kind": "input"})
    finally:
        assert not scope.close()


def test_union_support_save_restore_keeps_original_rows(tmp_path):
    """内置并集沿同一资产链保存，释放原运行后仍能精确恢复支持。"""
    from dataclasses import replace
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
        read_asset_bundle,
        save_cloud,
    )
    from tests.point_cloud_support import create_resource_service, policy
    from tests.test_metrology3d_roi_union import boxes, union
    from tests.test_point_cloud_assets import POLICY

    assets = replace(POLICY, chunk_bytes=128)

    points = np.array(
        [[x, y, 0] for x in range(-2, 8) for y in (-1, 0, 1, 2)], dtype=np.float32
    )
    expected = np.flatnonzero(
        (points[:, 1] <= 1)
        & (
            ((points[:, 0] >= -1) & (points[:, 0] <= 2))
            | ((points[:, 0] >= 4) & (points[:, 0] <= 6))
        )
    )
    settings = PlaneNodeParameters(
        settings=plane_parameters(),
        support=dict(
            kind="parameters",
            roi=union("patches", "left", "overlap", "right"),
            bounds=boxes(),
        ),
    )
    scope, runtime, cloud = make_cloud(
        unit="mm",
        coordinates=points,
        attributes=[("label", np.arange(len(points), dtype=np.uint64) + 2**63, "1")],
        runtime_policy=policy(max_working_bytes=32768),
    )
    service = create_resource_service(tmp_path)
    try:
        features = fit_supported_plane(runtime, cloud, settings, cancel=lambda: None)
        assert features.items[0].valid
        asset = save_cloud(
            runtime,
            features.items[0].support,
            service=service,
            project_id="test",
            mode="derived",
            name="inline-plane",
            write_identity="d" * 64,
            policy=assets,
            cancel=lambda: None,
        )
        geometry = features.items[0].geometry
        method = features.items[0].support.provenance.method
    finally:
        assert not scope.close() and runtime.budget.used == 0

    restored_scope = ResourceScope(kind="test")
    restored_runtime = get_cloud_runtime(
        restored_scope, run_id="restored-plane", policy=policy(max_working_bytes=32768)
    )
    try:
        root, _, _ = read_asset_bundle(
            restored_runtime,
            asset,
            service=service,
            project_id="test",
            policy=assets,
            cancel=lambda: None,
        )
        # 资产保留历史方法；恢复后的运行引用不冒用历史父链。
        assert (
            service.read(asset, project_id="test").content.point_cloud.provenance.method
            == method
        )
        feature = fit_plane(
            restored_runtime, root, settings.settings, cancel=lambda: None
        ).items[0]
        assert feature.valid and feature.geometry == geometry
        assert feature.support.observation_id == root.observation_id
        assert restored_runtime.source_point_count(feature.support) == len(points)
        with restored_runtime.borrow(feature.support) as view:
            for i, source_index in enumerate(expected):
                np.testing.assert_array_equal(
                    view.source_indices(i, i + 1), [source_index]
                )
                np.testing.assert_array_equal(
                    view.chunk(i, i + 1)["positions"],
                    points[source_index : source_index + 1],
                )
                assert int(view.chunk(i, i + 1)["label"][0, 0]) == 2**63 + int(
                    source_index
                )
    finally:
        assert not restored_scope.close() and restored_runtime.budget.used == 0
