"""实际钢片点集的精确邻域计数对照，不改变空间图或质量条件。"""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.spatial import cKDTree


def compare(directory):
    """全部十二个冻结局部输入交替执行；只输出有界计时和逐项一致性。"""
    report = []
    for path in sorted(directory.glob("metric-*.npz")):
        with np.load(path, allow_pickle=False) as data:
            points = data["positions"]
            settings = json.loads(str(data["settings"]))
            mask = (
                points[:, 2] > 0
                if settings["profiles"]["foreground"] == "above"
                else points[:, 2] < 0
            )
            xy = np.ascontiguousarray(points[mask, :2])
        tree = cKDTree(xy, copy_data=False)
        radius = settings["selection"]["connection_distance"]
        timings = {"tree_pairs": [], "chunk_lengths": []}
        expected = None
        for order in (tuple(timings), tuple(reversed(timings)), tuple(timings)):
            for kind in order:
                started = perf_counter()
                if kind == "tree_pairs":
                    count = int(tree.count_neighbors(tree, radius))
                else:
                    count = sum(
                        int(
                            tree.query_ball_point(
                                xy[start : start + 4096],
                                radius,
                                eps=0,
                                workers=1,
                                return_length=True,
                            ).sum()
                        )
                        for start in range(0, len(xy), 4096)
                    )
                timings[kind].append(perf_counter() - started)
                if expected is None:
                    expected = count
                assert count == expected
        report.append(
            dict(
                input=path.name,
                points=len(xy),
                count=count,
                timings=timings,
                exact=True,
            )
        )
    assert len(report) == 12
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    args.report.write_text(
        json.dumps(compare(args.directory), indent=2), encoding="utf-8"
    )
