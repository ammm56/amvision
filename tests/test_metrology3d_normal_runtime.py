"""计算法向运行身份、状态、保存和转换，不把内核测试冒充公开节点验收。"""

from io import BytesIO
from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.cloud_normal_info import NORMAL_FIELDS
from backend.contracts.workflows.point_cloud_runtime import NormalizeCloudUnits
from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.point_cloud.normal_fields import (
    validate_normal_arrays,
)
from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.normalize_units import normalize_units
from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud
from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
from custom_nodes.metrology3d_nodes.shared.io.export_file import export_cloud_file
from tests.test_metrology3d_normal_estimation import parameters
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_metrology3d_resample import parameters as resample_parameters
from tests.test_metrology3d_transform import cloud_pose
from tests.test_point_cloud_assets import POLICY
from tests.point_cloud_support import create_resource_service, policy

ASSET_POLICY = replace(POLICY, chunk_bytes=256)


def fixture(unit="mm", dtype="f4", **kwargs):
    """独立平面及 uint64 原始字段，预算仅属于测试。"""
    xy = np.array([(x, y) for x in range(5) for y in range(5)], dtype=dtype)
    xyz = np.column_stack((xy, xy[:, 0] * 0.25 - xy[:, 1] * 0.5 + 2)).astype(dtype)
    return make_cloud(
        unit=unit,
        coordinates=xyz,
        attributes=(("label", np.arange(25, dtype="u8") + 2**53 + 1, "1"),),
        runtime_policy=policy(
            max_working_bytes=2_000_000,
            max_live_array_bytes=2_000_000,
            chunk_rows=32,
            **kwargs,
        ),
    )


def compute(runtime, source, **kwargs):
    """每个测试明确选择参数，不修改生产默认值。"""
    return estimate_normals(
        runtime,
        source,
        parameters(
            frame_id=source.spatial.frame_id,
            length_unit=source.spatial.length_unit,
            **kwargs,
        ),
        cancel=lambda: None,
    )


@pytest.mark.parametrize("dtype", ["f4", "f8"])
def test_normal_source_save_transform_units_and_subset(tmp_path, dtype):
    scope, runtime, source = fixture(unit="m", dtype=dtype)
    try:
        result, summary = compute(
            runtime,
            source,
            orientation=dict(
                kind="viewpoint",
                position=[0, 0, 100],
                facing="toward",
                min_abs_cosine=0.1,
            ),
        )
        assert summary["valid_count"] == 25 and summary["oriented_count"] == 25
        info = result.normal_info
        assert info.support.cloud_id == source.cloud_id
        normalized = normalize_units(
            runtime, result, NormalizeCloudUnits(), cancel=lambda: None
        )
        assert normalized.normal_info.method == info.method
        assert normalized.normal_info.orientation.position == (0, 0, 100000)
        assert normalized.normal_info.length_unit == "mm"
        with runtime.borrow(result) as a, runtime.borrow(normalized) as b:
            np.testing.assert_array_equal(
                a.chunk(0, 25)["label"], b.chunk(0, 25)["label"]
            )
            np.testing.assert_allclose(
                b.chunk(0, 25)["normal_rms"],
                a.chunk(0, 25)["normal_rms"] * 1000,
                rtol=1e-7,
            )
        _, pose = cloud_pose(runtime, normalized)
        transformed = transform_cloud(runtime, normalized, pose, cancel=lambda: None)
        matrix = np.asarray(pose.transform.matrix)
        np.testing.assert_allclose(
            transformed.normal_info.orientation.position,
            matrix[:3, :3] @ [0, 0, 100000] + matrix[:3, 3],
        )
        subset, _ = resample_cloud(
            runtime, transformed, resample_parameters("stride"), cancel=lambda: None
        )
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            subset,
            service=service,
            project_id="test",
            name="normals",
            mode="derived",
            write_identity="a" * 64,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        assert restored.normal_info == subset.normal_info
        assert restored.normal_info.support == info.support
        with runtime.borrow(subset) as a, runtime.borrow(restored) as b:
            np.testing.assert_array_equal(
                a.source_indices(0, subset.point_count),
                b.source_indices(0, restored.point_count),
            )
            for key, values in a.chunk(0, subset.point_count).items():
                np.testing.assert_array_equal(
                    values, b.chunk(0, restored.point_count)[key]
                )
        broken = restored.model_dump(mode="json")
        broken["fields"] = [f for f in broken["fields"] if f["name"] != "normal_valid"]
        with pytest.raises(ValidationError, match="字段或状态"):
            type(restored).model_validate(broken)
        with pytest.raises(InvalidRequestError, match="替换"):
            compute(runtime, restored)
        replaced, _ = compute(
            runtime, restored, existing_normals="replace", diagnostics=False
        )
        assert len([f for f in replaced.fields if f.name in NORMAL_FIELDS]) == 4
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_generated_normals_keep_voxel_lineage_and_asset(tmp_path):
    scope, runtime, source = fixture()
    try:
        p = resample_parameters("voxel-centroid")
        p = p.model_copy(
            update={
                "settings": p.settings.model_copy(
                    update={"frame_id": source.spatial.frame_id, "voxel_size": 0.5}
                )
            }
        )
        cloud, _ = resample_cloud(runtime, source, p, cancel=lambda: None)
        result, _ = compute(runtime, cloud)
        assert (
            result.sample_origin == "estimated"
            and result.voxel_grid == cloud.voxel_grid
        )
        with runtime.borrow(result) as view:
            with pytest.raises(InvalidRequestError, match="唯一原始行号"):
                view.source_indices(0, 1)
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            result,
            service=service,
            project_id="test",
            name="centroid-normals",
            mode="derived",
            write_identity="b" * 64,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        with runtime.borrow(result) as a, runtime.borrow(restored) as b:
            for name, values in a.lineage_chunk(0, result.point_count).items():
                np.testing.assert_array_equal(
                    values, b.lineage_chunk(0, restored.point_count)[name]
                )
        assert restored.normal_info == result.normal_info
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


@pytest.mark.parametrize("bad", ["zero", "valid", "oriented", "reason", "rms"])
def test_normal_state_corruption_rejected(bad):
    scope, runtime, source = fixture()
    try:
        result, _ = compute(runtime, source)
        with runtime.borrow(result) as view:
            arrays = {k: v.copy() for k, v in view.chunk(0, 25).items()}
        if bad == "zero":
            arrays["normals"][0] = 0
        if bad == "valid":
            arrays["normal_valid"][0] = 0
        if bad == "oriented":
            arrays["normal_oriented"][0] = 0
        if bad == "reason":
            arrays["normal_reason"][0] = 5
        if bad == "rms":
            arrays["normal_rms"][0] = -1
        with pytest.raises(InvalidRequestError):
            validate_normal_arrays(
                arrays, result.normal_info, chunk_rows=3, cancel=lambda: None
            )
    finally:
        assert scope.close() == ()


def test_normal_preview_and_detail_keep_status(tmp_path):
    """预览和已保存叶块都携带逐点状态，计算失败不删除位置。"""
    from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
    from backend.service.application.workflows.point_cloud.detail_index import (
        prepare_index,
    )
    from tests.test_metrology3d_preview import preview_policy, decode
    from tests.test_point_cloud_details import detail_policy

    scope, runtime, source = fixture()
    try:
        cloud, _ = compute(runtime, source)
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=25, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        values = decode(body)
        assert body["normal_info"] == cloud.normal_info.model_dump(mode="json")
        assert values["normal_valid"].all() and values["normal_oriented"].all()
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="test",
            name="normal-preview",
            mode="derived",
            write_identity="d" * 64,
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=ASSET_POLICY,
            cancel=lambda: None,
        )
        index = prepare_index(
            runtime,
            restored,
            service=service,
            project_id="test",
            policy=detail_policy(),
            cancel=lambda: None,
        )
        assert index.normal_info == cloud.normal_info
        assert set(NORMAL_FIELDS) <= {f.name for f in index.fields}
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_export_requires_status_or_entirely_oriented_vectors():
    scope, runtime, source = fixture()
    try:
        result, _ = compute(runtime, source, orientation={"kind": "unoriented"})
        options = dict(
            profile_id="ply-ascii",
            profile_version=1,
            fields=["positions", "normals"],
            file_name="normals.ply",
            spatial_acknowledged=True,
        )
        with pytest.raises(InvalidRequestError, match="原因字段"):
            export_cloud_file(
                runtime,
                result,
                options,
                stream=BytesIO(),
                max_output_bytes=100000,
                cancel=lambda: None,
            )
        out = BytesIO()
        with pytest.raises(InvalidRequestError, match="未定向"):
            export_cloud_file(
                runtime,
                result,
                {**options, "profile_id": "xyzn-whitespace"},
                stream=out,
                max_output_bytes=100000,
                cancel=lambda: None,
            )
        assert out.getvalue() == b""
        summary, _ = export_cloud_file(
            runtime,
            result,
            {
                **options,
                "fields": [
                    "positions",
                    "normals",
                    "normal_valid",
                    "normal_oriented",
                    "normal_reason",
                ],
            },
            stream=out,
            max_output_bytes=100000,
            cancel=lambda: None,
        )
        assert (
            summary["normal_info_preserved"] is False
            and b"normal_valid" in out.getvalue()
        )
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0


def test_normal_cancel_every_checkpoint_and_budget():
    scope, runtime, source = fixture()
    before, calls = runtime.budget.used, 0

    def count():
        nonlocal calls
        calls += 1

    try:
        p = parameters(frame_id=source.spatial.frame_id)
        estimate_normals(runtime, source, p, cancel=count)
        for stop in range(1, calls + 1):
            used, seen = runtime.budget.used, 0

            def cancel():
                nonlocal seen
                seen += 1
                if seen == stop:
                    raise InterruptedError()

            with pytest.raises(InterruptedError):
                estimate_normals(runtime, source, p, cancel=cancel)
            assert runtime.budget.used == used
        runtime.policy = runtime.policy.model_copy(update={"max_working_bytes": 256})
        with pytest.raises(InvalidRequestError, match="工作预算"):
            estimate_normals(runtime, source, p, cancel=lambda: None)
        assert before > 0
    finally:
        assert scope.close() == ()
    assert runtime.budget.used == 0
