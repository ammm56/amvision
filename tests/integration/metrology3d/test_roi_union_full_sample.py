"""完整工件只验并集的数据链路，不把测试 ROI 当工程配方或尺寸真值。"""

from pathlib import Path

import numpy as np
import pytest

from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.service.application.runtime.resource_scope import ResourceScope
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.filter_valid import filter_valid
from custom_nodes._metrology3d_nodes.shared.io.read_file import read_file_reference
from tests.point_cloud_support import create_resource_service, options, policy
from tests.test_metrology3d_crop import box, parameters
from tests.test_metrology3d_roi_union import union


def test_complete_sample_five_region_union_and_original_rows(tmp_path, request):
    """逐块独立轴向比较并核对每个源行号，包含五个分离的候选窗口。"""
    supplied = request.config.getoption("--cloud-sample")
    if not supplied:
        pytest.skip("完整样本必须由 --cloud-sample 显式提供")
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
        max_decoded_bytes=400000000,
        max_working_bytes=134217728,
        chunk_rows=65536,
        chunk_bytes=4194304,
        max_live_array_bytes=800000000,
    )
    scope = ResourceScope(kind="workflow")
    runtime = get_cloud_runtime(scope, run_id="union-full-sample", policy=limits)
    windows = [
        (-45, -37, -145, -125),
        (-12, 20, -145, -132),
        (22, 44, -30, -4),
        (-12, 24, -25, -4),
        (-44, -37, -12, -3),
    ]
    try:
        raw = read_file_reference(
            runtime=runtime,
            object_store=service.storage,
            project_id="test",
            file=file,
            options=options(),
            cancel=lambda: None,
        )
        assert raw.point_count == 14745099
        cloud, _ = filter_valid(
            runtime,
            raw,
            FilterCloudValid(finite_fields=["positions"], sentinels=[]),
            cancel=lambda: None,
        )
        low, high = np.inf, -np.inf
        with runtime.borrow(cloud) as view:
            for start in range(0, cloud.point_count, limits.chunk_rows):
                points = view.chunk(
                    start, min(start + limits.chunk_rows, cloud.point_count)
                )["positions"]
                low, high = (
                    min(low, float(points[:, 2].min())),
                    max(high, float(points[:, 2].max())),
                )
        members = []
        for i, (xmin, xmax, ymin, ymax) in enumerate(windows):
            roi = box()
            roi["roi_id"] = f"window-{i}"
            # Z 范围只为本次数据链路测试覆盖全高，不冻结生产工程 ROI。
            roi["geometry"].update(
                center=[(xmin + xmax) / 2, (ymin + ymax) / 2, (low + high) / 2],
                size=[xmax - xmin, ymax - ymin, high - low + 2],
            )
            members.append(roi)
        config = parameters(
            union("five-regions", *(r["roi_id"] for r in members)), *members
        )
        selected, summary = crop_roi(runtime, cloud, config, cancel=lambda: None)
        cursor = 0
        with runtime.borrow(cloud) as source, runtime.borrow(selected) as target:
            for start in range(0, cloud.point_count, limits.chunk_rows):
                stop = min(start + limits.chunk_rows, cloud.point_count)
                points = source.chunk(start, stop)["positions"]
                expected = np.zeros(len(points), dtype=bool)
                for xmin, xmax, ymin, ymax in windows:
                    expected |= (
                        (points[:, 0] >= xmin)
                        & (points[:, 0] <= xmax)
                        & (points[:, 1] >= ymin)
                        & (points[:, 1] <= ymax)
                    )
                count = int(expected.sum())
                np.testing.assert_array_equal(
                    target.source_indices(cursor, cursor + count),
                    source.source_indices(start, stop)[expected],
                )
                np.testing.assert_array_equal(
                    target.chunk(cursor, cursor + count)["positions"], points[expected]
                )
                cursor += count
        assert cursor == selected.point_count == summary["kept_count"] and cursor > 0
        assert runtime.source_point_count(selected) == raw.point_count
        print(
            f"full sample rows={raw.point_count}, union rows={cursor}, fields={len(selected.fields)}"
        )
    finally:
        assert not scope.close() and runtime.budget.used == 0
