"""完整原云法向验收，计算时间、显式测试预算与工程质量参数分开记录。"""

import json
import platform
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

from backend.contracts.workflows.cloud_normals import EstimateNormalsParameters
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
)
from custom_nodes.metrology3d_nodes.shared.estimate_normals import estimate_normals
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.integration.metrology3d.test_published_runtime import sample_array
from tests.point_cloud_support import policy, create_resource_service
from tests.test_metrology3d_preprocess import make_cloud


def sample_parameters(kind="knn", *, frame_id="fixture", coarse=False):
    """仅工件法向工程对照，不替代原测量图门禁，不作为节点默认值。"""
    return EstimateNormalsParameters(
        neighborhood=(
            dict(kind=kind, neighbors=16, support=dict(kind="unrestricted"))
            if kind == "knn"
            else dict(
                kind=kind,
                radius=2.0 if coarse else 0.25,
                **(dict(max_neighbors=16) if kind == "hybrid" else {}),
            )
        ),
        quality=dict(
            min_support_points=6,
            min_normal_gap=0.02,
            max_rms=0.03,
            max_surface_variation=0.1,
        ),
        orientation=dict(kind="direction", direction=[0, 0, 1], min_abs_cosine=0.1),
        frame_id=frame_id,
        length_unit="mm",
        existing_normals="reject",
        diagnostics=True,
    )


def test_normals_complete_original_cloud(tmp_path, request):
    """所有原始点都参与；独立全云距离排序和 SVD 核对选定位置。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "input.bin"
    descriptor = sample_array(Path(sample), binary)
    points = np.memmap(binary, mode="r", shape=(descriptor.point_count, 3), dtype="<f4")
    # 当前完整原云的诊断输出和索引需显式 8 GiB 工作预算，不改生产配置。
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(
            max_working_bytes=8 * 1024**3,
            max_live_array_bytes=2 * 1024**3,
            max_decoded_bytes=1_000_000_000,
            chunk_rows=65536,
        ),
    )
    report = dict(platform=platform.platform(), point_count=len(points))
    try:
        p = sample_parameters(frame_id=source.spatial.frame_id)
        started = perf_counter()
        out, summary = estimate_normals(runtime, source, p, cancel=lambda: None)
        report.update(seconds=perf_counter() - started, summary=summary)
        print(json.dumps(report), flush=True)
        assert summary["valid_count"] > 0
        service = create_resource_service(tmp_path / "assets")
        assets = CloudAssetPolicy(
            max_asset_bytes=900000000,
            max_archive_bytes=1000000000,
            chunk_bytes=4 * 1024**2,
        )
        asset = save_cloud(
            runtime,
            out,
            service=service,
            project_id="test",
            name="normals",
            mode="derived",
            write_identity="d" * 64,
            policy=assets,
            cancel=lambda: None,
        )
        restored = read_asset(
            runtime,
            asset,
            service=service,
            project_id="test",
            policy=assets,
            cancel=lambda: None,
        )
        assert restored.normal_info == out.normal_info
        with runtime.borrow(out) as a, runtime.borrow(restored) as b:
            for start in range(0, len(points), 65536):
                stop = min(start + 65536, len(points))
                first, second = a.chunk(start, stop), b.chunk(start, stop)
                np.testing.assert_array_equal(first["positions"], points[start:stop])
                np.testing.assert_array_equal(
                    b.source_indices(start, stop), np.arange(start, stop)
                )
                for key in first:
                    np.testing.assert_array_equal(first[key], second[key])
            for row in np.linspace(0, len(points) - 1, 5, dtype=int):
                distance = np.empty(len(points), dtype="f8")
                for start in range(0, len(points), 65536):
                    delta = points[start : start + 65536].astype("f8") - points[
                        row
                    ].astype("f8")
                    distance[start : start + len(delta)] = np.linalg.norm(delta, axis=1)
                distance[row] = np.inf
                selected = np.argsort(distance, kind="stable")[:16]
                support = points[np.r_[row, selected]].astype("f8")
                _, singular, vectors = np.linalg.svd(
                    support - support.mean(axis=0), full_matrices=False
                )
                observed = a.chunk(int(row), int(row) + 1)
                np.testing.assert_allclose(
                    observed["normal_rms"][0, 0], singular[-1] / np.sqrt(17), atol=2e-7
                )
                if observed["normal_valid"][0, 0]:
                    assert abs(np.dot(observed["normals"][0], vectors[-1])) > 1 - 1e-6
                del distance
        report["save_restore_all_fields"] = True
    finally:
        assert scope.close() == () and runtime.budget.used == 0
        del points
    destination = request.config.getoption("--cloud-report-dir")
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"normals-{platform.system().lower()}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
