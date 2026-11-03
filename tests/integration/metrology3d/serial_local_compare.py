"""同一完整图的局部支持对照；不重复读取原文件，不作为正式节拍。"""

import argparse
import json
from pathlib import Path
from time import perf_counter

import numpy as np
from scipy.sparse import coo_array
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from pytest import MonkeyPatch


def compare_metric(path):
    """对全邻接比较公共构图路径，保留节点、边及分量标签一致性。"""
    with np.load(path, allow_pickle=False) as data:
        uvh = data["positions"]
        settings = json.loads(str(data["settings"]))
        above = settings["profiles"]["foreground"] == "above"
        rows = np.flatnonzero(uvh[:, 2] > 0 if above else uvh[:, 2] < 0)
        points = np.ascontiguousarray(uvh[rows, :2])
        expected_labels = data["labels"].copy()
        expected_count = int(data["component_count"])
    methods = {
        "original": (np.int64, np.uint8),
        "index32": (np.int32, np.uint8),
        "index32-float64": (np.int32, np.float64),
    }
    timings = {key: [] for key in methods}
    expected = None
    for order in (tuple(methods), tuple(reversed(methods)), tuple(methods)):
        for name in order:
            start = perf_counter()
            tree = cKDTree(points, copy_data=False)
            radius = settings["selection"]["connection_distance"]
            count = (int(tree.count_neighbors(tree, radius)) - len(points)) // 2
            assert max(len(points), count) < np.iinfo(np.int32).max
            pairs = tree.query_pairs(radius, eps=0, output_type="ndarray")
            index_dtype, value_dtype = methods[name]
            indices = pairs.astype(index_dtype, copy=False)
            graph = coo_array(
                (
                    np.ones(len(pairs), dtype=value_dtype),
                    (indices[:, 0], indices[:, 1]),
                ),
                shape=(len(points), len(points)),
            ).tocsr()
            components, labels = connected_components(graph, directed=False)
            timings[name].append(perf_counter() - start)
            assert len(pairs) == count and components == expected_count
            np.testing.assert_array_equal(labels, expected_labels)
            if expected is None:
                expected = graph.copy()
            else:
                np.testing.assert_array_equal(graph.indptr, expected.indptr)
                np.testing.assert_array_equal(graph.indices, expected.indices)
                np.testing.assert_array_equal(graph.data, expected.data)
    return dict(
        input=path.name, points=len(points), pairs=count, timings=timings, exact=True
    )


def compare_section(path):
    """两向原生求交逐项与捕获前结果一致，不只比较最后直径。"""
    import trimesh.intersections
    from custom_nodes.metrology3d_nodes.shared.boundary_section import intersect_surface

    with np.load(path, allow_pickle=False) as data:
        points, faces = data["positions"], data["faces"]
        kwargs = {
            key: data[key].item() if data[key].ndim == 0 else data[key]
            for key in ("origin", "normal", "numeric_tolerance", "max_working_bytes")
        }
        expected = {
            key: data["result_" + key].copy()
            for key in (
                "positions",
                "edges",
                "source_vertices",
                "weights",
                "face_offsets",
                "face_indices",
            )
        }
    original = trimesh.intersections.mesh_plane

    def uncached(mesh, normal, origin, **kwargs):
        return original(mesh, normal, origin, return_faces=True)

    timings = {"uncached_native": [], "cached_candidates": []}
    for order in (tuple(timings), tuple(reversed(timings)), tuple(timings)):
        for name in order:
            with MonkeyPatch.context() as patch:
                if name == "uncached_native":
                    patch.setattr(trimesh.intersections, "mesh_plane", uncached)
                start = perf_counter()
                result = intersect_surface(points, faces, **kwargs, cancel=lambda: None)
                timings[name].append(perf_counter() - start)
            assert result.reason is None
            for key, array in expected.items():
                np.testing.assert_array_equal(getattr(result, key), array)
    return dict(
        input=path.name,
        points=len(points),
        faces=len(faces),
        timings=timings,
        exact=True,
    )


def compare_edge_storage(path):
    """原始两列边键与无损 uint64 键的排序顺序逐项一致。"""
    with np.load(path, allow_pickle=False) as data:
        faces = data["faces"]
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    keys = np.sort(edges, axis=1)
    assert keys.min() >= 0 and keys.max() < 2**32
    timings = {"lexsort": [], "packed": []}
    for order in (tuple(timings), tuple(reversed(timings)), tuple(timings)):
        results = {}
        for name in order:
            start = perf_counter()
            if name == "lexsort":
                indices = np.lexsort((keys[:, 1], keys[:, 0]))
                sorted_keys = keys[indices]
                starts = np.flatnonzero(
                    np.r_[True, np.any(sorted_keys[1:] != sorted_keys[:-1], axis=1)]
                )
            else:
                packed = keys[:, 0].astype(np.uint64)
                packed <<= 32
                packed |= keys[:, 1].astype(np.uint64)
                indices = np.argsort(packed, kind="stable")
                sorted_keys = packed[indices]
                starts = np.flatnonzero(
                    np.r_[True, sorted_keys[1:] != sorted_keys[:-1]]
                )
            counts = np.diff(np.r_[starts, len(edges)])
            results[name] = indices, starts, counts
            timings[name].append(perf_counter() - start)
        for before, after in zip(results["lexsort"], results["packed"]):
            np.testing.assert_array_equal(before, after)
    return dict(input=path.name, faces=len(faces), timings=timings, exact=True)


def main():
    """只输出有界统计；局部点数组仍为本轮临时产物。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--sections-only", action="store_true")
    parser.add_argument("--edge-storage", action="store_true")
    args = parser.parse_args()
    if args.edge_storage:
        paths = sorted(args.directory.glob("surface-*.npz"))
        assert len(paths) == 2
        records = [compare_edge_storage(path) for path in paths]
    elif args.sections_only:
        paths = sorted(args.directory.glob("section-*.npz"))
        assert len(paths) == 2
        records = [compare_section(path) for path in paths]
    else:
        paths = sorted(args.directory.glob("metric-*.npz"))
        assert len(paths) == 12
        records = [compare_metric(path) for path in paths]
    args.report.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
