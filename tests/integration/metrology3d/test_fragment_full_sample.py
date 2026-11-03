"""完整输入上的 S2 片段来源与有限环带诊断，原始文件只读。"""

import json
from pathlib import Path

import numpy as np
import pytest

from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from tests.integration.metrology3d import workpiece_recipe as recipe
from tests.integration.metrology3d import representative_recipe as representative
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_transport_full_sample import FILE_SHA, POINTS
from tests.point_cloud_support import create_resource_service, options


def test_fragment_full_sample(tmp_path, request):
    """同一完整观测拟合五窗基准，再明确选择 S2 当前评价面开弧组。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须显式提供")
    service = create_resource_service(tmp_path)
    with Path(supplied).open("rb") as stream:
        meta = service.storage.write_immutable_stream(
            object_prefix="projects/test/results/cloud",
            source_stream=stream,
            media_type="application/octet-stream",
            extension="ply",
        ).metadata
    assert meta.checksum == FILE_SHA
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(
        scope, run_id="f4-fragments", policy=representative_policy().io
    )
    report = dict(file_sha256=FILE_SHA)
    try:
        cloud = read_file_reference(
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
        assert cloud.point_count == POINTS
        selected, _ = crop_roi(
            runtime, cloud, recipe.support_regions()["D"], cancel=lambda: None
        )
        planes = fit_plane(runtime, selected, recipe.plane("D"), cancel=lambda: None)
        datum = planes.items[0]
        assert datum.valid
        from tests.integration.metrology3d.datum_application_audit import (
            audit_datum_application,
        )

        with runtime.borrow(selected) as view:
            datum_points = np.concatenate(
                [
                    view.chunk(
                        start,
                        min(start + runtime.policy.chunk_rows, selected.point_count),
                    )["positions"]
                    for start in range(
                        0, selected.point_count, runtime.policy.chunk_rows
                    )
                ]
            )
        report["datum_application"] = audit_datum_application(
            datum_points, recipe.support_regions()["D"].rois, datum.geometry
        )
        pose = build_frame(
            runtime, [planes], representative.frame(), cancel=lambda: None
        )
        from tests.integration.metrology3d.profile_stage_audit import (
            audit_profile_sample,
        )

        report["profile_stages"] = audit_profile_sample(runtime, cloud, planes, pose)
        normal = np.asarray(datum.geometry.normal)
        u = np.array([1.0, 0, 0]) - normal[0] * normal
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
        origin = -datum.geometry.offset * normal
        source_center = np.array([32.4, -88.5, 0.0])
        source_center[2] = (
            -(normal[:2] @ source_center[:2] + datum.geometry.offset) / normal[2]
        )
        center = (source_center - origin) @ np.column_stack((u, v))
        config = recipe.contour("S2")
        data = config.model_dump(mode="json")
        parameters = type(config).model_validate(data)
        boundary = extract_boundary(
            runtime,
            cloud,
            parameters,
            contour_plane=datum,
            pose=pose,
            cancel=lambda: None,
        )
        item = boundary.items[0]
        report.update(
            parameters=data, boundary=item.model_dump(mode="json", exclude={"support"})
        )
        print(
            "S2 boundary",
            item.valid,
            item.reason,
            "center",
            center.tolist(),
            flush=True,
        )
        if item.valid:
            p = recipe.circle("S2")
            values = p.model_dump(mode="json")
            fitted = fit_boundary(
                runtime, boundary, type(p).model_validate(values), cancel=lambda: None
            ).items[0]
            report["fit"] = fitted.model_dump(mode="json", exclude={"support"})
            print(
                "S2 fit",
                fitted.valid,
                fitted.reason,
                {m.item_id: m.value for m in fitted.quality.metrics.items},
                flush=True,
            )
            assert fitted.valid, fitted.reason
            with runtime.borrow(fitted.support) as view:
                points = np.concatenate(
                    [
                        view.chunk(
                            start,
                            min(
                                start + runtime.policy.chunk_rows,
                                fitted.support.point_count,
                            ),
                        )["positions"]
                        for start in range(
                            0, fitted.support.point_count, runtime.policy.chunk_rows
                        )
                    ]
                )
            uv = (points - fitted.method.evaluation.origin) @ np.asarray(
                fitted.method.evaluation.rotation
            )[:, :2]
            report["independent"] = independent_circle_checks(
                uv, values["robust"], fitted.geometry, fitted.method.evaluation
            )
            report["support_uv"] = uv.tolist()
            from tests.integration.metrology3d.circle_method_audit import (
                compare_methods,
            )

            report["method_comparison"] = compare_methods(
                uv, fitted.support.topology, p
            )
        assert item.valid, item.reason
    finally:
        errors = scope.close()
        report["cleanup"] = dict(errors=list(errors), live_bytes=runtime.budget.used)
        (tmp_path / "fragment-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert not errors and runtime.budget.used == 0


def independent_circle_checks(uv, settings, geometry, evaluation, point_weights=None):
    """标量目标函数独立实现；隔点及删去目标八分之一角域不复制生产求解器。"""
    from scipy.optimize import minimize

    center = np.asarray(settings["center"])
    delta = uv - center
    angles = (np.arctan2(delta[:, 1], delta[:, 0]) - settings["start_angle"]) % (
        2 * np.pi
    )
    sectors = np.minimum(
        (angles / settings["sweep"] * settings["sector_count"]).astype(int),
        settings["sector_count"] - 1,
    )

    def solve(mask):
        points, ids = uv[mask] - center, sectors[mask]
        counts = np.bincount(ids, minlength=settings["sector_count"])
        weights = (
            len(points) / (np.count_nonzero(counts) * counts[ids])
            if point_weights is None
            else point_weights[mask]
        )

        def objective(v):
            residual = (
                np.sqrt((points[:, 0] - v[0]) ** 2 + (points[:, 1] - v[1]) ** 2) - v[2]
            )
            return float(
                np.sum(
                    weights
                    * settings["loss_scale"] ** 2
                    * (np.sqrt(1 + (residual / settings["loss_scale"]) ** 2) - 1)
                )
            )

        result = minimize(
            objective,
            [0, 0, 10],
            method="Nelder-Mead",
            options=dict(xatol=1e-10, fatol=1e-13, maxiter=3000),
        )
        assert result.success
        return np.r_[result.x[:2] + center, result.x[2]]

    reference = solve(np.ones(len(uv), bool))
    fitted_center = (np.asarray(geometry.center) - evaluation.origin) @ np.asarray(
        evaluation.rotation
    )[:, :2]
    np.testing.assert_allclose(
        reference, np.r_[fitted_center, geometry.radius], atol=1e-6, rtol=0
    )
    alternatives = [solve(np.arange(len(uv)) % 2 == phase) for phase in (0, 1)]
    alternatives += [solve(sectors // 4 != sector) for sector in range(8)]
    diameter_delta = max(abs(v[2] - reference[2]) * 2 for v in alternatives)
    center_delta = max(np.linalg.norm(v[:2] - reference[:2]) for v in alternatives)
    return dict(
        resampling_weights="rebalanced-sectors"
        if point_weights is None
        else "retained-original-edge-contributions",
        center_uv=reference[:2].tolist(),
        diameter=float(2 * reference[2]),
        resamples=[v.tolist() for v in alternatives],
        max_diameter_change=float(diameter_delta),
        max_center_change=float(center_delta),
        stability_limit_mm=0.03,
        stability_passed=bool(diameter_delta <= 0.03 and center_delta <= 0.03),
    )
