"""完整工件重采样；原始样本身份、逐行来源及资源回收均实际核对。"""

import json
import platform
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

from backend.contracts.workflows.cloud_preprocess import ResampleCloudParameters
from backend.contracts.workflows.point_cloud import CloudField
from backend.contracts.workflows.point_cloud_runtime import CloudLocalSource
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes.metrology3d_nodes.shared.resample import resample_cloud
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from tests.integration.metrology3d.test_published_runtime import sample_array
from tests.point_cloud_support import policy, spatial, create_resource_service
from tests.test_point_cloud_runtime import own
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CloudAssetPolicy,
)


def test_resample_complete_cloud(tmp_path, request):
    """三方法使用全部输入；抽查的成员和质心从完整云独立距离/格判断取得。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "cloud.bin"
    descriptor = sample_array(Path(sample), binary)
    points = np.memmap(binary, mode="r", shape=(descriptor.point_count, 3), dtype="<f4")
    report = dict(platform=platform.platform(), point_count=len(points), methods=[])
    for kind in ("stride", "voxel-representative", "voxel-centroid"):
        scope = ResourceScope(kind="resample-full")
        runtime = get_cloud_runtime(
            scope,
            run_id="full",
            policy=policy(
                max_working_bytes=4 * 1024**3,
                max_live_array_bytes=1024**3,
                max_decoded_bytes=1_000_000_000,
                chunk_rows=65536,
            ),
        )
        try:
            ref = runtime.register_source(
                owner=own(runtime, dict(positions=points)),
                point_count=len(points),
                fields=(
                    CloudField(
                        name="positions",
                        semantic="position",
                        dtype="float32",
                        components=3,
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
            p = ResampleCloudParameters(
                settings=(
                    dict(kind=kind, every_k_points=3, offset=1)
                    if kind == "stride"
                    else dict(
                        kind=kind,
                        voxel_size=1.0,
                        grid_origin=(0.0, 0.0, 0.0),
                        frame_id=ref.spatial.frame_id,
                        length_unit="mm",
                        **(
                            dict(max_position_error=0.0001, attributes="positions-only")
                            if kind == "voxel-centroid"
                            else {}
                        ),
                    )
                )
            )
            started = perf_counter()
            out, summary = resample_cloud(runtime, ref, p, cancel=lambda: None)
            elapsed = perf_counter() - started
            digest = sha256()
            with runtime.borrow(out) as view:
                members = []
                for start in range(0, out.point_count, 65536):
                    stop = min(start + 65536, out.point_count)
                    digest.update(view.chunk(start, stop)["positions"].tobytes())
                    if kind == "voxel-centroid":
                        data = view.lineage_chunk(start, stop)
                        members.append(data["source_rows"][:, 0].copy())
                    else:
                        ids = view.source_indices(start, stop)
                        assert (
                            view.chunk(start, stop)["positions"].tobytes()
                            == points[ids].tobytes()
                        )
                        if kind == "stride":
                            np.testing.assert_array_equal(
                                ids, 1 + np.arange(start, stop, dtype="u8") * 3
                            )
                if kind == "voxel-centroid":
                    np.testing.assert_array_equal(
                        np.sort(np.concatenate(members)), np.arange(len(points))
                    )
                    for row in np.linspace(0, out.point_count - 1, 3, dtype=int):
                        data = view.lineage_chunk(int(row), int(row) + 1)
                        expected = []
                        for start in range(0, len(points), 65536):
                            keys = np.floor(
                                points[start : start + 65536].astype(float)
                            ).astype("i8")
                            expected.extend(
                                (
                                    np.flatnonzero(
                                        np.all(keys == data["voxel_keys"][0], axis=1)
                                    )
                                    + start
                                ).tolist()
                            )
                        np.testing.assert_array_equal(
                            np.sort(data["source_rows"][:, 0]), expected
                        )
                        np.testing.assert_allclose(
                            view.chunk(int(row), int(row) + 1)["positions"][0],
                            points[expected].astype(float).mean(axis=0),
                            rtol=0,
                            atol=0.0001,
                        )
            if kind == "voxel-centroid":
                service = create_resource_service(tmp_path / "assets")
                ap = CloudAssetPolicy(
                    max_asset_bytes=600000000,
                    max_archive_bytes=610000000,
                    chunk_bytes=4 * 1024**2,
                )
                asset = save_cloud(
                    runtime,
                    out,
                    service=service,
                    project_id="test",
                    mode="derived",
                    name="centroid",
                    write_identity="c" * 64,
                    policy=ap,
                    cancel=lambda: None,
                )
                restored = read_asset(
                    runtime,
                    asset,
                    service=service,
                    project_id="test",
                    policy=ap,
                    cancel=lambda: None,
                )
                assert (
                    restored.point_count == out.point_count
                    and runtime.source_point_count(restored) == len(points)
                )
                # B03 内部运行链路使用同一完整云生成的所有质心，不改原测量图。
                from custom_nodes.metrology3d_nodes.shared.estimate_normals import (
                    estimate_normals,
                )
                from tests.test_metrology3d_normal_estimation import (
                    parameters as normal_parameters,
                )

                normals, normal_summary = estimate_normals(
                    runtime,
                    restored,
                    normal_parameters(
                        frame_id=restored.spatial.frame_id,
                        orientation=dict(kind="unoriented"),
                    ),
                    cancel=lambda: None,
                )
                assert normals.point_count == restored.point_count
                assert normals.voxel_aggregation == restored.voxel_aggregation
                with (
                    runtime.borrow(restored) as original,
                    runtime.borrow(normals) as calculated,
                ):
                    for start in range(0, normals.point_count, 65536):
                        stop = min(start + 65536, normals.point_count)
                        np.testing.assert_array_equal(
                            original.chunk(start, stop)["positions"],
                            calculated.chunk(start, stop)["positions"],
                        )
                        for name, values in original.lineage_chunk(start, stop).items():
                            np.testing.assert_array_equal(
                                values, calculated.lineage_chunk(start, stop)[name]
                            )
                report["normal_runtime"] = normal_summary
            report["methods"].append(
                dict(
                    summary=summary,
                    seconds=elapsed,
                    positions_sha256=digest.hexdigest(),
                )
            )
        finally:
            assert not scope.close()
            assert runtime.budget.used == 0
    del points
    destination = request.config.getoption("--cloud-report-dir")
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"resample-{platform.system().lower()}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
