"""真实运行所有权与边界/拟合组合，不使用算法输出作为几何真值。"""

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes.metrology3d_nodes.shared.geometry_preview import attach_geometry
from custom_nodes.metrology3d_nodes.shared.preview import build_cloud_preview
from tests.test_metrology3d_preprocess import make_cloud
from tests.point_cloud_support import policy
from tests.test_metrology3d_preview import preview_policy
from tests.test_metrology3d_boundary_contracts import (
    line_parameters,
    circle_parameters,
    evaluation,
)
from tests.integration.metrology3d.test_boundary_extraction import (
    extract_parameters,
    region,
)


def runtime_policy():
    """完整局部算法测试预算，不作为生产缺省。"""
    return policy(
        max_working_bytes=10_000_000,
        max_live_array_bytes=1_000_000,
        max_decoded_bytes=1_000_000,
        chunk_rows=32,
    )


def test_generated_section_line_and_preview_are_independent_of_root_row_order():
    """z=x 截面 x=.5；原始行重排不影响 y 向直线和原始来源。"""
    points = np.array([(x, y, x) for x in range(3) for y in range(3)], dtype="f4")
    points = points[[7, 2, 3, 0, 6, 1, 4, 8, 5]]
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=points, runtime_policy=runtime_policy()
    )
    try:
        parameters = extract_parameters(
            method=dict(
                kind="section",
                origin=[0, 0, 0.5],
                normal=[0, 0, 1],
                numeric_tolerance=1e-10,
            ),
            targets=[
                dict(segment_id="side", region=region(), closed=False, role="open")
            ],
        )
        boundary = extract_boundary(runtime, root, parameters, cancel=lambda: None)
        item = boundary.items[0]
        assert item.valid and item.support.vertex_kind == "generated"
        with runtime.borrow(item.support) as view:
            actual = view.chunk(0, item.support.point_count)["positions"]
            lineage = view.lineage_chunk(0, item.support.point_count)
            edges, weights = lineage["source_edges"], lineage["weights"]
            np.testing.assert_allclose(
                (points[edges] * weights[:, :, None]).sum(axis=1), actual, atol=1e-10
            )
        plane = evaluation(
            origin=[0.5, 0, 0.5], rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]]
        )
        fitted = fit_boundary(
            runtime,
            boundary,
            line_parameters(evaluation=plane, positive_direction=[0, 1, 0]),
            cancel=lambda: None,
        )
        assert fitted.items[0].valid
        np.testing.assert_allclose(
            fitted.items[0].geometry.direction, [0, 1, 0], atol=1e-12
        )
        np.testing.assert_allclose(
            fitted.items[0].geometry.origin, [0.5, 1, 0.5], atol=1e-12
        )
        # 每个显示附件都用对应评价空间，不能伪造同一平面方向。
        display_policy = preview_policy(
            max_points=100, max_body_bytes=100_000, max_working_bytes=1_000_000
        )
        body = build_cloud_preview(
            runtime,
            root,
            dict(point_limit=9, color=dict(mode="solid")),
            policy=display_policy,
            cancel=lambda: None,
        )
        body = attach_geometry(
            runtime,
            root,
            body,
            {"features": [boundary.model_dump(), fitted.model_dump()]},
            policy=display_policy,
            cancel=lambda: None,
        )
        assert len(body["geometry"]["curves"]) == 2
        assert "cloud_id" not in str(body["geometry"])
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_real_projection_circle_with_all_attributes_and_invalid_quality():
    """已知半径4的采样圆盘边界，保留 uint64 属性且坏质量清除几何。"""
    angle = np.linspace(0, 2 * np.pi, 64, endpoint=False)
    points = np.vstack(
        (
            [[0, 0, 0]],
            np.column_stack((4 * np.cos(angle), 4 * np.sin(angle), np.zeros(64))),
        )
    )
    serial = np.arange(len(points), dtype="u8") + np.uint64(2**63)
    scope, runtime, root = make_cloud(
        unit="mm",
        coordinates=points,
        attributes=[("serial", serial, "1")],
        runtime_policy=runtime_policy(),
    )
    try:
        p = extract_parameters(
            surface=dict(
                alpha_radius=5,
                max_edge_length=9,
                max_normal_step=1,
                min_projected_area=1e-12,
            ),
            targets=[
                dict(segment_id="arc", region=region(), closed=True, role="outer")
            ],
        )
        boundary = extract_boundary(runtime, root, p, cancel=lambda: None)
        assert boundary.items[0].valid
        support = boundary.items[0].support
        with runtime.borrow(support) as view:
            for start in range(0, support.point_count, 32):
                rows = view.source_indices(start, min(start + 32, support.point_count))
                np.testing.assert_array_equal(
                    view.chunk(start, min(start + 32, support.point_count))["serial"][
                        :, 0
                    ],
                    serial[rows],
                )
        circle = fit_boundary(
            runtime, boundary, circle_parameters(), cancel=lambda: None
        ).items[0]
        assert circle.valid and circle.geometry.radius == pytest.approx(4, abs=1e-10)
        np.testing.assert_allclose(circle.geometry.center, [0, 0, 0], atol=1e-10)
        bad = circle_parameters(evaluation=evaluation(origin=[0, 0, 1]))
        failed = fit_boundary(runtime, boundary, bad, cancel=lambda: None).items[0]
        assert (
            not failed.valid
            and failed.reason == "insufficient_quality"
            and failed.geometry is None
            and failed.intervals == ()
        )
        with pytest.raises(InvalidRequestError, match="唯一边界"):
            fit_boundary(
                runtime,
                boundary,
                circle_parameters(
                    selection=dict(feature_id="missing", segment_ids=["arc"])
                ),
                cancel=lambda: None,
            )
    finally:
        assert not scope.close() and runtime.budget.used == 0


def test_boundary_save_restore_features_fit_and_wrong_support(tmp_path):
    """保存证据不含运行引用，跨运行恢复后仍可拟合，错误支持不落盘。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import (
        save_cloud,
        read_asset,
    )
    from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_boundary
    from tests.point_cloud_support import create_resource_service
    from tests.test_point_cloud_assets import POLICY
    from dataclasses import replace
    from backend.service.application.runtime.resource_scope import ResourceScope
    from backend.service.application.workflows.point_cloud.runtime import (
        get_cloud_runtime,
    )

    points = np.array([(x, y, x) for x in range(3) for y in range(3)], dtype="f4")
    scope, runtime, root = make_cloud(
        unit="mm", coordinates=points, runtime_policy=runtime_policy()
    )
    service = create_resource_service(tmp_path)
    asset_policy = replace(POLICY, chunk_bytes=128)
    parameters = extract_parameters(
        method=dict(
            kind="section",
            origin=[0, 0, 0.5],
            normal=[0, 0, 1],
            numeric_tolerance=1e-10,
        ),
        targets=[dict(segment_id="side", region=region(), closed=False, role="open")],
    )
    try:
        features = extract_boundary(runtime, root, parameters, cancel=lambda: None)
        with pytest.raises(InvalidRequestError, match="完整支持"):
            save_cloud(
                runtime,
                root,
                features=features,
                service=service,
                project_id="test",
                mode="derived",
                name="wrong",
                write_identity="c" * 64,
                policy=asset_policy,
                cancel=lambda: None,
            )
        asset = save_cloud(
            runtime,
            features.items[0].support,
            features=features,
            service=service,
            project_id="test",
            mode="derived",
            name="boundary",
            write_identity="d" * 64,
            policy=asset_policy,
            cancel=lambda: None,
        )
        evidence = service.read(asset, project_id="test").content.point_cloud.boundary
        assert evidence is not None and "cloud_id" not in evidence.model_dump_json()
    finally:
        assert not scope.close() and runtime.budget.used == 0
    second = ResourceScope(kind="test")
    runtime = get_cloud_runtime(second, run_id="restored", policy=runtime_policy())
    try:
        cloud = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        restored = restore_boundary(cloud, evidence)
        assert restored.run_id == "restored" and restored.items[0].support == cloud
        fitted = fit_boundary(
            runtime,
            restored,
            line_parameters(
                evaluation=evaluation(
                    origin=[0.5, 0, 0.5], rotation=[[0, 0, 1], [1, 0, 0], [0, 1, 0]]
                ),
                positive_direction=[0, 1, 0],
            ),
            cancel=lambda: None,
        )
        assert fitted.items[0].valid
        np.testing.assert_allclose(
            fitted.items[0].geometry.origin, [0.5, 1, 0.5], atol=1e-12
        )
        assert not restore_boundary(cloud, None).items
    finally:
        assert not second.close() and runtime.budget.used == 0
