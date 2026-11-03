"""复用完整图取得的 S1/S2 局部数组，交替计时检查，不重新读取原云。"""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np

from custom_nodes.metrology3d_nodes.shared.boundary_surface import (
    _covers_vertices,
    _has_duplicate_projection,
    build_surface,
)


def compare(directory):
    """测量新旧检查，并将完整建面结果与同输入冻结数组逐项核对。"""
    report = []
    for path in sorted(Path(directory).glob("surface-*.npz")):
        with np.load(path, allow_pickle=False) as data:
            points = data["positions"]
            xy = np.ascontiguousarray(
                ((points.astype(float) - data["origin"]) @ data["rotation"])[:, :2]
            )
            faces = data["faces"]
            methods = {
                "duplicate_before": lambda: len(np.unique(xy, axis=0)) != len(xy),
                "duplicate_after": lambda: _has_duplicate_projection(
                    xy, cancel=lambda: None
                ),
                "coverage_before": lambda: len(np.unique(faces)) == len(xy),
                "coverage_after": lambda: _covers_vertices(
                    faces, len(xy), cancel=lambda: None
                ),
            }
            timings = {name: [] for name in methods}
            for order in (tuple(methods), tuple(reversed(methods)), tuple(methods)):
                results = {}
                for name in order:
                    start = perf_counter()
                    results[name] = methods[name]()
                    timings[name].append(perf_counter() - start)
                assert results["duplicate_before"] == results["duplicate_after"]
                assert results["coverage_before"] == results["coverage_after"]
            keys = (
                "origin",
                "rotation",
                "alpha_radius",
                "max_edge_length",
                "max_normal_step",
                "min_projected_area",
                "max_working_bytes",
            )
            kwargs = {
                key: data[key].item() if data[key].ndim == 0 else data[key]
                for key in keys
            }
            started = perf_counter()
            result = build_surface(points, **kwargs, cancel=lambda: None)
            elapsed = perf_counter() - started
            assert result.reason is None
            assert result.candidate_face_count == data["candidate_face_count"]
            np.testing.assert_array_equal(result.faces, faces)
            np.testing.assert_array_equal(result.boundary_edges, data["boundary_edges"])
            report.append(
                dict(
                    points=len(points),
                    timings=timings,
                    surface_seconds=elapsed,
                    exact=True,
                )
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
