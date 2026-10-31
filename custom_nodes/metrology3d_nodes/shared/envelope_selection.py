"""复用 SciPy 精确邻域及连通分量确定目标归属，不插入新的实测点。"""

import numpy as np
from scipy.sparse import coo_array
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from backend.service.application.errors import InvalidRequestError


def metric_membership(uvh, settings, *, max_working_bytes, cancel, capture=None):
    """全量局部支持先分区；边数先计费后构图，密集点拒绝而非截断邻居。"""
    cancel()
    selected = np.zeros(len(uvh), dtype=bool)
    positive = (
        uvh[:, 2] > 0 if settings.profiles.foreground == "above" else uvh[:, 2] < 0
    )
    rows = np.flatnonzero(positive)
    count = len(rows)
    if count == 0:
        return "target_not_found", selected, None, 0
    if count * 192 > max_working_bytes:
        raise InvalidRequestError("实际距离分区空间索引超过工作预算")
    points = np.ascontiguousarray(uvh[rows, :2])
    tree = cKDTree(points, copy_data=False)
    cancel()
    radius = settings.selection.connection_distance
    pairs_count = (int(tree.count_neighbors(tree, radius)) - count) // 2
    if count * 192 + pairs_count * 96 > max_working_bytes:
        raise InvalidRequestError("实际距离分区完整邻域图超过工作预算")
    cancel()
    pairs = tree.query_pairs(radius, eps=0, output_type="ndarray")
    if len(pairs) != pairs_count:
        raise RuntimeError("空间索引邻域计数与完整边集不一致")
    cancel()
    graph = coo_array(
        (np.ones(len(pairs), dtype=np.uint8), (pairs[:, 0], pairs[:, 1])),
        shape=(count, count),
    ).tocsr()
    component_count, labels = connected_components(graph, directed=False)
    cancel()
    seed = np.all(
        (points >= settings.selection.seed_min)
        & (points <= settings.selection.seed_max),
        axis=1,
    )
    targets = np.unique(labels[seed])
    if capture is not None:
        capture.put("metric_uv", points, dtype="float64")
        capture.put("metric_rows", rows, dtype="uint64")
        capture.put("metric_labels", labels, dtype="int64")
        capture.put("metric_seed", seed, dtype="uint8")
    if len(targets) != 1:
        return (
            "target_not_found" if not len(targets) else "target_ambiguous",
            selected,
            None,
            int(component_count),
        )
    selected[rows] = labels == targets[0]
    return None, selected, (rows, labels, int(targets[0])), int(component_count)
