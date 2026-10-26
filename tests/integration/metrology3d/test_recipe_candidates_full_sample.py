"""审计报告候选窗口，不将候选 ROI 或测试质量阈值升级为工程配方。"""

import json
import os
import platform
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes._metrology3d_nodes.shared.boundary_runtime import (
    materialize_positions,
)
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.fit_plane import _orthogonal_fit, fit_plane
from custom_nodes._metrology3d_nodes.shared.geometry_preview import attach_geometry
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes._metrology3d_nodes.shared.preview import build_cloud_preview
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_crop import box, parameters
from tests.test_metrology3d_plane import plane_parameters
from tests.test_metrology3d_preview import decode, preview_policy
from tests.test_metrology3d_roi_union import union


def test_report_candidates_full_sample(tmp_path, request):
    """逐行核查真实支持，独立协方差核对 QR 拟面，并记录既有容量拒绝。"""
    supplied = request.config.getoption("--cloud-sample")
    reports = os.environ.get("AMVISION_METROLOGY_REPORTS")
    if not supplied or not reports:
        pytest.skip("需显式提供完整点云和手工报告目录")
    report_root = Path(reports)
    config = json.loads((report_root / "measurement_config.json").read_text("utf-8"))
    dimensions = json.loads((report_root / "dimensions.json").read_text("utf-8"))
    candidates = [("D.union", config["datum_rois"])]
    candidates.extend(
        ("B." + row["name"], [row["xy"]]) for row in config["body_reference_rois"]
    )
    candidates.extend(
        ("T." + row["name"], [row["source_xy_bounds"]])
        for row in dimensions["steel_sheets"]["sheets"]
    )
    # S1/S2 搜索框来自 R5 基线；全高只用于容量审计，不表示最终测量支持。
    candidates.append(("S1.search", [[-13, 17, -85, -61]]))
    candidates.append(("S2.search", [[19, 46, -98, -73]]))
    service = create_resource_service(tmp_path)
    with Path(supplied).open("rb") as stream:
        meta = service.storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert (
        meta.checksum
        == "ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b"
    )
    limits = policy(
        max_header_bytes=65536,
        max_decoded_bytes=400000000,
        max_working_bytes=536870912,
        chunk_rows=65536,
        chunk_bytes=4194304,
        max_live_array_bytes=800000000,
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="recipe-candidate-audit", policy=limits)
    report = dict(
        scope="candidate-only-not-approved-recipe",
        environment=dict(
            platform=platform.platform(),
            python=platform.python_version(),
            packages={
                name: version(name)
                for name in (
                    "numpy",
                    "scipy",
                    "trimesh",
                    "pypcd4",
                    "pydantic",
                    "pytest",
                )
            },
        ),
        file_sha256=meta.checksum,
        limits=limits.model_dump(mode="json"),
        candidates=[],
    )
    try:
        raw = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=dict(
                transport_kind="storage",
                storage_ref="object-store",
                object_key=meta.object_key,
                file_name="sample.ply",
                media_type=meta.media_type,
                content_length=meta.content_length,
                checksum_algorithm="sha256",
                checksum=meta.checksum,
                immutable_version=meta.immutable_version,
            ),
            options=options(),
            cancel=lambda: None,
        )
        assert raw.point_count == 14745099
        low, high, digest = np.full(3, np.inf), np.full(3, -np.inf), sha256()
        with runtime.borrow(raw) as view:
            for start in range(0, raw.point_count, limits.chunk_rows):
                points = view.chunk(
                    start, min(start + limits.chunk_rows, raw.point_count)
                )["positions"]
                assert points.dtype == np.dtype("<f4") and np.isfinite(points).all()
                digest.update(points.tobytes())
                low, high = (
                    np.minimum(low, points.min(axis=0)),
                    np.maximum(high, points.max(axis=0)),
                )
        assert (
            digest.hexdigest()
            == "956927f058ba4a0170b1c1b93b1411b613fbe21fcbfc278ad0a7fc3cf621a1c6"
        )
        report.update(
            point_count=raw.point_count,
            xyz_sha256=digest.hexdigest(),
            bounds=[low.tolist(), high.tolist()],
        )
        preview = build_cloud_preview(
            runtime,
            raw,
            dict(
                point_limit=1000000,
                color=dict(
                    mode="scalar",
                    field="positions",
                    component=2,
                    range=dict(mode="finite-range"),
                ),
            ),
            policy=preview_policy(
                max_points=1000000,
                max_data_bytes=32000000,
                max_body_bytes=64000000,
                max_working_bytes=536870912,
            ),
            cancel=lambda: None,
        )
        assert preview["display_point_count"] == 1000000
        display = decode(preview)
        with runtime.borrow(raw) as source:
            for index in (0, 499999, 999999):
                row = int(display["source_indices"][index, 0])
                np.testing.assert_array_equal(
                    display["positions"][index],
                    source.chunk(row, row + 1)["positions"][0],
                )
        (tmp_path / "real-preview.json").write_text(json.dumps(preview), "utf-8")
        del preview, display
        for name, windows in candidates:
            members = []
            for index, (xmin, xmax, ymin, ymax) in enumerate(windows):
                roi = box()
                roi["roi_id"] = f"window-{index}"
                roi["geometry"].update(
                    center=[
                        (xmin + xmax) / 2,
                        (ymin + ymax) / 2,
                        (low[2] + high[2]) / 2,
                    ],
                    size=[xmax - xmin, ymax - ymin, high[2] - low[2] + 2],
                )
                members.append(roi)
            region = parameters(
                union("candidate", *(r["roi_id"] for r in members)), *members
            )
            selected, _ = crop_roi(runtime, raw, region, cancel=lambda: None)
            cursor, blocks, source_digest = 0, [], sha256()
            with runtime.borrow(raw) as source, runtime.borrow(selected) as target:
                for start in range(0, raw.point_count, limits.chunk_rows):
                    stop = min(start + limits.chunk_rows, raw.point_count)
                    points = source.chunk(start, stop)["positions"]
                    keep = np.zeros(len(points), dtype=bool)
                    for xmin, xmax, ymin, ymax in windows:
                        keep |= (
                            (points[:, 0] >= xmin)
                            & (points[:, 0] <= xmax)
                            & (points[:, 1] >= ymin)
                            & (points[:, 1] <= ymax)
                        )
                    count = int(keep.sum())
                    np.testing.assert_array_equal(
                        target.source_indices(cursor, cursor + count),
                        source.source_indices(start, stop)[keep],
                    )
                    np.testing.assert_array_equal(
                        target.chunk(cursor, cursor + count)["positions"], points[keep]
                    )
                    source_digest.update(
                        target.source_indices(cursor, cursor + count)
                        .astype("<u8", copy=False)
                        .tobytes()
                    )
                    blocks.append(points[keep].copy())
                    cursor += count
            assert (
                cursor == selected.point_count
                and runtime.source_point_count(selected) == raw.point_count
            )
            points = np.concatenate(blocks).astype(np.float64)
            center, normal, _, rms, maximum = _orthogonal_fit(
                runtime, selected, lambda: None
            )
            centered = points - points.mean(axis=0)
            _, vectors = np.linalg.eigh(centered.T @ centered)
            expected_normal = vectors[:, 0]
            if normal @ expected_normal < 0:
                expected_normal = -expected_normal
            np.testing.assert_allclose(normal, expected_normal, atol=1e-9, rtol=0)
            np.testing.assert_allclose(center, points.mean(axis=0), atol=1e-9, rtol=0)
            expected_residual = centered @ expected_normal
            np.testing.assert_allclose(
                [rms, maximum],
                [
                    np.sqrt(np.mean(expected_residual**2)),
                    np.max(np.abs(expected_residual)),
                ],
                atol=1e-9,
                rtol=0,
            )
            feature = fit_plane(
                runtime, selected, plane_parameters(), cancel=lambda: None
            ).items[0]
            row = dict(
                name=name,
                xy_windows=windows,
                point_count=cursor,
                source_indices_sha256=source_digest.hexdigest(),
                source_point_count=runtime.source_point_count(selected),
                crop_parameters=region.model_dump(mode="json"),
                selected_bounds=[
                    points.min(axis=0).tolist(),
                    points.max(axis=0).tolist(),
                ],
                source_z_quantiles=np.quantile(
                    points[:, 2], [0, 0.01, 0.5, 0.99, 1]
                ).tolist(),
                svd_center=center.tolist(),
                svd_normal=normal.tolist(),
                rms_mm=rms,
                max_residual_mm=maximum,
                max_residual_point=points[
                    int(np.argmax(np.abs(expected_residual)))
                ].tolist(),
                absolute_residual_quantiles=np.quantile(
                    np.abs(expected_residual), [0.5, 0.9, 0.99, 1]
                ).tolist(),
                fit_reason=feature.reason,
                quality_policy=feature.quality.model_dump(mode="json"),
                boundary_working_bytes=cursor * 12544,
                boundary_capacity_points=limits.max_working_bytes // 12544,
            )
            if name in {"D.union", "B.A_top", "T.A_top_L", "S1.search"}:
                # 审核附件仍调用正式显示生成器；不将候选平面伪装为有效基准。
                display_policy = preview_policy(
                    max_points=1000000,
                    max_data_bytes=32000000,
                    max_body_bytes=64000000,
                    max_working_bytes=536870912,
                )
                candidate_display = build_cloud_preview(
                    runtime,
                    selected,
                    dict(
                        point_limit=1000000,
                        color=dict(
                            mode="scalar",
                            field="positions",
                            component=2,
                            range=dict(mode="finite-range"),
                        ),
                    ),
                    policy=display_policy,
                    cancel=lambda: None,
                )
                candidate_display = attach_geometry(
                    runtime,
                    selected,
                    candidate_display,
                    {},
                    policy=display_policy,
                    cancel=lambda: None,
                )
                assert candidate_display["state"] == "ready"
                assert candidate_display["point_count"] == cursor
                assert candidate_display["source_point_count"] == raw.point_count
                displayed = decode(candidate_display)
                source_rows = displayed["source_indices"].reshape(-1)
                with runtime.borrow(raw) as source:
                    for index in sorted(
                        {0, len(source_rows) // 2, len(source_rows) - 1}
                    ):
                        original = int(source_rows[index])
                        np.testing.assert_array_equal(
                            displayed["positions"][index],
                            source.chunk(original, original + 1)["positions"][0],
                        )
                row["display_file"] = f"candidate-{name}.json"
                (tmp_path / row["display_file"]).write_text(
                    json.dumps(candidate_display, ensure_ascii=False), "utf-8"
                )
                del candidate_display, displayed, source_rows
            if cursor * 12544 > limits.max_working_bytes:
                with pytest.raises(
                    InvalidRequestError, match="完整局部支持超过工作预算"
                ):
                    materialize_positions(
                        runtime,
                        selected,
                        factor=12544,
                        with_sources=True,
                        cancel=lambda: None,
                    )
                row["boundary_capacity"] = "rejected-before-allocation"
            else:
                row["boundary_capacity"] = (
                    "fits-preflight-only-not-geometric-acceptance"
                )
            report["candidates"].append(row)
            print(
                f"{name}: points={cursor}, rms={rms:.8f}, max={maximum:.8f}, boundary={row['boundary_capacity']}"
            )
            del blocks, points, centered, expected_residual
    finally:
        errors = scope.close()
        report["cleanup"] = dict(
            errors=[str(e) for e in errors], live_array_bytes=runtime.budget.used
        )
        (tmp_path / "recipe-candidates.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
        )
        assert not errors and runtime.budget.used == 0
