"""B08 完整 PLY 四方法的来源守恒及独立逐格对照，不代表工件检测节拍。"""

import json
import platform
import statistics
from hashlib import sha256
from pathlib import Path
from time import perf_counter

import numpy as np
import pytest

from custom_nodes.metrology3d_nodes.shared.height_map import cloud_to_height_map
from tests.integration.metrology3d.full_cloud_sample import sample_array
from tests.point_cloud_support import policy
from tests.test_metrology3d_height_map import parameters
from tests.test_metrology3d_preprocess import make_cloud
from backend.contracts.workflows.height_map3d import HeightMapParameters


def test_complete_height_map_input_and_sources(tmp_path, request):
    """完整点云参与四种聚合；输出格不是显示抽样，也不替换正式测量配方。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "input.bin"
    descriptor = sample_array(Path(sample), binary)
    points = np.memmap(binary, mode="r", shape=(descriptor.point_count, 3), dtype="<f4")
    scope, runtime, source = make_cloud(
        unit="mm",
        coordinates=points,
        runtime_policy=policy(
            max_working_bytes=4 * 1024**3,
            max_live_array_bytes=1024**3,
            max_decoded_bytes=1_000_000_000,
            chunk_rows=65536,
        ),
    )
    baseline = runtime.budget.used
    records = []
    try:
        for method in ("minimum", "maximum", "mean", "median"):
            raw = parameters(method).model_dump()
            # 完整样本实测范围 X[-48.498,48.522003]、Y[-148.47,0]；固定测试格覆盖全云。
            raw.update(width=256, height=512)
            raw["grid"].update(origin=(-64, -192, 0), column_step=0.5, row_step=0.5)
            p = HeightMapParameters.model_validate(raw)
            started = perf_counter()
            result = cloud_to_height_map(runtime, source, p, cancel=lambda: None)
            elapsed = perf_counter() - started
            assert result.outside_count == 0
            digest = sha256()
            with result.borrow(runtime) as a:
                assert a["counts"].sum() == len(points)
                assert a["heights"].dtype == np.dtype("<f4")
                np.testing.assert_array_equal(a["source_rows"], a["input_rows"])
                np.testing.assert_array_equal(
                    np.sort(a["source_rows"][:, 0]), np.arange(len(points))
                )
                occupied = np.flatnonzero(a["counts"][:, 0])
                for cell in occupied[np.linspace(0, len(occupied) - 1, 7, dtype=int)]:
                    row, column = divmod(int(cell), p.width)
                    cx, cy = -64 + column * 0.5, -192 + row * 0.5
                    expected = []
                    for start in range(0, len(points), 65536):
                        block = points[start : start + 65536]
                        keep = (
                            (block[:, 0] >= cx - 0.25)
                            & (block[:, 0] < cx + 0.25)
                            & (block[:, 1] >= cy - 0.25)
                            & (block[:, 1] < cy + 0.25)
                        )
                        expected.extend((np.flatnonzero(keep) + start).tolist())
                    lo, hi = a["member_offsets"][cell : cell + 2, 0]
                    np.testing.assert_array_equal(a["input_rows"][lo:hi, 0], expected)
                    values = [float(z) for z in points[expected, 2]]
                    target = {
                        "minimum": min,
                        "maximum": max,
                        "mean": statistics.mean,
                        "median": statistics.median,
                    }[method](values)
                    assert a["heights"][cell, 0] == np.float32(target)
                for key in sorted(a):
                    digest.update(key.encode("ascii"))
                    digest.update(a[key].tobytes())
            records.append(
                dict(
                    method=method,
                    seconds=elapsed,
                    occupied_count=result.occupied_count,
                    outside_count=result.outside_count,
                    max_rounding_error=result.max_rounding_error,
                    sha256=digest.hexdigest(),
                )
            )
            runtime.storage_scope.close_resource(result.resource_key)
            assert runtime.budget.used == baseline
    finally:
        assert scope.close() == () and runtime.budget.used == 0
        points._mmap.close()
    report = dict(
        platform=platform.system(),
        point_count=descriptor.point_count,
        grid=[512, 256],
        step_mm=0.5,
        records=records,
    )
    print(json.dumps(report), flush=True)
    destination = request.config.getoption("--cloud-report-dir")
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"height-map-{platform.system().lower()}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
