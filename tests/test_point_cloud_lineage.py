"""有序视图、生成来源、持久恢复和失败释放的独立真值回归。"""

from dataclasses import replace
from hashlib import sha256

import numpy as np
import pytest

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.point_cloud_runtime import BoundaryCloudMethod
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes._metrology3d_nodes.shared.cloud_assets import read_asset, save_cloud
from custom_nodes._metrology3d_nodes.shared.preview import build_cloud_preview
from tests.point_cloud_support import policy, create_resource_service
from tests.test_point_cloud_runtime import own, root_cloud, method
from tests.test_point_cloud_assets import POLICY
from tests.test_metrology3d_preview import decode, preview_policy
from tests.integration.metrology3d.test_boundary_extraction import extract_parameters


def topology():
    """两点开段，不重复首尾。"""
    return BoundaryTopology(
        point_count=2,
        segments=[
            dict(
                segment_id="edge",
                start=0,
                count=2,
                closed=False,
                role="open",
                orientation="open",
            )
        ],
    )


def boundary_method():
    """显式测试方法；运行层不承担几何提取算法。"""
    parameters = extract_parameters()
    return BoundaryCloudMethod(
        method_id="extract-boundary",
        method_version=1,
        parameters=parameters,
        parameters_sha256=sha256(
            canonical_cloud_json(parameters.model_dump(mode="json"))
        ).hexdigest(),
        vertices_sha256="a" * 64,
        resolution=dict(
            observation_id="test-source",
            evaluation=parameters.evaluation,
            height=None,
            pose=None,
            datum=None,
            measurement=None,
            reason=None,
        ),
    )


def generated(runtime, parent, *, positions=None, **changes):
    """独立手算两条原始边，各 1/4 与 3/4 插值，不伪造单一源行号。"""
    arrays = dict(
        source_edges=np.array([[1, 3], [3, 5]], dtype="<u8"),
        weights=np.array([[0.25, 0.75], [0.75, 0.25]], dtype="<f8"),
        face_offsets=np.array([[0], [1], [3]], dtype="<u8"),
        source_faces=np.array([[1, 2, 3], [1, 3, 5], [3, 4, 5]], dtype="<u8"),
    )
    arrays.update(changes)
    return runtime.register_generated(
        parent=parent,
        method=boundary_method(),
        owner=own(
            runtime,
            {
                "positions": np.array(
                    [[7.5, 8.5, 9.5], [10.5, 11.5, 12.5]], dtype="<f4"
                )
                if positions is None
                else positions
            },
        ),
        lineage=own(runtime, arrays),
        point_count=2,
        fields=parent.fields,
        topology=topology(),
        cancel=lambda: None,
    )


def test_ordered_views_keep_original_rows_and_all_fields():
    """重排不改最初行号；后续子集按逻辑行而不是原始行排序。"""
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    try:
        root, _ = root_cloud(runtime)
        subset = runtime.register_subset(
            parent=root,
            method=method(),
            indices=own(runtime, {"indices": np.array([[1], [3], [5]], dtype="u4")}),
            cancel=lambda: None,
        )
        ordered = runtime.register_ordered(
            parent=subset,
            method=boundary_method(),
            indices=own(runtime, {"indices": np.array([[2], [0]], dtype="u4")}),
            topology=topology(),
            cancel=lambda: None,
        )
        with runtime.borrow(ordered) as view:
            np.testing.assert_array_equal(view.source_indices(0, 2), [5, 1])
            np.testing.assert_array_equal(
                view.chunk(0, 2)["positions"], [[15, 16, 17], [3, 4, 5]]
            )
        cropped = runtime.register_subset(
            parent=ordered,
            method=method(),
            indices=own(runtime, {"indices": np.array([[1]], dtype="u4")}),
            cancel=lambda: None,
        )
        assert cropped.topology is None
        with runtime.borrow(cropped) as view:
            np.testing.assert_array_equal(view.source_indices(0, 1), [1])
    finally:
        assert scope.close() == () and runtime.budget.used == 0


def test_generated_ancestry_survives_transform_crop_and_close():
    """变换只替换位置，裁剪只重排来源；关闭后不再借用。"""
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    try:
        root, _ = root_cloud(runtime)
        cloud = generated(runtime, root)
        changed = runtime.register_derived(
            parent=cloud,
            method=method(True),
            owner=own(runtime, {"positions": np.ones((2, 3), dtype="f4")}),
            fields=cloud.fields,
            spatial=cloud.spatial,
            cancel=lambda: None,
        )
        assert changed.topology == cloud.topology
        cropped = runtime.register_subset(
            parent=changed,
            method=method(),
            indices=own(runtime, {"indices": np.array([[1]], dtype="u4")}),
            cancel=lambda: None,
        )
        with runtime.borrow(cropped) as view:
            with pytest.raises(InvalidRequestError, match="唯一原始"):
                view.source_indices(0, 1)
            lineage = view.lineage_chunk(0, 1)
            np.testing.assert_array_equal(lineage["source_edges"], [[3, 5]])
            np.testing.assert_array_equal(lineage["face_offsets"], [[0], [2]])
            np.testing.assert_array_equal(
                lineage["source_faces"], [[1, 3, 5], [3, 4, 5]]
            )
            assert all(not array.flags.writeable for array in lineage.values())
        with pytest.raises(RuntimeError, match="结束"):
            view.lineage_chunk(0, 1)
        assert runtime.source_point_count(cropped) == 6
    finally:
        assert scope.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize("kind", ["source", "generated"])
def test_save_restore_re_save_and_preview(tmp_path, kind):
    """跨运行恢复和再次保存保持精度、来源及连接；显示不伪造源行号。"""
    service = create_resource_service(tmp_path)
    asset_policy = replace(POLICY, chunk_bytes=128)
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="first", policy=policy())
    try:
        root, _ = root_cloud(runtime)
        cloud = (
            generated(runtime, root)
            if kind == "generated"
            else runtime.register_ordered(
                parent=root,
                method=boundary_method(),
                topology=topology(),
                indices=own(runtime, {"indices": np.array([[5], [1]], dtype="u4")}),
                cancel=lambda: None,
            )
        )
        reference = save_cloud(
            runtime,
            cloud,
            service=service,
            project_id="test",
            name="boundary",
            mode="derived",
            write_identity="a" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
    finally:
        assert scope.close() == () and runtime.budget.used == 0
    second = ResourceScope(kind="test")
    runtime = get_cloud_runtime(second, run_id="second", policy=policy())
    try:
        restored = read_asset(
            runtime,
            reference,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        assert restored.topology == topology() and restored.vertex_kind == kind
        assert runtime.source_point_count(restored) == 6
        with runtime.borrow(restored) as view:
            if kind == "source":
                np.testing.assert_array_equal(view.source_indices(0, 2), [5, 1])
            else:
                np.testing.assert_array_equal(
                    view.lineage_chunk(0, 2)["source_edges"], [[1, 3], [3, 5]]
                )
        again = save_cloud(
            runtime,
            restored,
            service=service,
            project_id="test",
            name="copy",
            mode="derived",
            write_identity="b" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        assert again.sha256 == reference.sha256
        body = build_cloud_preview(
            runtime,
            restored,
            dict(point_limit=2, color=dict(mode="solid")),
            policy=preview_policy(),
            cancel=lambda: None,
        )
        arrays = decode(body)
        np.testing.assert_array_equal(
            arrays["vertex_indices" if kind == "generated" else "source_indices"][:, 0],
            [0, 1] if kind == "generated" else [5, 1],
        )
        assert ("source_indices" in arrays) == (kind == "source")
    finally:
        assert second.close() == () and runtime.budget.used == 0


@pytest.mark.parametrize(
    "changes",
    [
        dict(source_edges=np.array([[1, 6], [3, 5]], dtype="u8")),
        dict(weights=np.array([[0.3, 0.8], [0.5, 0.5]], dtype="f8")),
        dict(face_offsets=np.array([[0], [0], [3]], dtype="u8")),
        dict(source_faces=np.array([[1, 1, 3], [1, 3, 5], [3, 4, 5]], dtype="u8")),
        dict(source_faces=np.array([[0, 2, 3], [1, 3, 5], [3, 4, 5]], dtype="u8")),
        dict(positions=np.array([[np.nan, 0, 0], [0, 0, 0]], dtype="f4")),
    ],
)
def test_invalid_lineage_never_publishes_and_scope_reclaims(changes):
    scope = ResourceScope(kind="test")
    runtime = get_cloud_runtime(scope, run_id="run", policy=policy())
    try:
        root, _ = root_cloud(runtime)
        with pytest.raises(InvalidRequestError):
            generated(runtime, root, **changes)
        with runtime.borrow(root) as view:
            assert len(view.chunk(0, 1)["positions"]) == 1
    finally:
        assert scope.close() == () and runtime.budget.used == 0
