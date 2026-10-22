"""三维显示的确定性抽样、源行号、精度与独立生命周期。"""

import base64
from hashlib import sha256
import numpy as np
import pytest
from backend.contracts.workflows.point_cloud_runtime import (
    FilterCloudValid,
    NormalizeCloudUnits,
)
from backend.service.application.workflows.point_cloud.execution_policy import (
    CloudPreviewPolicy,
)
from backend.service.application.errors import InvalidRequestError
from custom_nodes._metrology3d_nodes.shared.preview import build_cloud_preview
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.normalize_units import normalize_units
from tests.test_metrology3d_preprocess import make_cloud


def preview_policy(**overrides):
    """仅供测试的显式显示预算。"""
    return CloudPreviewPolicy(
        **(
            dict(
                max_points=32,
                max_data_bytes=8192,
                max_body_bytes=16384,
                max_working_bytes=65536,
            )
            | overrides
        )
    )


def decode(body):
    """独立按描述检查精度与内容摘要，不使用生产编码函数解码。"""
    raw = base64.b64decode(body["data"]["content"], validate=True)
    assert len(raw) == body["data"]["content_length"]
    assert sha256(raw).hexdigest() == body["data"]["checksum"]
    return {
        f["name"]: np.ndarray(
            (f["count"], f["components"]),
            dtype=np.dtype(f["dtype"]).newbyteorder("<"),
            buffer=raw,
            offset=f["offset"],
        )
        for f in body["data"]["fields"]
    }


def test_subset_original_indices_survive_units_and_source_close():
    """过滤后两点仍为原始行 0/2，总点数为三，不是子集二。"""
    scope, runtime, cloud = make_cloud(
        coordinates=np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], dtype="f4"),
        attributes=[("validity", np.array([1, 0, 1], dtype="u1"), "1")],
    )
    try:
        subset, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        converted = normalize_units(
            runtime, subset, NormalizeCloudUnits(), cancel=lambda: None
        )
        body = build_cloud_preview(
            runtime,
            converted,
            dict(point_limit=5, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        assert body["source_point_count"] == 3 and body["display_point_count"] == 2
    finally:
        assert not scope.close()
    arrays = decode(body)
    np.testing.assert_array_equal(arrays["source_indices"][:, 0], [0, 2])
    np.testing.assert_array_equal(
        arrays["positions"], [[1000, 2000, 3000], [7000, 8000, 9000]]
    )
    assert arrays["positions"].dtype == np.dtype("<f4")


@pytest.mark.parametrize(
    "limit,expected",
    [(1, [0]), (2, [0, 16]), (5, [0, 4, 8, 12, 16]), (32, list(range(17)))],
)
def test_exact_index_sampling(limit, expected):
    """已知公式真值覆盖端点、单点及不需要抽样。"""
    scope, runtime, cloud = make_cloud(
        coordinates=np.arange(51, dtype="f8").reshape(17, 3)
    )
    try:
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=limit, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        np.testing.assert_array_equal(decode(body)["source_indices"][:, 0], expected)
        assert decode(body)["positions"].dtype == np.dtype("<f8")
    finally:
        assert not scope.close()


def test_exact_uint64_scalar_and_display_budget_failure():
    """uint64 色标不经 float；超预算只产生显示失败正文。"""
    values = np.array([2**64 - 2, 2**64 - 1], dtype="u8")
    scope, runtime, cloud = make_cloud(attributes=[("serial", values, "1")])
    params = dict(
        point_limit=2,
        color=dict(
            mode="scalar", field="serial", component=0, range=dict(mode="finite-range")
        ),
    )
    try:
        body = build_cloud_preview(
            runtime, cloud, params, policy=preview_policy(), cancel=lambda: None
        )
        assert body["color"]["min"] == str(2**64 - 2) and body["color"]["max"] == str(
            2**64 - 1
        )
        np.testing.assert_array_equal(decode(body)["scalar"][:, 0], values)
        failed = build_cloud_preview(
            runtime,
            cloud,
            params,
            policy=preview_policy(max_data_bytes=1),
            cancel=lambda: None,
        )
        assert failed["reason"] == "preview_size_limit" and failed["data"] is None
        with runtime.borrow(cloud) as view:
            np.testing.assert_array_equal(view.chunk(0, 2)["serial"][:, 0], values)
        with pytest.raises(InvalidRequestError):
            build_cloud_preview(
                runtime,
                cloud,
                dict(point_limit=2, color=dict(mode="rgb")),
                policy=preview_policy(),
                cancel=lambda: None,
            )
    finally:
        assert not scope.close()


def test_no_finite_candidates_and_cancellation():
    """无有效显示点为空，不把 NaN/Inf 变为原点；取消不伪装成功。"""
    scope, runtime, cloud = make_cloud(coordinates=np.full((2, 3), np.nan, dtype="f4"))
    try:
        params = dict(point_limit=2, color=dict(mode="solid"))
        body = build_cloud_preview(
            runtime, cloud, params, policy=preview_policy(), cancel=lambda: None
        )
        assert (
            body["state"] == "empty" and body["data"] is None and body["bounds"] is None
        )
        assert body["excluded_non_finite_count"] == 2

        def cancel():
            raise RuntimeError("cancel")

        with pytest.raises(RuntimeError, match="cancel"):
            build_cloud_preview(
                runtime, cloud, params, policy=preview_policy(), cancel=cancel
            )
    finally:
        assert not scope.close()


def test_restored_subset_preserves_original_rows_and_count(tmp_path):
    """跨资产重读、再过滤和再保存仍使用第一次输入的三行身份。"""
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )
    from custom_nodes._metrology3d_nodes.shared.cloud_assets import (
        save_cloud,
        read_asset,
    )
    from tests.point_cloud_support import create_resource_service, policy
    from tests.test_point_cloud_assets import POLICY
    from dataclasses import replace

    asset_policy = replace(POLICY, chunk_bytes=256)
    service = create_resource_service(tmp_path)
    scope, runtime, cloud = make_cloud(
        coordinates=np.arange(9, dtype="f4").reshape(3, 3),
        attributes=[("validity", np.array([1, 0, 1], dtype="u1"), "1")],
    )
    try:
        subset, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        ref = save_cloud(
            runtime,
            subset,
            service=service,
            project_id="test",
            name="First",
            mode="derived",
            write_identity="a" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
    finally:
        assert not scope.close()
    second = ResourceScope(kind="workflow")
    restored_runtime = get_cloud_runtime(second, run_id="restored", policy=policy())
    try:
        from tests.test_point_cloud_runtime import own

        incomplete = own(
            restored_runtime,
            {
                "positions": np.array([[0, 1, 2], [6, 7, 8]], dtype="f4"),
                "validity": np.ones((2, 1), dtype="u1"),
            },
        )
        with pytest.raises(InvalidRequestError, match="资产索引"):
            restored_runtime.register_asset(
                owner=incomplete,
                document=service.read(ref, project_id="test"),
                indices=None,
                cancel=lambda: None,
            )
        restored = read_asset(
            restored_runtime,
            ref,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        subset, _ = filter_valid(
            restored_runtime,
            restored,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        body = build_cloud_preview(
            restored_runtime,
            subset,
            dict(point_limit=2, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        assert body["source_point_count"] == 3
        np.testing.assert_array_equal(decode(body)["source_indices"][:, 0], [0, 2])
        again = save_cloud(
            restored_runtime,
            subset,
            service=service,
            project_id="test",
            name="Second",
            mode="derived",
            write_identity="b" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        assert (
            service.read(
                again, project_id="test"
            ).content.point_cloud.indices.source_point_count
            == 3
        )
    finally:
        assert not second.close()


def test_display_allocation_failure_and_empty_body_limit(monkeypatch):
    """显示分配失败不能影响计算云；空正文也受已配置的字节预算约束。"""
    from custom_nodes._metrology3d_nodes.shared import preview

    scope, runtime, cloud = make_cloud()
    try:

        def exhausted(_):
            raise MemoryError("test display allocation")

        monkeypatch.setattr(preview.base64, "b64encode", exhausted)
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=2, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        assert body["reason"] == "preview_allocation_failed"
        with runtime.borrow(cloud) as view:
            assert len(view.chunk(0, 2)["positions"]) == 2
    finally:
        assert not scope.close()
    scope, runtime, cloud = make_cloud(coordinates=np.full((2, 3), np.nan, dtype="f4"))
    try:
        body = build_cloud_preview(
            runtime,
            cloud,
            dict(point_limit=2, color=dict(mode="solid")),
            policy=preview_policy(max_body_bytes=1),
            cancel=lambda: None,
        )
        assert body["reason"] == "preview_size_limit"
    finally:
        assert not scope.close()
