"""按实际顶点身份组织一维边界，不做最近邻连接或缺口补线。"""

from dataclasses import dataclass

import numpy as np

from backend.service.application.errors import InvalidRequestError


@dataclass(frozen=True)
class OrderedSegment:
    """本次候选段；候选次序不是配方中持久的 segment_id。"""

    indices: np.ndarray
    closed: bool


def selected_runs(segment, mask, *, cancel):
    """按既有连接截取实测段；环的序列起点不是缺口，不插值 ROI 交点。"""
    cancel()
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != segment.indices.shape:
        raise InvalidRequestError("边界选择掩码与顶点数量不一致")
    if mask.all():
        yield segment
        return
    # 闭环从一个排除点后遍历，避免跨数组末尾的同一段被错误拆成两段。
    indices = segment.indices
    if segment.closed:
        start = int(np.flatnonzero(~mask)[0]) + 1
        mask = np.roll(mask, -start)
        indices = np.roll(indices, -start)
    changes = np.flatnonzero(np.diff(np.r_[False, mask, False]))
    for start, stop in changes.reshape(-1, 2):
        cancel()
        # 单点也保留为候选，由上层报告少点或多段，不能静默丢弃。
        yield OrderedSegment(indices[start:stop], False)


def order_segments(positions, edges, *, max_working_bytes, cancel):
    """无向边仅允许度一/二的链或环；返回原因及全部候选，不擅自选第一个。"""
    cancel()
    points, edges = np.asarray(positions), np.asarray(edges)
    if (
        points.ndim != 2
        or points.shape[1] != 3
        or points.dtype.kind != "f"
        or edges.ndim != 2
        or edges.shape[1] != 2
        or edges.dtype.kind not in "iu"
        or type(max_working_bytes) is not int
        or max_working_bytes <= 0
    ):
        raise InvalidRequestError("边界拓扑输入不合法")
    if len(points) * 64 + len(edges) * 1024 > max_working_bytes:
        raise InvalidRequestError("边界拓扑超过显式工作预算")
    if not np.isfinite(points).all() or (
        edges.size and (edges.min() < 0 or edges.max() >= len(points))
    ):
        raise InvalidRequestError("边界顶点或边索引不合法")
    if not len(edges):
        return "no_boundary", ()
    if np.any(edges[:, 0] == edges[:, 1]) or len(
        np.unique(np.sort(edges, axis=1), axis=0)
    ) != len(edges):
        raise InvalidRequestError("边界存在自环或重复边")
    adjacency = {}
    for a, b in edges:
        cancel()
        adjacency.setdefault(int(a), []).append(int(b))
        adjacency.setdefault(int(b), []).append(int(a))
    if any(len(values) > 2 for values in adjacency.values()):
        return "branched_boundary", ()
    if any(np.array_equal(points[a], points[b]) for a, b in edges):
        return "zero_length_edge", ()
    unseen = set(adjacency)
    segments = []
    # 一次排序避免大量独立短段时反复 min(unseen) 形成平方扫描。
    for root in sorted(adjacency):
        cancel()
        if root not in unseen:
            continue
        component, pending = set(), [root]
        while pending:
            cancel()
            current = pending.pop()
            if current in component:
                continue
            component.add(current)
            pending.extend(v for v in adjacency[current] if v not in component)
        endpoints = [v for v in component if len(adjacency[v]) == 1]
        closed = not endpoints
        if len(endpoints) not in (0, 2):
            return "invalid_boundary_degree", ()
        # 几何起点只规范本次序列；业务身份由显式匹配规则赋予。
        start = min(endpoints or component, key=lambda v: (tuple(points[v]), v))
        ordered, previous, current = [], None, start
        while True:
            cancel()
            ordered.append(current)
            following = [v for v in adjacency[current] if v != previous]
            if not following:
                break
            next_vertex = min(following, key=lambda v: (tuple(points[v]), v))
            if next_vertex == start:
                break
            previous, current = current, next_vertex
            if len(ordered) > len(component):
                raise RuntimeError("边界遍历超出连通分量")
        if len(ordered) != len(component) or len(ordered) < (3 if closed else 2):
            return "invalid_boundary_chain", ()
        unseen.difference_update(component)
        segments.append(OrderedSegment(np.asarray(ordered, dtype=np.int64), closed))
    cancel()
    return None, tuple(segments)
