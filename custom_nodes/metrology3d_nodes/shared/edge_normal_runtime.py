"""法向边实测配对与同窗口连接；完整诊断按原输入行汇总，不复制重叠窗口。"""

from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

from backend.contracts.workflows.edge3d import NormalCreaseSettings, NormalEdgeSettings
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.edge_normal_candidates import (
    NormalCreaseCandidates,
    NormalNeighborhoodStatus,
)
from custom_nodes.metrology3d_nodes.shared.edge_pairing import (
    PairStatus,
    pair_normal_points,
)


@dataclass(frozen=True)
class NormalEdgePairs:
    """候选父对象保留逐窗口模型，当前 owner 保留逐点完整状态和实测连接。"""

    candidates: NormalCreaseCandidates
    settings_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    pair_count: int

    @contextmanager
    def borrow(self, runtime):
        """父候选或原始云失效后不能继续使用。"""
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("法向实测配对资源已释放")
        with self.candidates.borrow(runtime), self.owner.borrow() as arrays:
            yield arrays


def _window_edges(points, ids, sides, state, settings, normals, *, cancel):
    """交线方向仅用于排序，顶点始终是原始实测位置；失败位置阻断连接。"""
    side = 0 if settings.side == "a" else 1
    rows = np.flatnonzero((sides == side) & (state == PairStatus.PAIRED))
    if len(rows) < 2:
        return (), ()
    tangent = np.cross(normals[0], normals[1])
    size = np.linalg.norm(tangent)
    if not np.isfinite(size) or size == 0:
        raise InvalidRequestError("已通过的折边模型缺少合法折角方向")
    tangent /= size
    tangent *= 1 if tangent[np.argmax(np.abs(tangent))] >= 0 else -1
    along = (points - points[0]) @ tangent
    rows = rows[np.argsort(along[rows], kind="stable")]
    tied = np.flatnonzero(np.diff(along[rows]) <= settings.tie_tolerance)
    if len(tied):
        return (), tuple(int(ids[v]) for i in tied for v in rows[i : i + 2])
    blocked = np.sort(
        along[~np.isin(state, (PairStatus.PAIRED, PairStatus.NOT_MUTUAL))]
    )
    edges = []
    for first, second in zip(rows[:-1], rows[1:]):
        cancel()
        left = np.searchsorted(
            blocked, along[first] + settings.tie_tolerance, side="right"
        )
        right = np.searchsorted(
            blocked, along[second] - settings.tie_tolerance, side="left"
        )
        if (
            right > left
            or np.linalg.norm(points[first] - points[second])
            > settings.max_link_distance
        ):
            continue
        edges.append(tuple(sorted((int(ids[first]), int(ids[second])))))
    return edges, ()


def pair_normal_candidates(runtime, candidates, settings, *, cancel):
    """所有窗口参加裁决；一个源点的成功不能覆盖另一窗口的歧义或失败。"""
    settings = NormalEdgeSettings.model_validate(settings.model_dump())
    support = NormalCreaseSettings.model_validate_json(candidates.settings_json)
    cloud = CloudReference.model_validate_json(candidates.cloud_json)
    if settings.tie_tolerance >= support.max_pair_distance:
        raise InvalidRequestError("法向等距容差必须小于实测配对间距")
    keys, output, block, tree = [], None, None, None
    try:
        with (
            runtime.producing(),
            candidates.borrow(runtime) as evidence,
            runtime.borrow(cloud) as view,
        ):
            count = cloud.point_count
            held = sum(v.nbytes for v in evidence.values()) + count * 1024
            available = runtime.policy.max_working_bytes - held
            width = sum(np.dtype(f.dtype).itemsize * f.components for f in cloud.fields)
            chunk = min(runtime.policy.chunk_rows, available // (2 * width + 512))
            if chunk < 1:
                raise InvalidRequestError("法向完整配对和索引超过工作预算")
            output = dict(
                positions=np.empty((count, 3), dtype="<f8"),
                input_rows=np.arange(count, dtype="<u8").reshape(-1, 1),
                source_rows=evidence["source_rows"].copy(),
                sides=np.full((count, 1), 2, dtype="u1"),
                status=np.full((count, 1), PairStatus.NOT_MUTUAL, dtype="u1"),
                partners=np.full((count, 1), -1, dtype="<i8"),
                metrics=np.full((count, 3), np.nan, dtype="<f8"),
                reason_bits=np.zeros((count, 1), dtype="<u2"),
                observation_counts=np.zeros((count, 1), dtype="<u8"),
                first_pair_candidate=np.full((count, 1), -1, dtype="<i8"),
            )
            for start in range(0, count, chunk):
                cancel()
                stop = min(count, start + chunk)
                block = view.chunk(start, stop)
                output["positions"][start:stop] = block["positions"]
            block = None
            points = output["positions"]
            cancel()
            tree = cKDTree(points, copy_data=True)
            cancel()
            bits = output["reason_bits"][:, 0]
            state = evidence["status"][:, 0]
            bits[state == NormalNeighborhoodStatus.INVALID_NORMAL] |= (
                1 << PairStatus.NORMAL_INVALID
            )
            bits[
                np.isin(
                    state,
                    (
                        NormalNeighborhoodStatus.SATURATED,
                        NormalNeighborhoodStatus.INSUFFICIENT,
                        NormalNeighborhoodStatus.INVALID_NEIGHBOR_NORMAL,
                    ),
                )
            ] |= 1 << PairStatus.NEIGHBORHOOD_INCOMPLETE
            edges = set()
            for index, (first, second) in enumerate(evidence["pairs"]):
                cancel()
                center = points[first] / 2 + points[second] / 2
                failed = bool(evidence["reason"][index, 0])
                # 两跳覆盖对点的反向最近邻及等距壳层；只在原支持窗内组织边。
                radius = (
                    support.support.radius
                    if failed
                    else support.support.radius
                    + 2 * (support.max_pair_distance + settings.tie_tolerance)
                )
                if not np.isfinite(radius):
                    raise InvalidRequestError("法向完整配对搜索范围超出有限数值")
                size = int(
                    tree.query_ball_point(
                        center,
                        radius,
                        eps=0,
                        workers=1,
                        return_length=True,
                    )
                )
                if size * 1024 + len(edges) * 256 > available:
                    raise InvalidRequestError("法向完整窗口和实测连接超过工作预算")
                ids = np.asarray(
                    tree.query_ball_point(center, radius, eps=0, workers=1),
                    dtype=np.int64,
                )
                if failed:
                    output["observation_counts"][ids, 0] += 1
                    bits[ids] |= 1 << PairStatus.SUPPORT_INVALID
                    continue
                local = points[ids]
                core = np.linalg.norm(local - center, axis=1) <= support.support.radius
                normals = evidence["model_normals"][index].reshape(2, 3)
                sides, status, partner, metrics = pair_normal_points(
                    local,
                    evidence["model_origins"][index].reshape(2, 3),
                    normals,
                    support,
                    settings,
                    chunk_rows=chunk,
                    cancel=cancel,
                )
                observed = core.copy()
                observed[partner[core & (partner >= 0)]] = True
                output["observation_counts"][ids[observed], 0] += 1
                bits[ids[observed]] |= np.left_shift(
                    np.uint16(1), status[observed].astype(np.uint16)
                )
                for row in np.flatnonzero(observed & (partner >= 0)):
                    cancel()
                    logical, other = int(ids[row]), int(ids[partner[row]])
                    previous = int(output["partners"][logical, 0])
                    if previous >= 0 and (
                        previous != other or output["sides"][logical, 0] != sides[row]
                    ):
                        bits[logical] |= 1 << PairStatus.PAIRING_CONFLICT
                    elif previous < 0:
                        output["partners"][logical, 0] = other
                        output["sides"][logical, 0] = sides[row]
                        output["metrics"][logical] = metrics[row]
                        output["first_pair_candidate"][logical, 0] = index
                local_edges, issues = _window_edges(
                    local[core],
                    ids[core],
                    sides[core],
                    status[core],
                    settings,
                    normals,
                    cancel=cancel,
                )
                for row in issues:
                    bits[row] |= 1 << PairStatus.EDGE_ORDER_AMBIGUOUS
                for edge in local_edges:
                    cancel()
                    edges.add(edge)
                    if size * 1024 + len(edges) * 256 > available:
                        raise InvalidRequestError("法向实测连接超过工作预算")
            tree = None
            # 保留全部原因位；整体状态采用明确失败优先，不允许后来成功覆盖失败。
            status = output["status"][:, 0]
            status[(bits & (1 << PairStatus.PAIRED)) != 0] = PairStatus.PAIRED
            inconsistent = ((bits & (1 << PairStatus.PAIRED)) != 0) & (
                (bits & (1 << PairStatus.NOT_MUTUAL)) != 0
            )
            bits[inconsistent] |= 1 << PairStatus.PAIRING_CONFLICT
            for reason in reversed(tuple(PairStatus)):
                if reason not in (PairStatus.PAIRED, PairStatus.NOT_MUTUAL):
                    status[(bits & (1 << reason)) != 0] = reason
            partner = output["partners"][:, 0]
            for row in np.flatnonzero(status == PairStatus.PAIRED):
                cancel()
                other = int(partner[row])
                if (
                    other < 0
                    or partner[other] != row
                    or status[other] != PairStatus.PAIRED
                ):
                    bits[row] |= 1 << PairStatus.PAIRING_CONFLICT
                    status[row] = PairStatus.PAIRING_CONFLICT
            accepted = status == PairStatus.PAIRED
            partner[~accepted] = -1
            output["metrics"][~accepted] = np.nan
            output["edges"] = np.asarray(sorted(edges), dtype="<u8").reshape(-1, 2)
            cancel()
            owner = own_output(runtime, output, keys)
            total = int(accepted.sum()) // 2
            output = None
            cancel()
            return NormalEdgePairs(
                candidates, settings.model_dump_json(), owner, keys[0], total
            )
    except BaseException as error:
        output = block = tree = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise


def build_normal_edge_chains(runtime, pairs, *, cancel):
    """仅消费同窗口实测连接；窗口之间不另做最近邻补线。"""
    from custom_nodes.metrology3d_nodes.shared.edge_chains import finish_edge_chains

    settings = NormalEdgeSettings.model_validate_json(pairs.settings_json)
    keys = []
    with (
        runtime.producing(),
        pairs.borrow(runtime) as data,
        pairs.candidates.borrow(runtime) as evidence,
    ):
        cancel()
        held = sum(a.nbytes for a in (*data.values(), *evidence.values()))
        if (
            held + len(data["status"]) * 1024 + len(data["edges"]) * 2048 + 1024
            > runtime.policy.max_working_bytes
        ):
            raise InvalidRequestError("法向实测边完整拓扑超过工作预算")
        side = 0 if settings.side == "a" else 1
        selected = (data["status"][:, 0] == PairStatus.PAIRED) & (
            data["sides"][:, 0] == side
        )
        rows = np.flatnonzero(selected)
        reverse = np.full(len(selected), -1, dtype=np.int64)
        reverse[rows] = np.arange(len(rows))
        edges = data["edges"]
        edges = reverse[edges[selected[edges].all(axis=1)]]
        return finish_edge_chains(
            runtime,
            pairs,
            settings,
            data,
            rows,
            data["partners"][rows, 0].copy(),
            data["positions"][rows].copy(),
            edges,
            set(),
            None,
            held,
            keys,
            cancel=cancel,
        )
