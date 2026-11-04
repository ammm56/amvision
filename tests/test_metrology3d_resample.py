"""重采样的独立逐行、成员、精度、存读和回收真值。"""

from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.resample import (
    resample_cloud,
    voxel_resample,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.test_metrology3d_denoise import fixture
from tests.test_point_cloud_assets import POLICY
from tests.point_cloud_support import create_resource_service, policy
from tests.test_point_cloud_runtime import method, own


def parameters(kind):
    """仅本测试的显式格距和量化限值，不是默认生产配置。"""
    return ResampleCloudParameters(
        settings=(
            dict(kind=kind, every_k_points=2, offset=1)
            if kind == "stride"
            else dict(
                kind=kind,
                voxel_size=2.0,
                grid_origin=(0.0, 0.0, 0.0),
                frame_id="sensor",
                length_unit="mm",
                **(
                    dict(max_position_error=1e-5, attributes="positions-only")
                    if kind == "voxel-centroid"
                    else {}
                ),
            )
        )
    )


@pytest.mark.parametrize("kind", ["stride", "voxel-representative", "voxel-centroid"])
def test_runtime_identity_fields_and_save_restore(tmp_path, kind):
    scope, runtime, source, arrays = fixture()
    p = parameters(kind)
    if kind != "stride":
        p = ResampleCloudParameters(
            settings={**p.settings.model_dump(), "frame_id": source.spatial.frame_id}
        )
    try:
        out, summary = resample_cloud(runtime, source, p, cancel=lambda: None)
        assert summary["input_count"] == 6
        if kind != "voxel-centroid":
            with runtime.borrow(out) as view:
                selected = view.source_indices(0, out.point_count)
                for key in arrays:
                    assert (
                        view.chunk(0, out.point_count)[key].tobytes()
                        == arrays[key][selected].tobytes()
                    )
                if kind == "stride":
                    np.testing.assert_array_equal(selected, [1, 3, 5])
        else:
            assert (
                out.lineage_kind == "voxel-aggregate"
                and out.sample_origin == "estimated"
            )
            with runtime.borrow(out) as view:
                saved = {
                    k: v.copy()
                    for k, v in view.lineage_chunk(0, out.point_count).items()
                }
                np.testing.assert_array_equal(
                    np.sort(saved["source_rows"][:, 0]), np.arange(6)
                )
                with pytest.raises(InvalidRequestError, match="唯一"):
                    view.source_indices(0, 1)
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            out,
            service=service,
            project_id="test",
            mode="derived",
            name="sample",
            write_identity="b" * 64,
            policy=replace(POLICY, chunk_bytes=37),
            cancel=lambda: None,
        )
        from io import BytesIO

        archive = BytesIO()
        service.export_cloud_archive(
            asset, project_id="test", stream=archive, policy=POLICY, cancel=lambda: None
        )
        imported = service.import_cloud_archive(
            stream=archive,
            project_id="other",
            name="Imported",
            write_identity="c" * 64,
            policy=POLICY,
            cancel=lambda: None,
        )
        imported_cloud = read_asset(
            runtime,
            imported.reference,
            service=service,
            project_id="other",
            policy=POLICY,
            cancel=lambda: None,
        )
        with runtime.borrow(out) as a, runtime.borrow(imported_cloud) as b:
            np.testing.assert_array_equal(
                a.chunk(0, out.point_count)["positions"],
                b.chunk(0, out.point_count)["positions"],
            )
            if kind == "voxel-centroid":
                for key in saved:
                    np.testing.assert_array_equal(
                        b.lineage_chunk(0, out.point_count)[key], saved[key]
                    )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=replace(POLICY, chunk_bytes=37),
            cancel=lambda: None,
        )
        assert runtime.source_point_count(restored) == 6
        assert restored.lineage_kind == out.lineage_kind
        assert restored.voxel_aggregation == out.voxel_aggregation
        assert imported_cloud.voxel_aggregation == out.voxel_aggregation
        with runtime.borrow(out) as a, runtime.borrow(restored) as b:
            for key in a.chunk(0, out.point_count):
                assert (
                    a.chunk(0, out.point_count)[key].tobytes()
                    == b.chunk(0, out.point_count)[key].tobytes()
                )
            if kind == "voxel-centroid":
                for key in saved:
                    np.testing.assert_array_equal(
                        b.lineage_chunk(0, out.point_count)[key], saved[key]
                    )
    finally:
        scope.close()
    assert runtime.budget.used == 0


@pytest.mark.parametrize("rows", [1, 3, 100])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_independent_voxel_truth_and_boundaries(rows, dtype):
    points = np.array(
        [
            [-2, 0, 0],
            [-1.75, 0, 0],
            [0, 0, 0],
            [1, 0, 0],
            [2, 0, 0],
            [2.25, 0, 0],
            [0, 0, 0],
        ],
        dtype=dtype,
    )
    points = np.vstack(
        [
            points,
            [np.nextafter(np.array(2, dtype=dtype), np.array(0, dtype=dtype)), 0, 0],
        ]
    ).astype(dtype)
    identities = np.array([9, 5, 4, 7, 1, 3, 8, 12], dtype=np.uint64)
    p = parameters("voxel-centroid")
    result = voxel_resample(
        points,
        identities,
        p.settings,
        max_working_bytes=1_000_000,
        chunk_rows=rows,
        cancel=lambda: None,
    )
    expected = {}
    for i, point in enumerate(points):
        key = tuple(int(np.floor(float(x) / 2)) for x in point)
        expected.setdefault(key, []).append(i)
    for cell, key in enumerate(sorted(expected)):
        members = sorted(expected[key], key=lambda i: int(identities[i]))
        np.testing.assert_array_equal(result["voxel_keys"][cell], key)
        lo, hi = result["member_offsets"][cell : cell + 2, 0]
        np.testing.assert_array_equal(result["source_rows"][lo:hi], identities[members])
        mean = np.array(
            [
                sum(float(points[i, axis]) for i in members) / len(members)
                for axis in range(3)
            ],
            dtype=dtype,
        )
        np.testing.assert_array_equal(result["positions"][cell], mean)


def test_subset_keeps_initial_rows_and_generated_subset_lineage():
    scope, runtime, source, _ = fixture()
    try:
        parent = runtime.register_subset(
            parent=source,
            method=method(),
            indices=own(runtime, {"indices": np.array([[1], [3], [5]], dtype="u4")}),
            cancel=lambda: None,
        )
        p = parameters("voxel-centroid")
        p = ResampleCloudParameters(
            settings={**p.settings.model_dump(), "frame_id": source.spatial.frame_id}
        )
        generated, _ = resample_cloud(runtime, parent, p, cancel=lambda: None)
        selected, _ = resample_cloud(
            runtime, generated, parameters("stride"), cancel=lambda: None
        )
        with runtime.borrow(selected) as view:
            np.testing.assert_array_equal(
                view.lineage_chunk(0, 1)["source_rows"][:, 0], [3]
            )
        assert runtime.source_point_count(selected) == 6
        with pytest.raises(InvalidRequestError, match="实测"):
            resample_cloud(runtime, generated, p, cancel=lambda: None)
    finally:
        scope.close()


def test_contract_rejects_ambiguous_or_invalid_parameters():
    for values in (
        dict(kind="stride", every_k_points=0, offset=0),
        dict(kind="stride", every_k_points=2, offset=2),
        dict(kind="stride", every_k_points=True, offset=0),
    ):
        with pytest.raises(ValidationError):
            ResampleCloudParameters(settings=values)
    with pytest.raises(ValidationError):
        ResampleCloudParameters(
            settings={
                **parameters("voxel-centroid").settings.model_dump(),
                "attributes": "average-all",
            }
        )


@pytest.mark.parametrize("kind", ["stride", "voxel-representative", "voxel-centroid"])
def test_cancel_each_checkpoint_reclaims_storage(kind):
    reached = False
    for at in range(1, 150):
        scope, runtime, source, _ = fixture(
            policy(max_working_bytes=1_000_000, chunk_rows=2)
        )
        initial, calls = runtime.budget.used, 0
        p = parameters(kind)
        if kind != "stride":
            p = ResampleCloudParameters(
                settings={
                    **p.settings.model_dump(),
                    "frame_id": source.spatial.frame_id,
                }
            )

        def cancel():
            nonlocal calls
            calls += 1
            if calls == at:
                raise RuntimeError("cancel")

        try:
            try:
                resample_cloud(runtime, source, p, cancel=cancel)
                reached = True
            except RuntimeError as error:
                assert str(error) == "cancel"
                assert runtime.budget.used == initial
            with runtime.borrow(source) as view:
                assert len(view.chunk(0, 1)["positions"]) == 1
        finally:
            scope.close()
        assert runtime.budget.used == 0
        if reached:
            break
    assert reached


def test_budget_and_duplicate_source_rejection():
    p = parameters("voxel-centroid").settings
    points = np.zeros((3, 3), dtype="f4")
    for budget, ids, match in ((500, [1, 2, 3], "预算"), (100000, [1, 1, 2], "重复")):
        with pytest.raises(InvalidRequestError, match=match):
            voxel_resample(
                points,
                np.array(ids, dtype="u8"),
                p,
                max_working_bytes=budget,
                chunk_rows=10,
                cancel=lambda: None,
            )


def test_voxel_preview_has_bounded_keys_and_counts_not_member_json():
    from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
    from tests.test_metrology3d_preview import decode, preview_policy

    scope, runtime, source, _ = fixture()
    try:
        p = parameters("voxel-centroid")
        p = ResampleCloudParameters(
            settings={**p.settings.model_dump(), "frame_id": source.spatial.frame_id}
        )
        out, _ = resample_cloud(runtime, source, p, cancel=lambda: None)
        body = build_cloud_preview(
            runtime,
            out,
            dict(point_limit=2, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        data = decode(body)
        assert body["lineage_kind"] == "voxel-aggregate"
        assert body["voxel_aggregation"] == out.voxel_aggregation.model_dump(
            mode="json"
        )
        np.testing.assert_array_equal(data["voxel_keys"], [[0, 0, 0], [20, 0, 0]])
        np.testing.assert_array_equal(data["member_counts"][:, 0], [4, 1])
        assert "source_rows" not in data
        # 最大允许扫描块不等于实际小云工作集，不能误报容量不足。
        from tests.integration.metrology3d.test_transport_full_sample import full_policy

        small = build_cloud_preview(
            runtime,
            out,
            dict(point_limit=1000, color=dict(mode="solid")),
            policy=full_policy().preview,
            cancel=lambda: None,
        )
        assert small["state"] == "ready"
        # 显示策略不能覆盖更小的 Run 工作预算；正文与扫描块要同时准入。
        from custom_nodes.metrology3d_nodes.shared.preview import _build_cloud_preview

        previous_policy = runtime.policy
        runtime.policy = previous_policy.model_copy(update={"max_working_bytes": 512})
        try:
            limited = _build_cloud_preview(
                runtime,
                out,
                dict(point_limit=1000, color=dict(mode="solid")),
                policy=full_policy().preview,
                cancel=lambda: None,
            )
            assert (
                limited["state"] == "unavailable"
                and limited["reason"] == "preview_size_limit"
            )
        finally:
            runtime.policy = previous_policy
    finally:
        scope.close()


def test_empty_and_forged_references():
    scope, runtime, source, _ = fixture()
    try:
        huge, _ = resample_cloud(
            runtime,
            source,
            ResampleCloudParameters(
                settings=dict(kind="stride", every_k_points=2**53 - 1, offset=0)
            ),
            cancel=lambda: None,
        )
        with runtime.borrow(huge) as view:
            np.testing.assert_array_equal(view.source_indices(0, 1), [0])
        empty, _ = resample_cloud(
            runtime,
            source,
            ResampleCloudParameters(
                settings=dict(kind="stride", every_k_points=10, offset=9)
            ),
            cancel=lambda: None,
        )
        p = parameters("voxel-centroid")
        p = ResampleCloudParameters(
            settings={**p.settings.model_dump(), "frame_id": source.spatial.frame_id}
        )
        out, _ = resample_cloud(runtime, empty, p, cancel=lambda: None)
        assert out.point_count == 0
        with runtime.borrow(out) as view:
            np.testing.assert_array_equal(
                view.lineage_chunk(0, 0)["member_offsets"], [[0]]
            )
        for changed in (dict(run_id="another"), dict(point_count=5)):
            with pytest.raises(InvalidRequestError):
                resample_cloud(
                    runtime, source.model_copy(update=changed), p, cancel=lambda: None
                )
    finally:
        scope.close()


def test_quantization_limit_and_large_original_rows():
    """真实 uint64 身份不经 double；不可表达的质心必须受精度上限约束。"""
    p = parameters("voxel-centroid").settings.model_copy(
        update={"voxel_size": 1e9, "max_position_error": 0.25}
    )
    points = np.array([[1e8, 0, 0], [1e8 + 8, 0, 0]], dtype="f4")
    ids = np.array([2**53 + 1, 2**53 + 3], dtype="u8")
    with pytest.raises(InvalidRequestError, match="回写误差"):
        voxel_resample(
            points, ids, p, max_working_bytes=100000, chunk_rows=2, cancel=lambda: None
        )
    result = voxel_resample(
        points.astype("f8"),
        ids,
        p,
        max_working_bytes=100000,
        chunk_rows=2,
        cancel=lambda: None,
    )
    np.testing.assert_array_equal(result["source_rows"], ids)
    assert result["positions"][0, 0] == 100000004


def test_voxel_grid_survives_transform_subset_and_asset(tmp_path):
    """原聚合格属于原 frame，不被最后一次变换或采样参数覆盖。"""
    from tests.test_metrology3d_transform import cloud_pose
    from tests.test_metrology3d_preprocess import make_cloud
    from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud

    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=np.array([[1, 2, 3], [2, 2, 3], [1, 3, 3], [2, 3, 3]], dtype="f4"),
        runtime_policy=policy(chunk_bytes=256),
    )
    try:
        _, pose = cloud_pose(runtime, source)
        p = ResampleCloudParameters(
            settings={
                **parameters("voxel-centroid").settings.model_dump(),
                "frame_id": source.spatial.frame_id,
                "voxel_size": 0.75,
            }
        )
        centroid, _ = resample_cloud(runtime, source, p, cancel=lambda: None)
        transformed = transform_cloud(runtime, centroid, pose, cancel=lambda: None)
        subset, _ = resample_cloud(
            runtime, transformed, parameters("stride"), cancel=lambda: None
        )
        assert subset.spatial.frame_id == "part"
        assert subset.voxel_aggregation == centroid.voxel_aggregation
        assert (
            subset.voxel_aggregation.parameters.settings.frame_id
            == source.spatial.frame_id
        )
        service = create_resource_service(tmp_path)
        asset = save_cloud(
            runtime,
            subset,
            service=service,
            project_id="test",
            mode="derived",
            name="transformed",
            write_identity="d" * 64,
            policy=replace(POLICY, chunk_bytes=37),
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=replace(POLICY, chunk_bytes=37),
            cancel=lambda: None,
        )
        assert restored.voxel_aggregation == centroid.voxel_aggregation
        assert runtime.source_point_count(restored) == 4
        with runtime.borrow(subset) as a, runtime.borrow(restored) as b:
            np.testing.assert_array_equal(
                a.chunk(0, 2)["positions"], b.chunk(0, 2)["positions"]
            )
            for key in a.lineage_chunk(0, 2):
                np.testing.assert_array_equal(
                    a.lineage_chunk(0, 2)[key], b.lineage_chunk(0, 2)[key]
                )
        raw = restored.model_dump(mode="json")
        raw["voxel_aggregation"]["parameters"]["settings"]["grid_origin"] = [1, 0, 0]
        with pytest.raises(ValidationError, match="摘要"):
            type(restored).model_validate(raw)
    finally:
        scope.close()
    assert runtime.budget.used == 0


@pytest.mark.parametrize(
    "bad", ["offset", "empty", "duplicate", "range", "key", "dtype"]
)
def test_bad_voxel_lineage_rejected(bad):
    """持久来源在正式运行读取时检查完整 CSR，包括跨格重复计入。"""
    from backend.service.application.workflows.point_cloud.voxel_lineage import (
        validate_voxel_lineage,
    )

    data = dict(
        voxel_keys=np.array([[0, 0, 0], [1, 0, 0]], dtype="<i8"),
        member_offsets=np.array([[0], [2], [3]], dtype="<u8"),
        source_rows=np.array([[0], [1], [2]], dtype="<u4"),
    )
    if bad == "offset":
        data["member_offsets"][0] = 1
    if bad == "empty":
        data["member_offsets"][1] = 0
    if bad == "duplicate":
        data["source_rows"][2] = 0
    if bad == "range":
        data["source_rows"][2] = 3
    if bad == "key":
        data["voxel_keys"][1] = data["voxel_keys"][0]
    if bad == "dtype":
        data["source_rows"] = data["source_rows"].astype("f8")
    for a in data.values():
        a.setflags(write=False)
    with pytest.raises(InvalidRequestError):
        validate_voxel_lineage(
            data,
            point_count=2,
            source_point_count=3,
            policy=policy(),
            cancel=lambda: None,
        )
