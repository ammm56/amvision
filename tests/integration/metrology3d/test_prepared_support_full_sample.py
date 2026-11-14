"""完整工件及正式配方支持的索引/全扫描对照，不替代 B17 发布验收。"""

import json
from math import fsum, sqrt
from pathlib import Path

import numpy as np
import pytest

from backend.contracts.workflows.geometry3d import (
    CropCloudParameters,
    FitPlaneParameters,
)
from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes.metrology3d_nodes.shared.fit_plane import fit_plane
from custom_nodes.metrology3d_nodes.shared.io.read_file import read_file_reference
from custom_nodes.metrology3d_nodes.shared.measurement_reference import (
    reference_coverage,
)
from custom_nodes.metrology3d_nodes.shared.prepared_plane_support import (
    prepare_plane_support,
)
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_prepared_support import settings, assert_same
from tests.test_metrology3d_datum_deviation import parameters as deviation_parameters
from custom_nodes.metrology3d_nodes.shared.datum_deviation import (
    measure_datum_deviation,
)
from custom_nodes.metrology3d_nodes.shared.deviation_rows import validate_deviation_rows


def test_complete_workpiece_datum_body_and_top_support(tmp_path, request):
    """读取全部原始行，使用已有 D/B/T 参数，不为通过对照更改拟面门槛。"""
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
    assert (
        meta.checksum
        == "ff2b9e0ef2d6c45af02c4bf8d474cd82f77f86ad92bd371a4c0f71b1b90d116b"
    )
    file = dict(
        transport_kind="storage",
        storage_ref="object-store",
        object_key=meta.object_key,
        file_name="sample.ply",
        media_type=meta.media_type,
        content_length=meta.content_length,
        checksum_algorithm="sha256",
        checksum=meta.checksum,
        immutable_version=meta.immutable_version,
    )
    limits = policy(
        max_header_bytes=65536,
        max_decoded_bytes=1024**3,
        max_working_bytes=4 * 1024**3,
        chunk_rows=65536,
        chunk_bytes=4194304,
        max_live_array_bytes=1024**3,
    )
    scope = ResourceScope(kind="prepared-support-full-sample")
    runtime = get_cloud_runtime(scope, run_id="prepared-full-sample", policy=limits)
    template = (
        Path(__file__).resolve().parents[3]
        / "docs/examples/workflows/lithium_workpiece.template.json"
    )
    nodes = {
        n["node_id"]: n["parameters"]
        for n in json.loads(template.read_text("utf-8"))["nodes"]
    }
    report = {}
    parts, groups = {}, {}
    try:
        cloud = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=file,
            options=options(),
            cancel=lambda: None,
        )
        assert cloud.point_count == 14_745_099
        filtered, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=["positions"], sentinels=[]),
            cancel=lambda: None,
        )
        for name in ("D", "A_top.B", "A_top_L.T"):
            source = nodes[f"{name}-crop"]["source"]
            parameters = CropCloudParameters(
                roi_id=source["roi"]["roi_id"],
                rois=[*source["bounds"], source["roi"]],
            )
            part, _ = crop_roi(runtime, filtered, parameters, cancel=lambda: None)
            group = fit_plane(
                runtime,
                part,
                FitPlaneParameters.model_validate(nodes[name]["settings"]),
                cancel=lambda: None,
            )
            feature = group.items[0]
            parts[name], groups[name] = part, group
            assert feature.valid
            points = []
            with runtime.borrow(part) as view:
                for row in np.linspace(0, part.point_count - 1, 8, dtype=int):
                    points.append(
                        view.chunk(int(row), int(row) + 1)["positions"][0].astype(float)
                    )
            points += [np.array([-34.75, -19.0, -14.0]), np.array([100.0, 100.0, 0.0])]
            baseline = runtime.budget.used
            with prepare_plane_support(
                runtime, feature, "reference", cancel=lambda: None
            ) as prepared:
                for point in points:
                    configured = settings(
                        point, radius=0.15, direction=feature.geometry.normal
                    )
                    expected = reference_coverage(
                        runtime, feature, configured, cancel=lambda: None
                    )
                    actual = reference_coverage(
                        runtime,
                        feature,
                        configured,
                        cancel=lambda: None,
                        prepared=prepared,
                    )
                    assert_same(expected, actual)
                    assert actual.support.source_point_count == cloud.point_count
                report[name] = dict(
                    points=part.point_count,
                    queries=len(points),
                    index_budget_bytes=prepared.held_bytes,
                )
            assert runtime.budget.used == baseline
        # 沿既有 Z 测量的基准/门槛，独立计算完整顶面逐点偏差，不改正式配方。
        mode = nodes["A_top_L.Z"]["settings"]["mode"]
        quality = dict(mode["quality_policy"])
        quality["rules"] = [
            r for r in quality["rules"] if r["item_id"].startswith("reference_")
        ]
        configured = deviation_parameters(
            reference_feature_id="D",
            support_radius=mode["support_radius"],
            reference_policy=mode["reference_policy"],
            quality_policy=quality,
        )
        result = measure_datum_deviation(
            runtime,
            parts["A_top_L.T"],
            [groups["D"]],
            configured,
            cancel=lambda: None,
            capture_details=True,
        )
        with runtime.borrow(parts["A_top_L.T"]) as view:
            xyz = view.chunk(0, parts["A_top_L.T"].point_count)["positions"].astype(
                float
            )
            original = view.source_indices(0, len(xyz))
        plane = groups["D"].items[0].geometry
        expected = np.array(
            [
                fsum(float(p[i]) * plane.normal[i] for i in range(3)) + plane.offset
                for p in xyz
            ]
        )
        with result.borrow(runtime) as arrays:
            validate_deviation_rows(
                arrays, result.summary, chunk_rows=256, cancel=lambda: None
            )
            np.testing.assert_array_equal(
                arrays["source_index"][:, 0], original.reshape(-1)
            )
            np.testing.assert_allclose(
                arrays["deviation"][:, 0], expected, rtol=0, atol=1e-12
            )
        summary = result.summary
        assert (
            summary.target_count == 7656
            and summary.source_point_count == cloud.point_count
        )
        assert summary.diagnostic.count == 7656
        assert summary.diagnostic.minimum == pytest.approx(min(expected), abs=1e-12)
        assert summary.diagnostic.maximum == pytest.approx(max(expected), abs=1e-12)
        assert summary.diagnostic.peak_to_valley == pytest.approx(
            max(expected) - min(expected), abs=1e-12
        )
        assert summary.diagnostic.mean == pytest.approx(
            fsum(expected) / len(expected), abs=1e-12
        )
        assert summary.diagnostic.rms == pytest.approx(
            sqrt(fsum(v * v for v in expected) / len(expected)), abs=1e-12
        )
        assert all(i.valid == summary.valid for i in summary.numeric_table().items)
        runtime.storage_scope.close_resource(result.resource_key)
        baseline = runtime.budget.used
        normal = measure_datum_deviation(
            runtime, parts["A_top_L.T"], [groups["D"]], configured, cancel=lambda: None
        )
        assert normal.owner is None and normal.resource_key is None
        assert normal.summary == summary
        assert normal.summary.numeric_table() == summary.numeric_table()
        assert runtime.budget.used == baseline
        report["deviation"] = summary.model_dump(mode="json", exclude={"parameters"})
        report["default_mode"] = dict(
            summary_matches_capture=True, retained_output_array_bytes=0
        )
        print(
            json.dumps(dict(input_points=cloud.point_count, supports=report)),
            flush=True,
        )
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0
