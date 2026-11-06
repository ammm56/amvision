"""B07 原行表所有权、跨代资产与搬运；通过真实存储核对空行而非只看 XYZ。"""

from contextlib import contextmanager
from dataclasses import replace
from io import BytesIO
from hashlib import sha256
import weakref

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.measurement_resources import MeasurementResourceContent
from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.contracts.workflows.profile3d import ProfileBufferDescriptor
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.point_cloud.profile_buffer import (
    profile_descriptor_sha256,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)
from custom_nodes.metrology3d_nodes.shared.io.read_profiles import (
    read_profile_local,
    read_profile_reference,
)
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from tests.point_cloud_support import policy, create_resource_service
from tests.test_metrology3d_profile_conversion import specification, inputs
from tests.test_metrology3d_profile_io import encode
from tests.test_metrology3d_profile_buffer import arena_input as arena_input, descriptor
from tests.test_metrology3d_raster_runtime import save, restored, package_roundtrip
from tests.test_metrology3d_raster_runtime import POLICY
from tests.integration.metrology3d.test_file_read import publish


@pytest.fixture
def context(tmp_path):
    """仅限测试的显式容量，覆盖 NPZ 元数据与多代对象，不成为节点默认。"""
    scope = ResourceScope(kind="profiles-runtime")
    runtime = get_cloud_runtime(
        scope,
        run_id="profiles-test",
        policy=policy(
            max_decoded_bytes=1024**2,
            max_working_bytes=4 * 1024**2,
            max_live_array_bytes=8 * 1024**2,
            chunk_rows=16,
        ),
    )
    try:
        yield runtime, create_resource_service(tmp_path)
    finally:
        assert scope.close() == ()
        assert runtime.budget.used == 0


@contextmanager
def guard(data):
    """内核输入字节守卫，真实 mmap 生命周期另由 arena 用例覆盖。"""
    with memoryview(data) as view:
        yield view


def source(
    runtime,
    service,
    *,
    entry="file",
    method="encoder-positions",
    cancel=lambda: None,
    invalid=True,
    planar=False,
    dtype="float32",
):
    """空轮廓保留特殊 NaN 位模式，非空轮廓保留倒向编码器。"""
    spec = (
        specification(
            dtype=dtype,
            displacement=dict(
                kind="encoder-positions", dtype="float64", scale=0.5, origin=10
            ),
        )
        if method == "encoder-positions"
        else specification(dtype=dtype)
    )
    if planar:
        spec = spec.model_copy(
            update={
                "x_direction": (1.0, 0.0, 0.0),
                "scan_direction": (0.0, 1.0, 0.0),
                "height_direction": (0.0, 0.0, 1.0),
            }
        )
    values = inputs(
        dtype=dtype, encoder=[12, 3, 8, 8] if method == "encoder-positions" else None
    )
    if method == "encoder-positions":
        encoder = values["encoder_positions"].copy()
        encoder.view("u8")[1] = 0x7FF8000000000123
        encoder.setflags(write=False)
        values["encoder_positions"] = encoder
    raw = values["profiles"].copy()
    if dtype == "float64":
        raw[1, 1] = np.nextafter(np.float64(1), np.float64(2))
    if planar:
        raw[:, 1] = 3
    if invalid:
        raw[0, 0] = np.nan
    raw.setflags(write=False)
    values["profiles"] = raw
    if entry == "file":
        ref, counts = read_profile_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=publish(service.storage, encode(values)),
            spec=spec,
            has_validity=False,
            cancel=cancel,
        )
    else:
        d = ProfileBufferDescriptor(
            format_id="amvision.profile-buffer.v1",
            profiles=spec,
            has_validity=False,
            content_length=spec.input_bytes(has_validity=False),
        )
        data = b"".join(
            values[name].tobytes()
            for name, _, _ in spec.input_layout(has_validity=False)
        )
        ref, counts = read_profile_local(
            runtime=runtime,
            descriptor=d,
            expected_descriptor_sha256=profile_descriptor_sha256(d),
            acquire_view=lambda: guard(data),
            cancel=cancel,
        )
    assert counts["valid"] == (5 if invalid else 6)
    return ref, values


def check_rows(runtime, ref, values):
    """逐字节核对包括空行的全部原行表；拒绝把当前点数当原始总数。"""
    spec = runtime.profile_source(ref).profiles
    assert runtime.source_point_count(ref) == 6
    with runtime.borrow_profile_rows(ref) as rows:
        assert set(rows) == {name for name, _, _ in spec.row_layout()}
        for name in rows:
            assert not rows[name].flags.writeable
            assert rows[name].tobytes() == values[name].tobytes()


@pytest.mark.parametrize("entry", ["file", "array"])
@pytest.mark.parametrize("mode", ["original", "derived"])
@pytest.mark.parametrize("method", ["fixed-step", "encoder-positions"])
@pytest.mark.parametrize("dtype", ["float32", "float64"])
def test_complete_row_table_survives_three_asset_generations(
    context, entry, mode, method, dtype
):
    runtime, service = context
    original, values = source(runtime, service, entry=entry, method=method, dtype=dtype)
    expected = runtime.profile_source(original)
    loaded = restored(runtime, save(runtime, original, service, mode, "a"), service)
    for identity in ("b", "c"):
        check_rows(runtime, loaded, values)
        filtered, _ = filter_valid(
            runtime,
            loaded,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        loaded = restored(
            runtime, save(runtime, filtered, service, "derived", identity), service
        )
        assert runtime.profile_source(loaded) == expected
        assert loaded.point_count == 5
        with runtime.borrow(loaded) as view:
            np.testing.assert_array_equal(view.source_indices(0, 5), [1, 2, 3, 4, 5])
            np.testing.assert_array_equal(
                view.chunk(0, 5)["acquisition_line_id"][:, 0], [3, 8, 8, 8, 9]
            )
            assert (
                view.chunk(0, 5)["raw_profile_x"][:, 0].tobytes()
                == values["profiles"][1:, 0].tobytes()
            )
            assert (
                view.chunk(0, 5)["raw_profile_height"][:, 0].tobytes()
                == values["profiles"][1:, 1].tobytes()
            )
    check_rows(runtime, loaded, values)


@pytest.mark.parametrize("kind", ["stride", "voxel-representative", "voxel-centroid"])
def test_resample_and_empty_environment_package_keep_rows(context, tmp_path, kind):
    from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
    from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
    from tests.test_metrology3d_resample import parameters

    runtime, service = context
    original, values = source(runtime, service, invalid=False)
    loaded = restored(
        runtime, save(runtime, original, service, "original", "a"), service
    )
    params = parameters(kind)
    if kind != "stride":
        params = ResampleCloudParameters(
            settings={
                **params.settings.model_dump(),
                "frame_id": loaded.spatial.frame_id,
            }
        )
    sampled, _ = resample_cloud(runtime, loaded, params, cancel=lambda: None)
    ref = save(runtime, sampled, service, "derived", "b")
    loaded = restored(runtime, ref, service)
    filtered, _ = filter_valid(
        runtime,
        loaded,
        FilterCloudValid(finite_fields=("positions",), sentinels=()),
        cancel=lambda: None,
    )
    ref = save(runtime, filtered, service, "derived", "c")
    roundtrip, content = package_roundtrip(runtime, ref, service, tmp_path)
    check_rows(runtime, roundtrip, values)
    assert runtime.profile_source(roundtrip) == runtime.profile_source(original)
    with runtime.borrow(sampled) as a, runtime.borrow(roundtrip) as b:
        for key, value in a.chunk(0, sampled.point_count).items():
            assert value.tobytes() == b.chunk(0, roundtrip.point_count)[key].tobytes()
        if kind == "voxel-centroid":
            with pytest.raises(InvalidRequestError, match="唯一"):
                b.source_indices(0, 1)
    bad = content.model_dump(mode="json")
    bad["point_cloud"]["blobs"] = [
        b for b in bad["point_cloud"]["blobs"] if b["role"] != "profile-rows"
    ]
    with pytest.raises(ValidationError, match="行表"):
        MeasurementResourceContent.model_validate(bad)


def test_actual_mmap_input_can_be_reclaimed_before_use(context, arena_input):
    runtime, _ = context
    arena, receipt, acquire = arena_input
    ref, _ = read_profile_local(
        runtime=runtime,
        descriptor=descriptor(),
        expected_descriptor_sha256=profile_descriptor_sha256(descriptor()),
        acquire_view=acquire,
        cancel=lambda: None,
    )
    assert arena.request_reclaim(receipt) == "released"
    check_rows(runtime, ref, inputs())
    with pytest.raises(ValidationError, match="frozen"):
        ref.source.profiles.calibration_revision = "tampered"
    ref = ref.model_copy(
        update={
            "source": ref.source.model_copy(
                update={
                    "profiles": ref.source.profiles.model_copy(
                        update={"calibration_revision": "tampered"}
                    ),
                }
            )
        }
    )
    with pytest.raises(InvalidRequestError):
        runtime.profile_source(ref)


@pytest.mark.parametrize("stop", [1, 15, 35, 70, 110])
def test_input_cancel_releases_points_and_row_table_before_scope_close(context, stop):
    runtime, service = context
    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stop:
            raise InterruptedError("profile input cancelled")

    with pytest.raises(InterruptedError):
        source(runtime, service, cancel=cancel)
    assert runtime.budget.used == 0


def test_profile_asset_bad_rows_rejected_even_with_matching_hash(context):
    runtime, service = context
    original, _ = source(runtime, service, entry="array")
    ref = save(runtime, original, service, "derived", "a")
    cloud = service.read(ref, project_id="test").content.point_cloud
    blob = next(b for b in cloud.blobs if b.role == "profile-rows")
    with service.storage.open_read_snapshot(
        cloud_blob_key(service, ref, blob)
    ) as snapshot:
        content = bytearray(snapshot.stream.read())
    content[:8] = np.uint64(1).tobytes()
    fake = blob.model_copy(update={"sha256": sha256(content).hexdigest()})
    stream = CheckedBlobStream(BytesIO(content), fake, lambda: None, cloud)
    with pytest.raises(InvalidRequestError, match="行偏移"):
        while stream.read(3):
            pass


def test_profile_rows_owner_blocks_premature_close(tmp_path):
    scope = ResourceScope(kind="profile-close-failed")
    runtime = get_cloud_runtime(scope, run_id="profile-close", policy=policy())
    service = create_resource_service(tmp_path)
    original, values = source(runtime, service, entry="array")
    with runtime.borrow_profile_rows(original) as rows:
        refs = [weakref.ref(a) for a in rows.values()]
        with pytest.raises(RuntimeError):
            runtime.close()
        assert rows["line_ids"].tobytes() == values["line_ids"].tobytes()
        assert runtime.budget.used > 0
        with pytest.raises(RuntimeError, match="不可用"):
            runtime.profile_source(original)
    # 关闭失败仍交给原有隔离边界；这里仅清理测试自己的已无借用存储。
    assert scope.close()
    assert runtime.storage_scope.close() == ()
    assert all(r() is None for r in refs)
    assert runtime.budget.used == 0


@pytest.mark.parametrize("entry", ["file", "array"])
def test_late_source_failure_releases_arrays_with_exception_held(
    context, monkeypatch, entry
):
    """已分配输出后元数据失败，不能等 Run 结束才归还内存。"""
    runtime, service = context
    # 管理 API 会按正式机制重载节点包，补丁必须命中此用例实际调用函数的命名空间。
    namespace = read_profile_reference.__globals__
    original = namespace["_convert"]
    refs = []

    def tracked(*args, **kwargs):
        result, rows, digest = original(*args, **kwargs)
        with result.arrays.borrow() as points, rows.borrow() as table:
            refs.extend(weakref.ref(a) for a in (*points.values(), *table.values()))
        return result, rows, digest

    def rejected(**kwargs):
        raise ValueError("source rejected after conversion")

    monkeypatch.setitem(namespace, "_convert", tracked)
    monkeypatch.setitem(namespace, "CloudProfileSource", rejected)
    with pytest.raises(ValueError) as held:
        source(runtime, service, entry=entry)
    assert held.value and refs and all(r() is None for r in refs)
    assert runtime.budget.used == 0


def test_guard_exit_failure_does_not_publish(arena_input, monkeypatch):
    scope = ResourceScope(kind="profile-input-close-failed")
    runtime = get_cloud_runtime(scope, run_id="profile-close", policy=policy())
    arena, receipt, acquire = arena_input
    published = []
    original = runtime.register_source

    def record(**kwargs):
        published.append(True)
        return original(**kwargs)

    @contextmanager
    def broken():
        with acquire() as view:
            yield view
        raise RuntimeError("input guard close failed")

    monkeypatch.setattr(runtime, "register_source", record)
    with pytest.raises(RuntimeError, match="guard close"):
        read_profile_local(
            runtime=runtime,
            descriptor=descriptor(),
            expected_descriptor_sha256=profile_descriptor_sha256(descriptor()),
            acquire_view=broken,
            cancel=lambda: None,
        )
    assert not published
    # guard 退出失败不能声称输入容量已回收；新输出已释放，只有输入保守计费。
    assert runtime.budget.used == descriptor().content_length
    assert scope.close() == ()
    assert arena.request_reclaim(receipt) == "released"


def test_joint_points_and_rows_decoded_budget(context):
    runtime, service = context
    spec = specification()
    point_bytes = spec.point_count * sum(
        np.dtype(f.dtype).itemsize * f.components
        for f in spec.cloud_fields(has_validity=False)
    )
    runtime.policy = runtime.policy.model_copy(
        update={"max_decoded_bytes": point_bytes}
    )
    with pytest.raises(InvalidRequestError, match="联合解码"):
        source(runtime, service, entry="array", method="fixed-step")
    assert runtime.budget.used == 0


def test_transformed_profile_asset_keeps_capture_and_current_frames(context):
    from tests.test_metrology3d_transform import cloud_pose
    from custom_nodes.metrology3d_nodes.shared.transform_cloud import transform_cloud

    runtime, service = context
    original, values = source(runtime, service, invalid=False, planar=True)
    loaded = restored(
        runtime, save(runtime, original, service, "original", "a"), service
    )
    _, pose = cloud_pose(runtime, loaded)
    moved = transform_cloud(runtime, loaded, pose, cancel=lambda: None)
    result = restored(runtime, save(runtime, moved, service, "derived", "b"), service)
    check_rows(runtime, result, values)
    assert runtime.profile_source(result) == runtime.profile_source(original)
    assert (
        result.spatial.frame_id
        != runtime.profile_source(result).profiles.spatial.frame_id
    )
    with runtime.borrow(loaded) as before, runtime.borrow(result) as after:
        matrix = np.asarray(pose.transform.matrix)
        np.testing.assert_allclose(
            after.chunk(0, 6)["positions"],
            before.chunk(0, 6)["positions"] @ matrix[:3, :3].T + matrix[:3, 3],
            atol=1e-6,
        )


@pytest.mark.parametrize("failure", ["cancel", "budget", "project"])
def test_save_failure_leaves_source_and_no_partial_resource(context, failure):
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud

    runtime, service = context
    original, values = source(runtime, service)
    original = restored(
        runtime, save(runtime, original, service, "original", "a"), service
    )
    used = runtime.budget.used

    def cancel():
        if failure == "cancel":
            raise InterruptedError("cancel save")

    with pytest.raises((InterruptedError, InvalidRequestError)):
        save_cloud(
            runtime,
            original,
            service=service,
            project_id="other" if failure == "project" else "test",
            name="fail",
            mode="derived",
            write_identity="b" * 64,
            policy=replace(POLICY, max_asset_bytes=128, chunk_bytes=64)
            if failure == "budget"
            else POLICY,
            cancel=cancel,
        )
    assert len(service.list_versions(project_id="test")) == 1
    assert service.list_versions(project_id="other") == []
    assert runtime.budget.used == used
    check_rows(runtime, original, values)


@pytest.mark.parametrize("stop", [5, 12, 20, 35, 45])
def test_restore_cancel_releases_new_arrays_and_keeps_parent(
    context, monkeypatch, stop
):
    from custom_nodes.metrology3d_nodes.shared import cloud_assets

    runtime, service = context
    original, values = source(runtime, service, entry="array")
    ref = save(runtime, original, service, "derived", "a")
    used, refs, calls = runtime.budget.used, [], 0
    empty = cloud_assets.np.empty

    def tracked(*args, **kwargs):
        result = empty(*args, **kwargs)
        refs.append(weakref.ref(result))
        return result

    def cancel():
        nonlocal calls
        calls += 1
        if calls == stop:
            raise InterruptedError("cancel restore")

    monkeypatch.setattr(cloud_assets.np, "empty", tracked)
    with pytest.raises(InterruptedError) as held:
        cloud_assets.read_asset(
            runtime,
            ref,
            service=service,
            project_id="test",
            policy=POLICY,
            cancel=cancel,
        )
    assert held.value and all(r() is None for r in refs)
    assert runtime.budget.used == used
    check_rows(runtime, original, values)
