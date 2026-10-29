"""R5 代表工件完整数据验证；几何无效保留为未完成量值，不冒充生产验收。"""

import json
import platform
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

import numpy as np
import pytest
from scipy.optimize import minimize

from backend.contracts.workflows.measurement3d_evidence import MeasurementEvidence3d
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import extract_boundary
from custom_nodes.metrology3d_nodes.shared.build_frame import build_frame
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.fit_boundary import fit_boundary
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.boundary_assets import restore_boundary
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.measure_step import measure_step
from custom_nodes.metrology3d_nodes.shared.measure_hole import measure_hole
from custom_nodes.metrology3d_nodes.shared.measure_extents import measure_extents
from tests.integration.metrology3d.representative_recipe import (
    boxes,
    supports,
    plane,
    frame,
    step,
    contour,
    circle,
    hole,
)
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_dimension_contracts import extent_parameters
from tests.test_point_cloud_assets import POLICY


def verify_circle(runtime, boundary, fitted, diameter, service, *, close_source=None):
    """两参数中心优化独立核对三参数拟圆，再验证生成点来源的保存重读一致性。"""
    feature = boundary.items[0]
    with runtime.borrow(feature.support) as view:
        points = view.chunk(0, feature.support.point_count)["positions"].copy()
        lineage = {
            name: values.copy()
            for name, values in view.lineage_chunk(
                0, feature.support.point_count
            ).items()
        }
    evaluation = feature.method.resolution.evaluation
    uv = ((points - evaluation.origin) @ np.asarray(evaluation.rotation))[:, :2]

    def objective(center):
        delta = center - uv
        distances = np.linalg.norm(delta, axis=1)
        residual = distances - distances.mean()
        return float(residual @ residual), 2 * (
            residual[:, None] * delta / distances[:, None]
        ).sum(axis=0)

    # 代数圆只提供独立初值；半径消元后的目标函数不调用生产三参数求解器。
    initial = np.linalg.lstsq(
        np.column_stack((2 * uv, np.ones(len(uv)))), (uv * uv).sum(axis=1), rcond=None
    )[0][:2]
    checked = minimize(
        objective,
        initial,
        jac=True,
        method="BFGS",
        options={"gtol": 1e-8, "maxiter": 500},
    )
    assert np.linalg.norm(checked.jac) < 1e-6, checked.message
    expected = 2 * np.linalg.norm(uv - checked.x, axis=1).mean()
    assert diameter.items[0].value == pytest.approx(expected, abs=1e-7)
    asset_policy = replace(
        POLICY,
        max_asset_bytes=16 * 1024**2,
        max_archive_bytes=32 * 1024**2,
        chunk_bytes=1048576,
    )
    asset = save_cloud(
        runtime,
        feature.support,
        features=boundary,
        service=service,
        project_id="test",
        name="S1-real-arc",
        mode="derived",
        write_identity="c" * 64,
        policy=asset_policy,
        cancel=lambda: None,
    )
    if close_source is not None:
        assert not close_source()
        assert runtime.budget.used == 0
        with pytest.raises(RuntimeError, match="点云运行资源不可用"):
            with runtime.borrow(feature.support):
                pytest.fail("已关闭运行仍可借用旧引用")
    second = ResourceScope(kind="workflow")
    restored_runtime = get_cloud_runtime(
        second, run_id="r5-restored", policy=runtime.policy
    )
    try:
        restored = read_asset(
            restored_runtime,
            asset,
            service=service,
            project_id="test",
            policy=asset_policy,
            cancel=lambda: None,
        )
        evidence = service.read(asset, project_id="test").content.point_cloud.boundary
        recovered = restore_boundary(restored, evidence)
        again = fit_boundary(restored_runtime, recovered, circle(), cancel=lambda: None)
        actual = measure_hole(restored_runtime, [again], hole(), cancel=lambda: None)
        assert again.items[0].geometry == fitted.items[0].geometry
        assert actual.items[0].value == diameter.items[0].value
        with restored_runtime.borrow(restored) as after:
            np.testing.assert_array_equal(
                after.chunk(0, restored.point_count)["positions"], points
            )
            for name, values in lineage.items():
                np.testing.assert_array_equal(
                    after.lineage_chunk(0, restored.point_count)[name], values
                )
    finally:
        assert not second.close() and restored_runtime.budget.used == 0
    return dict(
        independent_diameter=expected,
        restored_value=actual.items[0].value,
        source_closed_before_restore=close_source is not None,
    )


def independent_support(runtime, root, selected, region):
    """轴对齐配方采用独立逐行比较，协方差特征分解核对 QR/SVD。"""
    boxes = [r.geometry for r in region.rois if r.kind == "box"]
    cursor, blocks, digest = 0, [], sha256()
    with runtime.borrow(root) as original, runtime.borrow(selected) as actual:
        for start in range(0, root.point_count, runtime.policy.chunk_rows):
            end = min(start + runtime.policy.chunk_rows, root.point_count)
            points = original.chunk(start, end)["positions"]
            mask = np.zeros(len(points), dtype=bool)
            for box in boxes:
                low = np.asarray(box.center) - np.asarray(box.size) / 2
                high = np.asarray(box.center) + np.asarray(box.size) / 2
                mask |= ((points >= low) & (points <= high)).all(axis=1)
            expected = np.arange(start, end, dtype="<u8")[mask]
            count = len(expected)
            np.testing.assert_array_equal(
                actual.source_indices(cursor, cursor + count), expected
            )
            np.testing.assert_array_equal(
                actual.chunk(cursor, cursor + count)["positions"], points[mask]
            )
            digest.update(expected)
            blocks.append(points[mask].copy())
            cursor += count
    assert cursor == selected.point_count
    assert runtime.source_point_count(selected) == root.point_count
    data = np.concatenate(blocks).astype(float)
    center = data.mean(axis=0)
    residual = data - center
    _, vectors = np.linalg.eigh(residual.T @ residual)
    normal = vectors[:, 0]
    normal *= np.sign(normal[2])
    distances = residual @ normal
    return (
        normal,
        -float(center @ normal),
        dict(
            point_count=cursor,
            source_indices_sha256=digest.hexdigest(),
            normal=normal.tolist(),
            offset=-float(center @ normal),
            rms=float(np.sqrt(np.mean(distances**2))),
            max_residual=float(abs(distances).max()),
        ),
    )


def test_representative_recipe_full_input_truth_and_failures(tmp_path, request):
    """真实文件入口、同定义高度独立真值、动态边界及有界诊断报告。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须显式提供")
    started = monotonic()
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
    # 真实局部剖分的显式测试容量，未降低 12544*N 预检，不进入生产配置。
    limits = policy(
        max_header_bytes=65536,
        max_decoded_bytes=400000000,
        max_working_bytes=4 * 1024**3,
        max_live_array_bytes=1024**3,
        chunk_rows=65536,
        chunk_bytes=4194304,
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="r5-representative", policy=limits)
    report = dict(
        platform=platform.platform(),
        python=platform.python_version(),
        scope="single-sample-recipe-not-production-acceptance",
        source_sha256=meta.checksum,
        limits=limits.model_dump(mode="json"),
        supports={},
        measurements={},
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
        assert cloud.point_count == 14745099
        groups, truth = {}, {}
        for name, region in supports().items():
            selected, _ = crop_roi(runtime, cloud, region, cancel=lambda: None)
            normal, offset, summary = independent_support(
                runtime, cloud, selected, region
            )
            truth[name] = normal, offset
            fitted = fit_plane(runtime, selected, plane(name), cancel=lambda: None)
            feature = fitted.items[0]
            report["supports"][name] = dict(
                **summary,
                parameters=region.model_dump(mode="json"),
                fit_parameters=plane(name).model_dump(mode="json"),
                valid=feature.valid,
                reason=feature.reason,
            )
            assert feature.valid, (name, feature.quality.model_dump())
            np.testing.assert_allclose(
                feature.geometry.normal, normal, rtol=0, atol=1e-10
            )
            assert feature.geometry.offset == pytest.approx(offset, abs=1e-10)
            groups[name] = fitted
            print(name, json.dumps(summary), flush=True)
        pose = build_frame(runtime, [groups["D"]], frame(), cancel=lambda: None)
        assert pose.state == "found", pose.reason
        normal, offset = truth["D"]
        origin = -offset * normal
        u = np.array([1.0, 0, 0]) - normal[0] * normal
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
        query = origin - 34.75 * u - 19 * v
        measurements = {}
        for item_id, reference in (("H", "B"), ("Z", "D")):
            config = step(item_id, reference)
            result = measure_step(
                runtime,
                config,
                groups=[groups[reference], groups["T"]],
                pose=pose,
                cancel=lambda: None,
            )
            item = result.items[0]
            expected = []
            for key in (reference, "T"):
                n, d = truth[key]
                expected.append(query - (n @ query + d) / (n @ normal) * normal)
            report["measurements"][item_id] = result.model_dump(mode="json")
            assert item.valid, item.model_dump()
            np.testing.assert_allclose(
                item.geometry.endpoints, expected, rtol=0, atol=1e-9
            )
            assert item.value == pytest.approx(
                float((expected[1] - expected[0]) @ normal), abs=1e-9
            )
            assert (
                MeasurementEvidence3d.model_validate_json(result.model_dump_json())
                == result
            )
            measurements[item_id] = item
            print(item_id, item.value, flush=True)
        for name in ("A_top_L", "S1"):
            config = contour(name)
            selected, _ = crop_roi(runtime, cloud, config.region, cancel=lambda: None)
            boundary = extract_boundary(
                runtime,
                cloud,
                config,
                contour_plane=groups["D"].items[0],
                pose=pose,
                measurement=measurements["H"] if name == "A_top_L" else None,
                measurement_planes=(groups["B"].items[0], groups["T"].items[0])
                if name == "A_top_L"
                else (),
                cancel=lambda: None,
            )
            feature = boundary.items[0]
            report["boundaries"][name] = dict(
                parameters=config.model_dump(mode="json"),
                point_count=selected.point_count,
                estimated_bytes=selected.point_count * 12544,
                evidence=feature.model_dump(mode="json", exclude={"support"}),
            )
            assert feature.method.resolution.reason is None
            if name == "A_top_L":
                assert not feature.valid and feature.reason == "target_not_found"
                from tests.integration.metrology3d.boundary_audit import (
                    audit_surface,
                    verify_endpoint_context,
                )

                from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
                    materialize_positions,
                )

                points, rows = materialize_positions(
                    runtime,
                    selected,
                    factor=12544,
                    with_sources=True,
                    cancel=lambda: None,
                )
                evaluation = feature.method.resolution.evaluation.model_dump(
                    mode="json"
                )
                audit, section = audit_surface(
                    points,
                    rows,
                    evaluation,
                    config.surface.model_dump(),
                    budget=limits.max_working_bytes,
                    tolerance=1e-8,
                )
                assert audit["segment_count"] == 25
                assert audit["rejection_combinations"] == {
                    "passed": 944,
                    "edge": 18,
                    "edge+alpha": 580,
                }
                assert len(audit["endpoints"]) == 50
                assert all(
                    len(end["neighbor_faces"]) == 2
                    and sum(f["kept"] for f in end["neighbor_faces"]) == 1
                    for end in audit["endpoints"]
                )
                context, _ = crop_roi(
                    runtime,
                    cloud,
                    boxes("context", [[-39, -27, -25, -12, -20, -12]]),
                    cancel=lambda: None,
                )
                surrounding, source_rows = materialize_positions(
                    runtime,
                    context,
                    factor=12544,
                    with_sources=True,
                    cancel=lambda: None,
                )
                audit["context_check"] = verify_endpoint_context(
                    surrounding,
                    source_rows,
                    evaluation,
                    audit,
                )
                report["steel_boundary_audit"] = audit
                # 诊断位置不进入产品尺寸，全部临时数组在后续弧验证前释放。
                del points, rows, section, surrounding, source_rows
                result = measure_extents(
                    runtime,
                    extent_parameters(
                        evaluation=dict(
                            kind="feature", frame_id="fixture", length_unit="mm"
                        ),
                        source=dict(
                            kind="boundary",
                            selection=dict(
                                feature_id=feature.feature_id, segment_ids=[name]
                            ),
                        ),
                        outputs=[
                            dict(component="u", item_id="W"),
                            dict(component="v", item_id="L"),
                        ],
                    ),
                    groups=[boundary],
                    cancel=lambda: None,
                )
                assert all(
                    not item.valid and item.value is None for item in result.items
                )
                report["measurements"]["L-W"] = result.model_dump(mode="json")
            else:
                assert feature.valid, feature.reason
                fitted = fit_boundary(runtime, boundary, circle(), cancel=lambda: None)
                assert fitted.items[0].valid, fitted.items[0].quality.model_dump()
                result = measure_hole(runtime, [fitted], hole(), cancel=lambda: None)
                assert result.items[0].valid, result.items[0].reason
                report["measurements"]["S1.D"] = result.model_dump(mode="json")
                report["circle_verification"] = verify_circle(
                    runtime, boundary, fitted, result, service
                )
                print("S1.D", result.items[0].value, flush=True)
            print(name, feature.valid, feature.reason, selected.point_count, flush=True)
    finally:
        errors = scope.close()
        report["cleanup"] = dict(
            errors=[str(e) for e in errors], live_array_bytes=runtime.budget.used
        )
        report["elapsed_seconds"] = monotonic() - started
        target = request.config.getoption("--cloud-report-dir")
        directory = Path(target) if target else tmp_path
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "representative-recipe.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), "utf-8"
        )
        assert not errors and runtime.budget.used == 0
