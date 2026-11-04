"""完整真实输入的去噪覆盖；不修改正式测量图或把算法采样当作原云。"""

import json
from pathlib import Path
import platform
from time import perf_counter

import numpy as np
import pytest

from backend.contracts.workflows.cloud_preprocess import DenoiseCloudParameters
from custom_nodes.metrology3d_nodes.shared.denoise import denoise_mask
from tests.integration.metrology3d.test_published_runtime import sample_array


def test_complete_cloud_denoise(tmp_path, request):
    """读取完整样本；分块独立遍历全云核对六个查询，不调用 KDTree 生成真值。"""
    sample = request.config.getoption("--cloud-sample")
    if not sample:
        pytest.skip("完整样本必须显式提供")
    binary = tmp_path / "cloud.bin"
    descriptor = sample_array(Path(sample), binary)
    report = dict(
        platform=platform.platform(), points=descriptor.point_count, methods=[]
    )
    with binary.open("rb") as source:
        import mmap

        with mmap.mmap(source.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
            points = np.ndarray((descriptor.point_count, 3), dtype="<f4", buffer=mapped)
            queries = np.linspace(0, len(points) - 1, 6, dtype=int)
            for settings in (
                dict(kind="radius", radius=0.1, min_neighbors=3),
                dict(kind="statistical", neighbors=8, std_ratio=2),
            ):
                p = DenoiseCloudParameters(settings=settings)
                started = perf_counter()
                mask, summary = denoise_mask(
                    points,
                    p.settings,
                    max_working_bytes=4 * 1024**3,
                    chunk_rows=4096,
                    cancel=lambda: None,
                )
                seconds = perf_counter() - started
                for row in queries:
                    count, nearest = 0, np.full(8, np.inf)
                    for start in range(0, len(points), 262144):
                        block = points[start : start + 262144].astype(float)
                        distance = np.linalg.norm(
                            block - points[row].astype(float), axis=1
                        )
                        if start <= row < start + len(block):
                            distance[row - start] = np.inf
                        if settings["kind"] == "radius":
                            count += np.count_nonzero(distance <= settings["radius"])
                        else:
                            nearest = np.partition(np.r_[nearest, distance], 7)[:8]
                    expected = (
                        count >= 3
                        if settings["kind"] == "radius"
                        else nearest.mean() <= summary["distance_threshold"]
                    )
                    assert bool(mask[row]) == bool(expected)
                report["methods"].append(
                    dict(
                        settings=settings,
                        kept=int(mask.sum()),
                        removed=int((~mask).sum()),
                        seconds=seconds,
                        independent_queries=6,
                        summary=summary,
                    )
                )
                del mask
            del points
    destination = request.config.getoption("--cloud-report-dir")
    if destination:
        target = Path(destination)
        target.mkdir(parents=True, exist_ok=True)
        (target / f"denoise-{platform.system().lower()}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
