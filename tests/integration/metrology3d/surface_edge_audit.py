"""同一真实三角面上的新旧排序对照；附加诊断时间不当作正式整图节拍。"""

from time import perf_counter
import numpy as np

from custom_nodes.metrology3d_nodes.shared import boundary_surface


def previous_edges(faces):
    """冻结优化前的 NumPy unique 行为，仅在测试中作全数组等价对照。"""
    edges = np.concatenate((faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]))
    _, first, counts = np.unique(
        np.sort(edges, axis=1), axis=0, return_index=True, return_counts=True
    )
    return None if np.any(counts > 2) else edges[first[counts == 1]]


def capture_edge_audit(monkeypatch, report):
    """同次建面结果上交替比较，保留既有返回值、不更换剖分或参数。"""
    current = boundary_surface._boundary_edges

    def audit(faces, *, cancel):
        timings = {"previous": [], "current": []}
        for order in (
            ("previous", "current"),
            ("current", "previous"),
            ("previous", "current"),
        ):
            results = {}
            for name in order:
                cancel()
                started = perf_counter()
                results[name] = (
                    previous_edges(faces)
                    if name == "previous"
                    else current(faces, cancel=cancel)
                )
                timings[name].append(perf_counter() - started)
            if results["previous"] is None:
                assert results["current"] is None
            else:
                np.testing.assert_array_equal(results["current"], results["previous"])
        report.append(dict(face_count=len(faces), timings=timings, exact_edges=True))
        return results["current"]

    monkeypatch.setattr(boundary_surface, "_boundary_edges", audit)
