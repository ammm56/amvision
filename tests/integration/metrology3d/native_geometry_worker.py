"""真实原生调用的验收进程，不进入生产节点目录。"""

import argparse
import json
from pathlib import Path


def main():
    """仅提供可观察的真实原生工作，不用 sleep 代替算法阻塞。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["hold", "resources"])
    parser.add_argument("--marker", type=Path)
    args = parser.parse_args()
    import numpy as np
    import open3d
    import psutil

    assert open3d.__version__ == "0.20.0"
    if args.mode == "hold":
        points = np.random.default_rng(123).uniform(-10, 10, (500000, 3))
        cloud = open3d.geometry.PointCloud(open3d.utility.Vector3dVector(points))
        args.marker.write_text("native-entering", encoding="utf-8")
        cloud.segment_plane(
            distance_threshold=1e-9,
            ransac_n=3,
            num_iterations=1000000,
            probability=0.999999,
        )
        args.marker.write_text("native-completed", encoding="utf-8")
    else:
        from tests.integration.metrology3d.test_geometry_native import native_case

        process = psutil.Process()
        samples = []
        for _ in range(20):
            native_case(np.float64, "inclined")
            samples.append(
                dict(rss=process.memory_info().rss, threads=process.num_threads())
            )
        print(json.dumps(dict(cycles=20, samples=samples)), flush=True)


if __name__ == "__main__":
    main()
