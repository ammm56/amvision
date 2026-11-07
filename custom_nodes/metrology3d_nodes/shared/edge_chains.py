"""格对来源约束下组织实测边；复用现有一维拓扑，不跨诊断缺口补线。"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from itertools import product
from typing import TYPE_CHECKING

import numpy as np

from backend.contracts.workflows.edge3d import (
    EdgeChainSettings,
    HeightJumpPairingSettings,
)
from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.boundary_topology import order_segments
from custom_nodes.metrology3d_nodes.shared.edge_pairing import PairStatus
from custom_nodes.metrology3d_nodes.shared.edge_pair_runtime import HeightJumpPairs
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)

if TYPE_CHECKING:
    from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import (
        NormalEdgePairs,
    )


@dataclass(frozen=True)
class EdgeChains:
    """内部候选链和来源；选择稳定目标及质量校验后才可成为 BoundaryFeature。"""

    pairs: HeightJumpPairs | "NormalEdgePairs"
    settings_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    reason: str | None

    @contextmanager
    def borrow(self, runtime):
        """不让父配对释放后的链继续提供旧几何。"""
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("实测边链资源已释放")
        with self.pairs.borrow(runtime), self.owner.borrow() as arrays:
            yield arrays


def _quads(first, second, width, height):
    """格中心作为顶点；只允许同一个有界四格单元内的候选相接。"""
    r1, c1 = divmod(int(first), width)
    r2, c2 = divmod(int(second), width)
    for row in (r1 - 1, r1):
        for column in (c1 - 1, c1):
            if (
                0 <= row < height - 1
                and 0 <= column < width - 1
                and row <= r2 <= row + 1
                and column <= c2 <= column + 1
            ):
                yield row, column


CHAIN_ISSUES = (
    None,
    "pairing_ambiguous",
    "edge_order_ambiguous",
    "edge_link_ambiguous",
)


def _build(
    data, candidates, parameters, counts, settings, tolerance, *, cancel, issues=None
):
    """纯拓扑内核；调用方按全部记录而非成功点数为字典和排序预算。"""
    offsets = data["offsets"][:, 0]
    width, height = parameters.width, parameters.height
    spacing = np.array([parameters.grid.column_step, parameters.grid.row_step])
    groups, vertices, paired_rows, used = [], [], [], {}
    reason = None
    for index, (start, stop) in enumerate(zip(offsets[:-1], offsets[1:])):
        cancel()
        start, stop = int(start), int(stop)
        members = []
        for row in range(start, stop):
            if (row - start) % 1024 == 0:
                cancel()
            if (
                data["status"][row, 0] != PairStatus.PAIRED
                or data["sides"][row, 0] != 0
            ):
                continue
            other = int(data["partners"][row, 0])
            a_is_low = data["metrics"][row, 2] > 0
            selected, opposite = (
                (other, row) if (settings.side == "high") == a_is_low else (row, other)
            )
            logical = int(data["input_rows"][selected, 0])
            other_logical = int(data["input_rows"][opposite, 0])
            if logical in used:
                vertex, old_other = used[logical]
                if old_other != other_logical:
                    reason = "pairing_ambiguous"
                    if issues is not None:
                        issues.add((vertex, 1))
            else:
                vertex = len(vertices)
                used[logical] = vertex, other_logical
                vertices.append(selected)
                paired_rows.append(opposite)
            members.append(vertex)
        groups.append(np.asarray(sorted(set(members)), dtype=np.int64))
    rows = np.asarray(vertices, dtype=np.int64)
    opposite = np.asarray(paired_rows, dtype=np.int64)
    points = data["positions"][rows]
    edges = set()
    endpoints, quads = {}, {}
    blocked_states = (
        PairStatus.UNASSIGNED,
        PairStatus.SURFACE_AMBIGUOUS,
        PairStatus.NEAREST_AMBIGUOUS,
        PairStatus.GAP_EXCEEDED,
        PairStatus.PARTNER_AMBIGUOUS,
        PairStatus.NOT_HEIGHT_JUMP,
    )
    for index, group in enumerate(groups):
        cancel()
        first, second = candidates["cells"][index]
        for quad in _quads(first, second, width, height):
            # 格单元约束连接范围；对角候选不能阻断另一条已证实的正交边。
            quads.setdefault(quad, []).append(index)
        if not len(group):
            continue
        a, b = (
            np.array(divmod(int(first), width))[::-1],
            np.array(divmod(int(second), width))[::-1],
        )
        direction = (b - a) * spacing
        tangent = np.array([-direction[1], direction[0]], dtype=float)
        tangent /= np.linalg.norm(tangent)
        along = points[group, :2] @ tangent
        order = np.argsort(along, kind="stable")
        group, along = group[order], along[order]
        if np.any(np.diff(along) <= tolerance):
            reason = reason or "edge_order_ambiguous"
            if issues is not None:
                for i in np.flatnonzero(np.diff(along) <= tolerance):
                    issues.add((int(group[i]), 2))
                    issues.add((int(group[i + 1]), 2))
            continue
        start, stop = int(offsets[index]), int(offsets[index + 1])
        invalid = np.isin(data["status"][start:stop, 0], blocked_states)
        blocked = np.sort(data["positions"][start:stop][invalid, :2] @ tangent)
        for n in range(len(group) - 1):
            cancel()
            # 未解释/歧义记录处不能直接连通两端成功点。
            left = np.searchsorted(blocked, along[n] + tolerance, side="right")
            right = np.searchsorted(blocked, along[n + 1] - tolerance, side="left")
            x, y = int(group[n]), int(group[n + 1])
            if (
                right > left
                or np.linalg.norm(points[y] - points[x]) > settings.max_link_distance
            ):
                continue
            edges.add(tuple(sorted((x, y))))
        eligible = []
        if not len(blocked) or blocked[0] >= along[0] - tolerance:
            eligible.append(int(group[0]))
        if not len(blocked) or blocked[-1] <= along[-1] + tolerance:
            eligible.append(int(group[-1]))
        if eligible:
            endpoints[index] = tuple(set(eligible))
    for (row, column), indices in quads.items():
        cancel()
        cells = np.array(
            [
                row * width + column,
                row * width + column + 1,
                (row + 1) * width + column,
                (row + 1) * width + column + 1,
            ]
        )
        if np.any(counts[cells] == 0):
            continue
        active = [index for index in indices if index in endpoints]
        if len(active) > 2:
            connected = set(groups[active[0]].tolist())
            pending = list(active[1:])
            while pending:
                joined = [i for i in pending if connected.intersection(groups[i])]
                if not joined:
                    break
                for i in joined:
                    connected.update(groups[i].tolist())
                    pending.remove(i)
            if pending:
                reason = reason or "edge_link_ambiguous"
                if issues is not None:
                    issues.update((int(v), 3) for i in active for v in endpoints[i])
            # 已共享实测顶点的重复观察无需补边；真正分支由现有拓扑核验。
            continue
        if len(active) != 2:
            continue
        if np.intersect1d(groups[active[0]], groups[active[1]]).size:
            continue
        choices = sorted(
            set(
                tuple(sorted((a, b)))
                for a, b in product(endpoints[active[0]], endpoints[active[1]])
                if a != b
            )
        )
        if not choices:
            continue
        distance = np.array([np.linalg.norm(points[a] - points[b]) for a, b in choices])
        best = float(distance.min())
        if best > settings.max_link_distance:
            continue
        nearest = np.flatnonzero(distance - best <= tolerance)
        if len(nearest) != 1:
            reason = reason or "edge_link_ambiguous"
            if issues is not None:
                issues.update((int(v), 3) for i in nearest for v in choices[int(i)])
            continue
        edges.add(choices[int(nearest[0])])
    edges = np.asarray(sorted(edges), dtype=np.int64).reshape(-1, 2)
    return rows, opposite, points, edges, reason


def build_edge_chains(runtime, pairs, settings, *, cancel):
    """所有边均具格邻接和距离依据，分支不任取一条，孤立点保留诊断。"""
    settings = EdgeChainSettings.model_validate(settings.model_dump())
    ref = HeightMapReference.model_validate_json(pairs.candidates.height_map_json)
    pairing = HeightJumpPairingSettings.model_validate_json(pairs.settings_json)
    keys = []
    try:
        with (
            runtime.producing(),
            pairs.borrow(runtime) as data,
            pairs.candidates.borrow(runtime) as candidates,
            resolve_height_map(runtime, ref).borrow(runtime) as grid,
        ):
            cancel()
            held = sum(
                a.nbytes for a in (*data.values(), *candidates.values(), *grid.values())
            )
            planned = len(data["status"]) * 4096 + len(candidates["cells"]) * 2048
            if held + planned + 1024 > runtime.policy.max_working_bytes:
                raise InvalidRequestError("实测边完整排序和拓扑超过工作预算")
            issues = set()
            rows, opposite, points, edges, reason = _build(
                data,
                candidates,
                ref.evidence.parameters,
                grid["counts"][:, 0],
                settings,
                pairing.tie_tolerance,
                cancel=cancel,
                issues=issues,
            )
            return finish_edge_chains(
                runtime,
                pairs,
                settings,
                data,
                rows,
                opposite,
                points,
                edges,
                issues,
                reason,
                held,
                keys,
                cancel=cancel,
            )
    except BaseException as error:
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise


def finish_edge_chains(
    runtime,
    pairs,
    settings,
    data,
    rows,
    opposite,
    points,
    edges,
    issues,
    reason,
    held,
    keys,
    *,
    cancel,
):
    """高度与法向实测链共用拓扑、转角、只读输出和资源登记。"""
    output = None
    try:
        topology_reason, segments = order_segments(
            points,
            edges,
            max_working_bytes=runtime.policy.max_working_bytes - held,
            cancel=cancel,
        )
        reason = reason or topology_reason
        # 复用已有度数/闭环检查；转角超限拒绝而不是隐藏简化弯折。
        if reason is None:
            for segment in segments:
                actual = points[segment.indices]
                triples = (
                    np.vstack((actual[-1:], actual, actual[:1]))
                    if segment.closed
                    else actual
                )
                for index in range(1, len(triples) - 1):
                    cancel()
                    before = triples[index] - triples[index - 1]
                    after = triples[index + 1] - triples[index]
                    angle = np.arccos(
                        np.clip(
                            before
                            @ after
                            / (np.linalg.norm(before) * np.linalg.norm(after)),
                            -1,
                            1,
                        )
                    )
                    if angle > settings.max_turn_angle:
                        reason = "edge_turn_exceeded"
        # 无效时仍保留实测点和边证据，但不发布可消费段。
        if reason:
            segments = ()
        ordered = (
            np.concatenate([s.indices for s in segments])
            if segments
            else np.empty(0, dtype=np.int64)
        )
        offsets = np.zeros((len(segments) + 1, 1), dtype="<u8")
        offsets[1:, 0] = np.cumsum([len(s.indices) for s in segments])
        output = dict(
            pair_rows=rows.reshape(-1, 1),
            other_rows=opposite.reshape(-1, 1),
            input_rows=data["input_rows"][rows].copy(),
            source_rows=data["source_rows"][rows].copy(),
            positions=points,
            edges=edges,
            issues=np.asarray(sorted(issues), dtype="<u8").reshape(-1, 2),
            segment_rows=ordered.reshape(-1, 1),
            segment_offsets=offsets,
            closed=np.asarray([s.closed for s in segments], dtype="u1").reshape(-1, 1),
            isolated=np.flatnonzero(~np.isin(np.arange(len(points)), edges))
            .astype("<u8")
            .reshape(-1, 1),
        )
        cancel()
        owner = own_output(runtime, output, keys)
        output = None
        cancel()
        return EdgeChains(pairs, settings.model_dump_json(), owner, keys[0], reason)
    except BaseException as error:
        output = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
