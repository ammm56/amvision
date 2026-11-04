"""去噪用独立距离矩阵真值，不用被测空间树生成期望值。"""

from dataclasses import replace

import numpy as np
import pytest
from pydantic import ValidationError

from backend.contracts.workflows.cloud_preprocess import DenoiseCloudParameters
from backend.contracts.workflows.point_cloud import CloudField
from backend.contracts.workflows.point_cloud_runtime import CloudLocalSource
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.denoise import denoise_mask, denoise_cloud
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.point_cloud_support import policy, spatial, create_resource_service
from tests.test_point_cloud_runtime import own
from tests.test_point_cloud_assets import POLICY


def parameters(kind):
    """解析例阈值只在测试使用，不是生产默认值。"""
    return DenoiseCloudParameters(
        settings=(
            dict(kind=kind, neighbors=3, std_ratio=1)
            if kind == "statistical"
            else dict(kind=kind, radius=1.01, min_neighbors=2)
        )
    )


def points():
    """重复点、等距点、细线与孤立点共同覆盖自身邻居排除。"""
    return np.array(
        [[0, 0, 0], [0, 0, 0], [1, 0, 0], [2, 0, 0], [1, 1, 0], [40, 0, 0]],
        dtype=np.float32,
    )


@pytest.mark.parametrize("kind", ["statistical", "radius"])
@pytest.mark.parametrize("rows", [1, 2, 100])
def test_exact_neighbors_and_chunk_invariance(kind, rows):
    values, p = points(), parameters(kind)
    distances = np.linalg.norm(
        values[:, None, :].astype(float) - values[None, :, :], axis=2
    )
    np.fill_diagonal(distances, np.inf)
    if kind == "statistical":
        means = np.sort(distances, axis=1)[:, : p.settings.neighbors].mean(axis=1)
        expected = means <= means.mean() + p.settings.std_ratio * means.std(ddof=0)
    else:
        expected = (distances <= p.settings.radius).sum(
            axis=1
        ) >= p.settings.min_neighbors
    actual, _ = denoise_mask(
        values,
        p.settings,
        max_working_bytes=1_000_000,
        chunk_rows=rows,
        cancel=lambda: None,
    )
    np.testing.assert_array_equal(actual, expected)


def fixture(limits=None):
    """颜色和大整数属性与源行号不得被空间算法改写。"""
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(
        scope,
        run_id="denoise",
        policy=limits or policy(max_working_bytes=1_000_000, chunk_rows=10),
    )
    arrays = dict(
        positions=points(), serial=np.arange(6, dtype=np.uint64).reshape(-1, 1) + 2**60
    )
    cloud = runtime.register_source(
        owner=own(runtime, arrays),
        point_count=6,
        fields=(
            CloudField(
                name="positions",
                semantic="position",
                dtype="float32",
                components=3,
                unit=None,
            ),
            CloudField(
                name="serial",
                semantic="scalar",
                dtype="uint64",
                components=1,
                unit=None,
            ),
        ),
        spatial=spatial(),
        source=CloudLocalSource(
            kind="local-array",
            content_sha256="1" * 64,
            descriptor_sha256="2" * 64,
            source_observation_id=None,
        ),
        source_metadata=None,
        cancel=lambda: None,
    )
    return scope, runtime, cloud, arrays


@pytest.mark.parametrize("kind", ["statistical", "radius"])
def test_branches_fields_sources_and_save_restore(tmp_path, kind):
    scope, runtime, source, arrays = fixture()
    try:
        kept, removed, summary = denoise_cloud(
            runtime, source, parameters(kind), cancel=lambda: None
        )
        assert summary["kept_count"] + summary["removed_count"] == 6
        all_rows = []
        for output, selection in ((kept, "kept"), (removed, "removed")):
            assert output.provenance.method.selection == selection
            with runtime.borrow(output) as view:
                rows = view.source_indices(0, output.point_count)
                all_rows.extend(rows.tolist())
                for key, data in arrays.items():
                    np.testing.assert_array_equal(
                        view.chunk(0, output.point_count)[key], data[rows]
                    )
            service = create_resource_service(tmp_path / selection)
            resource = save_cloud(
                runtime,
                output,
                service=service,
                project_id="test",
                mode="derived",
                name=selection,
                write_identity=("a" if selection == "kept" else "b") * 64,
                policy=replace(POLICY, chunk_bytes=128),
                cancel=lambda: None,
            )
            restored = read_asset(
                runtime,
                resource,
                service=service,
                project_id="test",
                policy=replace(POLICY, chunk_bytes=128),
                cancel=lambda: None,
            )
            with runtime.borrow(restored) as view:
                np.testing.assert_array_equal(
                    view.source_indices(0, restored.point_count), rows
                )
                assert runtime.source_point_count(restored) == 6
        assert sorted(all_rows) == list(range(6))
        assert len(all_rows) == len(set(all_rows))
    finally:
        scope.close()
    assert runtime.budget.used == 0


def test_budget_cancellation_and_bad_configuration():
    p = parameters("statistical")
    with pytest.raises(InvalidRequestError, match="预算"):
        denoise_mask(
            points(),
            p.settings,
            max_working_bytes=1200,
            chunk_rows=10,
            cancel=lambda: None,
        )
    with pytest.raises(InvalidRequestError, match="邻居"):
        denoise_mask(
            points()[:2],
            p.settings,
            max_working_bytes=1_000_000,
            chunk_rows=10,
            cancel=lambda: None,
        )
    with pytest.raises(ValidationError):
        DenoiseCloudParameters(settings=dict(kind="radius", radius=0, min_neighbors=2))
    with pytest.raises(ValidationError):
        DenoiseCloudParameters(
            settings=dict(kind="radius", radius=1, min_neighbors=True)
        )
    for trigger in range(1, 14):
        scope, runtime, source, _ = fixture(
            policy(max_working_bytes=1_000_000, chunk_rows=1)
        )
        initial, calls = runtime.budget.used, 0

        def cancel():
            nonlocal calls
            calls += 1
            if calls == trigger:
                raise RuntimeError("cancel")

        try:
            with pytest.raises(RuntimeError, match="cancel"):
                denoise_cloud(runtime, source, p, cancel=cancel)
            assert runtime.budget.used == initial
        finally:
            scope.close()
        assert runtime.budget.used == 0


def test_closed_radius_boundary_and_empty_cloud():
    """半径包含等号，重复点不丢；空半径输入是真实空集而非异常伪造值。"""
    p = DenoiseCloudParameters(settings=dict(kind="radius", radius=1, min_neighbors=1))
    data = np.array([[0.0, 0, 0], [1.0, 0, 0], [np.nextafter(2.0, np.inf), 0, 0]])
    mask, _ = denoise_mask(
        data, p.settings, max_working_bytes=4096, chunk_rows=1, cancel=lambda: None
    )
    np.testing.assert_array_equal(mask, [True, True, False])
    empty, _ = denoise_mask(
        np.empty((0, 3)),
        p.settings,
        max_working_bytes=4096,
        chunk_rows=1,
        cancel=lambda: None,
    )
    assert len(empty) == 0


def test_stale_or_forged_reference_is_not_borrowed():
    """方法不能绕过现有 CloudRuntime 的 run 和完整引用校验。"""
    scope, runtime, source, _ = fixture()
    try:
        for invalid in (
            source.model_copy(update=dict(run_id="other")),
            source.model_copy(update=dict(point_count=5)),
        ):
            with pytest.raises(InvalidRequestError):
                denoise_cloud(
                    runtime, invalid, parameters("radius"), cancel=lambda: None
                )
    finally:
        scope.close()
    with pytest.raises((InvalidRequestError, RuntimeError)):
        denoise_cloud(runtime, source, parameters("radius"), cancel=lambda: None)


def test_second_output_failure_reclaims_both_owners(monkeypatch):
    """第二分支失败不能留下第一分支的存储，也不能关闭仍可用的父云。"""
    scope, runtime, source, arrays = fixture()
    initial = runtime.budget.used
    register, calls = runtime.register_subset, 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second output failed")
        return register(**kwargs)

    monkeypatch.setattr(runtime, "register_subset", fail_second)
    try:
        with pytest.raises(RuntimeError, match="second output failed"):
            denoise_cloud(runtime, source, parameters("radius"), cancel=lambda: None)
        assert runtime.budget.used == initial
        with runtime.borrow(source) as view:
            np.testing.assert_array_equal(
                view.chunk(0, 6)["positions"], arrays["positions"]
            )
    finally:
        scope.close()
    assert runtime.budget.used == 0
