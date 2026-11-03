"""同次完整局部截面对照：来源逐项相同，交替计时，不计文件读取。"""

import argparse
import json
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

import numpy as np

from custom_nodes.metrology3d_nodes.shared import boundary_section as section
from tests.integration.metrology3d.test_section_sources import scalar_sources


def compare(directory):
    """冻结数组检查所有输出，再比较同一求交仅端点匹配不同的成本。"""
    report = []
    fields = (
        "positions",
        "edges",
        "source_vertices",
        "weights",
        "face_offsets",
        "face_indices",
    )
    for path in sorted(Path(directory).glob("section-*.npz")):
        with np.load(path, allow_pickle=False) as data:
            kwargs = {
                key: data[key].item() if data[key].ndim == 0 else data[key]
                for key in (
                    "origin",
                    "normal",
                    "numeric_tolerance",
                    "max_working_bytes",
                )
            }
            points, faces = data["positions"], data["faces"]
            batch = section._endpoint_sources
            timings = {"scalar": [], "batch": []}
            # 原生库首次导入不偏置先运行的一方；真实工作流首次成本仍由整图计时覆盖。
            section.intersect_surface(points, faces, **kwargs, cancel=lambda: None)
            for order in (
                ("scalar", "batch"),
                ("batch", "scalar"),
                ("scalar", "batch"),
            ):
                for method in order:
                    with patch.object(
                        section,
                        "_endpoint_sources",
                        scalar_sources if method == "scalar" else batch,
                    ):
                        started = perf_counter()
                        result = section.intersect_surface(
                            points, faces, **kwargs, cancel=lambda: None
                        )
                        timings[method].append(perf_counter() - started)
                    assert result.reason is None
                    for key in fields:
                        np.testing.assert_array_equal(
                            getattr(result, key), data["result_" + key]
                        )
            report.append(
                dict(points=len(points), faces=len(faces), timings=timings, exact=True)
            )
    assert len(report) == 2
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    Path(args.report).write_text(
        json.dumps(compare(args.directory), indent=2) + "\n", encoding="utf-8"
    )
