"""Open3D 原生采样边界准入对照；失败返回非零，不作为产品降级算法。"""

import json

import numpy as np


def audit():
    """规则平面的外圈有独立整数真值，刚体变换/法向反转不应改变掩码。"""
    import open3d as o3d

    grid = np.asarray(list(np.ndindex(5, 5)), dtype=np.float64)
    hole_grid = np.asarray(list(np.ndindex(9, 9)), dtype=np.float64)
    hole_grid = hole_grid[~((hole_grid >= 3) & (hole_grid <= 5)).all(axis=1)]
    occupied = {tuple(point) for point in hole_grid}
    hole_expected = np.asarray(
        [
            any(
                (x + dx, y + dy) not in occupied
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
            )
            for x, y in hole_grid
        ]
    )
    scenarios = (
        ("outer", grid, ((grid == 0) | (grid == 4)).any(axis=1), 1.5),
        ("observed_gap", hole_grid, hole_expected, 1.01),
    )
    angle = 0.3
    frames = {
        "z": np.eye(3),
        "negative_z": np.diag([1, -1, -1]),
        "x": np.asarray([[0, 0, 1], [1, 0, 0], [0, 1, 0]]),
        "y": np.asarray([[0, 1, 0], [0, 0, 1], [1, 0, 0]]),
        "oblique": np.asarray(
            [
                [np.cos(angle), 0, np.sin(angle)],
                [0, 1, 0],
                [-np.sin(angle), 0, np.cos(angle)],
            ]
        ),
    }
    cases = []
    for scenario, grid, expected, radius in scenarios:
        source = np.column_stack((grid, np.zeros(len(grid))))
        for dtype in (np.float32, np.float64):
            for name, rotation in frames.items():
                for sign in (-1, 1):
                    positions = np.ascontiguousarray(
                        source @ rotation.T + [31, -19, 7], dtype=dtype
                    )
                    normals = np.tile(sign * rotation[:, 2], (len(source), 1)).astype(
                        dtype
                    )
                    cloud = o3d.t.geometry.PointCloud(o3d.core.Tensor(positions))
                    cloud.point.normals = o3d.core.Tensor(normals)
                    _, native = cloud.compute_boundary_points(radius, 16, 120.0)
                    actual = native.numpy()
                    cases.append(
                        dict(
                            scenario=scenario,
                            dtype=np.dtype(dtype).name,
                            frame=name,
                            normal_sign=sign,
                            expected_count=int(expected.sum()),
                            actual_count=int(actual.sum()),
                            differing_rows=np.flatnonzero(actual != expected).tolist(),
                            passed=bool(np.array_equal(actual, expected)),
                        )
                    )
    return dict(
        open3d_version=o3d.__version__,
        passed=all(case["passed"] for case in cases),
        cases=cases,
    )


def audit_plane():
    """直接核对既有 RANSAC 原生调用的独立支持真值，不绕过平台版本准入。"""
    import open3d as o3d

    cases = []
    xy = np.asarray(list(np.ndindex(10, 10)), dtype=np.float64)
    for dtype in (np.float32, np.float64):
        for inclined in (False, True):
            heights = 0.2 * xy[:, 0] - 0.3 * xy[:, 1] if inclined else np.zeros(100)
            inliers = np.column_stack((xy, heights + 7)).astype(dtype)
            outliers = inliers[:20].copy()
            outliers[:, 2] += 2
            points = np.vstack((inliers, outliers))
            saved = points.copy()
            cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(points))
            model, rows = cloud.segment_plane(1e-4, 3, 300, probability=0.999999)
            residual = np.abs(inliers.astype(np.float64) @ model[:3] + model[3])
            passed = (
                np.array_equal(np.sort(rows), np.arange(100))
                and np.array_equal(saved, points)
                and np.isfinite(model).all()
                and np.max(residual) < 1e-5
            )
            cases.append(
                dict(dtype=np.dtype(dtype).name, inclined=inclined, passed=bool(passed))
            )
    return dict(
        open3d_version=o3d.__version__,
        cases=cases,
        passed=all(c["passed"] for c in cases),
    )


if __name__ == "__main__":
    result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
