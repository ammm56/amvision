"""全工件逐行支持、独立拟面/交点和 50 项状态；不把数据限制伪装成有效尺寸。"""

import json
import platform
from pathlib import Path

import numpy as np
import pytest

from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    extract_boundary,
    materialize_positions,
)
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes.metrology3d_nodes.shared.measure_hole import measure_hole
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from tests.integration.metrology3d import (
    representative_recipe,
    workpiece_recipe as recipe,
)
from tests.integration.metrology3d.boundary_audit import audit_surface
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_representative_recipe_full_sample import (
    independent_support,
    verify_circle,
)
from tests.integration.metrology3d.test_transport_full_sample import FILE_SHA, POINTS
from tests.point_cloud_support import create_resource_service, options


def test_workpiece_full_sample_truth(tmp_path, request):
    """只读一次原云，共用 D/本组 B；逐项检验固定查询、质量及失败来源。"""
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
        scope, run_id="r5-whole-workpiece", policy=representative_policy().io
    )
    report = dict(
        platform=platform.platform(),
        file_sha256=FILE_SHA,
        source_points=POINTS,
        scope="fixed-workpiece-engineering-not-production",
        supports={},
        items={},
        boundaries={},
    )
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
        planes, truth = {}, {}
        contexts = {
            name: crop_roi(runtime, cloud, region, cancel=lambda: None)[0]
            for name, region in recipe.group_regions().items()
        }
        for name, region in recipe.support_regions().items():
            group = (
                name.removesuffix(".B")
                if name.endswith(".B")
                else name.removesuffix(".T").rsplit("_", 1)[0]
            )
            selected, _ = crop_roi(
                runtime,
                cloud if name == "D" else contexts[group],
                region,
                cancel=lambda: None,
            )
            normal, offset, summary = independent_support(
                runtime, cloud, selected, region
            )
            truth[name] = normal, offset
            fitted = fit_plane(
                runtime, selected, recipe.plane(name), cancel=lambda: None
            )
            feature = fitted.items[0]
            metrics = {
                item.item_id: item.value for item in feature.quality.metrics.items
            }
            assert metrics["rms"] == pytest.approx(summary["rms"], abs=1e-10)
            assert metrics["max_residual"] == pytest.approx(
                summary["max_residual"], abs=1e-9
            )
            if feature.valid:
                np.testing.assert_allclose(
                    feature.geometry.normal, normal, rtol=0, atol=1e-10
                )
                assert feature.geometry.offset == pytest.approx(offset, abs=1e-10)
            else:
                assert feature.reason == "geometry_quality_failed"
                assert any(not check.passed for check in feature.quality.checks)
            planes[name] = fitted
            report["supports"][name] = dict(
                **summary,
                valid=feature.valid,
                reason=feature.reason,
                quality=feature.quality.model_dump(mode="json"),
                region=region.model_dump(mode="json"),
            )
            print(
                name, feature.valid, summary["rms"], summary["max_residual"], flush=True
            )
        pose = build_frame(
            runtime, [planes["D"]], representative_recipe.frame(), cancel=lambda: None
        )
        assert pose.state == "found"
        n, d = truth["D"]
        origin = -d * n
        u = np.array([1.0, 0, 0]) - n[0] * n
        u /= np.linalg.norm(u)
        v = np.cross(n, u)
        for name, (_, uv, _, _) in recipe.STEEL.items():
            base, target = name.rsplit("_", 1)[0] + ".B", name + ".T"
            height = None
            for component, reference in (("H", base), ("Z", "D")):
                config = recipe.step(name, component)
                result = measure_step(
                    runtime,
                    config,
                    groups=[planes[reference], planes[target]],
                    pose=pose,
                    cancel=lambda: None,
                )
                item = result.items[0]
                if component == "H":
                    height = item
                if item.valid:
                    query = origin + uv[0] * u + uv[1] * v
                    ends = [
                        query - (pn @ query + pd) / (pn @ n) * n
                        for pn, pd in (truth[reference], truth[target])
                    ]
                    np.testing.assert_allclose(
                        item.geometry.endpoints, ends, rtol=0, atol=1e-9
                    )
                    assert item.value == pytest.approx(
                        float((ends[1] - ends[0]) @ n), abs=1e-9
                    )
                else:
                    assert item.value is None and item.reason
                report["items"][item.item_id] = item.model_dump(mode="json")
            config = recipe.contour(name)
            boundary = extract_boundary(
                runtime,
                contexts[name.rsplit("_", 1)[0]],
                config,
                contour_plane=planes["D"].items[0],
                pose=pose,
                measurement=height,
                measurement_planes=(planes[base].items[0], planes[target].items[0]),
                cancel=lambda: None,
            )
            feature = boundary.items[0]
            summary = dict(
                valid=feature.valid,
                reason=feature.reason,
                resolution=feature.method.resolution.model_dump(mode="json"),
                quality=feature.quality.model_dump(mode="json"),
            )
            # 原 A_top_L 的同一端点诊断已有独立证据，不重复计算；新对象分别核对。
            if name != "A_top_L" and feature.method.resolution.reason is None:
                selected, _ = crop_roi(
                    runtime, cloud, config.region, cancel=lambda: None
                )
                points, rows = materialize_positions(
                    runtime,
                    selected,
                    factor=12544,
                    with_sources=True,
                    cancel=lambda: None,
                )
                audit, _ = audit_surface(
                    points,
                    rows,
                    feature.method.resolution.evaluation.model_dump(mode="json"),
                    config.surface.model_dump(),
                    budget=runtime.policy.max_working_bytes,
                    tolerance=1e-8,
                )
                summary["independent_surface"] = {
                    key: value for key, value in audit.items() if key != "endpoints"
                }
                del points, rows, audit
            report["boundaries"][name] = summary
            result = measure_extents(
                runtime, recipe.extents(name), groups=[boundary], cancel=lambda: None
            )
            for item in result.items:
                assert item.valid or (item.value is None and item.reason)
                report["items"][item.item_id] = item.model_dump(mode="json")
            print(
                name,
                [
                    (
                        key,
                        report["items"][name + "." + key]["value"],
                        report["items"][name + "." + key]["reason"],
                    )
                    for key in ("H", "Z", "W", "L")
                ],
                flush=True,
            )
        for name in ("S1", "S2"):
            boundary = extract_boundary(
                runtime,
                cloud,
                recipe.contour(name),
                contour_plane=planes["D"].items[0],
                pose=pose,
                cancel=lambda: None,
            )
            fitted = fit_boundary(
                runtime, boundary, recipe.circle(name), cancel=lambda: None
            )
            diameter = measure_hole(
                runtime, [fitted], recipe.hole(name), cancel=lambda: None
            )
            item = diameter.items[0]
            report["boundaries"][name] = dict(
                valid=boundary.items[0].valid,
                reason=boundary.items[0].reason,
                quality=boundary.items[0].quality.model_dump(mode="json"),
                fit_valid=fitted.items[0].valid,
                fit_reason=fitted.items[0].reason,
                fit_quality=fitted.items[0].quality.model_dump(mode="json"),
            )
            if name == "S1":
                saved_circle = boundary, fitted, diameter
            else:
                config = recipe.contour(name)
                selected, _ = crop_roi(
                    runtime, cloud, config.region, cancel=lambda: None
                )
                points, rows = materialize_positions(
                    runtime,
                    selected,
                    factor=12544,
                    with_sources=True,
                    cancel=lambda: None,
                )
                audit, _ = audit_surface(
                    points,
                    rows,
                    boundary.items[0].method.resolution.evaluation.model_dump(
                        mode="json"
                    ),
                    config.surface.model_dump(),
                    budget=runtime.policy.max_working_bytes,
                    tolerance=1e-8,
                )
                report["boundaries"][name]["independent_surface"] = {
                    key: value for key, value in audit.items() if key != "endpoints"
                }
                del points, rows, audit
            report["items"][item.item_id] = item.model_dump(mode="json")
            print(name, item.value, item.reason, flush=True)
        report["boundaries"]["S1"]["independent_and_restored"] = verify_circle(
            runtime, *saved_circle, service, close_source=scope.close
        )
        assert len(report["items"]) == 50
        assert report["items"]["A_top_L.H"]["value"] == pytest.approx(
            1.128335845558628, abs=1e-9
        )
        assert report["items"]["A_top_L.Z"]["value"] == pytest.approx(
            1.5776995404900624, abs=1e-9
        )
        assert report["items"]["S1.D"]["value"] == pytest.approx(
            20.14782366565865, abs=1e-7
        )
        assert not report["items"]["A_top_L.L"]["valid"]
        frozen = json.loads(
            (
                Path(__file__).parents[3]
                / "docs/development/assets/r5-e/workpiece-matrix.json"
            ).read_text("utf-8")
        )
        assert report["items"].keys() == frozen["items"].keys()
        for name, item in report["items"].items():
            expected = frozen["items"][name]
            assert (item["valid"], item["reason"]) == (
                expected["valid"],
                expected["reason"],
            )
            assert item["value"] == (
                pytest.approx(expected["value"], abs=1e-7) if item["valid"] else None
            )
    finally:
        errors = scope.close()
        report["cleanup"] = dict(
            errors=[str(e) for e in errors], live_array_bytes=runtime.budget.used
        )
        directory = Path(request.config.getoption("--cloud-report-dir") or tmp_path)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"workpiece-{platform.system().lower()}.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        assert not errors and runtime.budget.used == 0
