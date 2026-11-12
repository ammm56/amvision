"""完整诊断进入既有目标选择和质量比较；不从失败候选中只挑成功点。"""

from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np

from backend.contracts.workflows.boundary3d_selection import BoundaryFragmentTarget
from backend.contracts.workflows.edge3d import EdgeChainSettings, NormalEdgeSettings
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.edge3d_selection import (
    EdgeTargetReport,
    EdgeTargetSelection,
)
from backend.contracts.workflows.evaluation3d import EvaluationPlane3d
from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.boundary_targets import (
    select_boundary_targets,
    target_mask,
)
from custom_nodes.metrology3d_nodes.shared.boundary_topology import (
    OrderedSegment,
    order_segments,
)
from custom_nodes.metrology3d_nodes.shared.edge_chains import CHAIN_ISSUES, EdgeChains
from custom_nodes.metrology3d_nodes.shared.edge_pairing import PairStatus
from custom_nodes.metrology3d_nodes.shared.edge_normal_runtime import NormalEdgePairs
from custom_nodes.metrology3d_nodes.shared.geometry_quality import geometry_quality
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)


@dataclass(frozen=True)
class EdgeTargetResults:
    """目标结果仍依赖同次链与原云；报告快照不持有可变 Pydantic 对象。"""

    chains: EdgeChains
    settings_json: str
    evaluation_json: str
    reports_json: tuple[str, ...]
    owner: OwnedCloudArrays
    resource_key: tuple
    extraction_json: str | None = None

    @property
    def reason(self):
        """任一必选目标失败，整体不得消费部分成功结果。"""
        return next(
            (
                r.reason
                for raw in self.reports_json
                if (r := EdgeTargetReport.model_validate_json(raw)).reason
            ),
            None,
        )

    @contextmanager
    def borrow(self, runtime):
        """源链/源云释放后结果不可重用。"""
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("实测边目标资源已释放")
        with self.chains.borrow(runtime), self.owner.borrow() as arrays:
            yield arrays


def height_evaluation(ref):
    """将本次网格评价轴映回源空间；目标 ROI 始终使用源云真实坐标。"""
    return height_evaluation_from_evidence(ref.evidence, ref.cloud)


def height_evaluation_from_evidence(evidence, cloud):
    """运行和持久证据共用评价面计算，不构造历史运行引用。"""
    grid = evidence.parameters.grid
    axes = np.asarray(
        [grid.column_direction, grid.row_direction, grid.height_direction]
    ).T
    origin = np.asarray(grid.origin)
    if evidence.pose:
        matrix = np.asarray(evidence.pose.transform.matrix)
        origin = matrix[:3, :3].T @ (origin - matrix[:3, 3])
        axes = matrix[:3, :3].T @ axes
    return EvaluationPlane3d(
        frame_id=cloud.spatial.frame_id,
        length_unit=cloud.spatial.length_unit,
        origin=origin.tolist(),
        rotation=axes.tolist(),
    )


def _quality(
    points,
    row_ids,
    topology,
    pair_data,
    chain_data,
    policy,
    observation,
    unit,
    *,
    planar,
):
    """仅统计真正选中支持与真实段长度；片段之间的缺口不计入长度。"""
    length = 0.0
    for part in topology.segments:
        actual = points[row_ids[part.start : part.start + part.count]].astype(
            np.float64
        )
        length += float(np.linalg.norm(np.diff(actual, axis=0), axis=1).sum())
        if part.closed:
            length += float(np.linalg.norm(actual[-1] - actual[0]))
    metrics = pair_data["metrics"][chain_data["pair_rows"][row_ids, 0]]
    values = dict(
        support_count=(len(row_ids), "1"),
        length=(length, unit),
        max_pair_distance=(float(metrics[:, 1].max()), unit),
    )
    if planar:
        values["max_planar_gap"] = (float(metrics[:, 0].max()), unit)
    if any(
        r.item_id not in values or r.unit != values[r.item_id][1] for r in policy.rules
    ):
        raise InvalidRequestError("实测边质量包含未知指标或错误单位")
    return geometry_quality(observation, values, policy, reason="metric_unavailable")


def _target(
    points,
    records,
    data,
    pairs,
    target,
    parameters,
    evaluation,
    chain_settings,
    *,
    budget,
    cancel,
):
    """先按同一目标检查全部诊断，再复用拓扑和选择；孤立点不能被丢弃。"""
    mask = target_mask(
        points, target, evaluation, max_working_bytes=budget, cancel=cancel
    )
    record_mask = target_mask(
        records, target, evaluation, max_working_bytes=budget, cancel=cancel
    )
    codes, counts = np.unique(pairs["status"][record_mask, 0], return_counts=True)
    summary = {PairStatus(int(c)).name: int(n) for c, n in zip(codes, counts)}
    bad = [int(c) for c in codes if c not in (PairStatus.PAIRED, PairStatus.NOT_MUTUAL)]
    if bad:
        return "pair_" + PairStatus(bad[0]).name.lower(), summary, None, None
    for vertex, code in data["issues"]:
        cancel()
        if mask[int(vertex)]:
            return CHAIN_ISSUES[int(code)], summary, None, None
    selected = np.flatnonzero(mask)
    if not len(selected):
        return "target_not_found", summary, None, None
    edges = data["edges"]
    edges = edges[mask[edges].all(axis=1)]
    reverse = np.full(len(points), -1, dtype=np.int64)
    reverse[selected] = np.arange(len(selected))
    reason, segments = order_segments(
        points[selected], reverse[edges], max_working_bytes=budget, cancel=cancel
    )
    if reason not in (None, "no_boundary"):
        return reason, summary, None, None
    candidates = [OrderedSegment(selected[s.indices], s.closed) for s in segments]
    candidates.extend(
        OrderedSegment(np.array([i]), False)
        for i in selected[~np.isin(selected, edges)]
    )
    reason, _, rows, topology = select_boundary_targets(
        points,
        candidates,
        targets=(target,),
        evaluation=evaluation,
        min_projected_area=parameters.min_projected_area,
        max_working_bytes=budget,
        cancel=cancel,
    )
    if reason is not None:
        return reason, summary, None, None
    for part in topology.segments:
        actual = points[rows[part.start : part.start + part.count]].astype(float)
        extended = (
            np.vstack((actual[-1:], actual, actual[:1])) if part.closed else actual
        )
        for i in range(1, len(extended) - 1):
            cancel()
            a, b = extended[i] - extended[i - 1], extended[i + 1] - extended[i]
            angle = np.arccos(
                np.clip(a @ b / (np.linalg.norm(a) * np.linalg.norm(b)), -1, 1)
            )
            if angle > chain_settings.max_turn_angle:
                return "edge_turn_exceeded", summary, None, None
    return None, summary, rows, topology


def select_edge_targets(runtime, chains, parameters, *, cancel, evaluation=None):
    """目标按配方身份依次核对；整体失败仍保留逐目标报告供显示。"""
    parameters = EdgeTargetSelection.model_validate(parameters.model_dump())
    normal = isinstance(chains.pairs, NormalEdgePairs)
    if normal:
        cloud = CloudReference.model_validate_json(chains.pairs.candidates.cloud_json)
        if evaluation is None:
            raise InvalidRequestError("法向边目标必须显式提供评价面")
        evaluation = EvaluationPlane3d.model_validate(evaluation.model_dump())
        chain_settings = NormalEdgeSettings.model_validate_json(chains.settings_json)
        if (evaluation.frame_id, evaluation.length_unit) != (
            cloud.spatial.frame_id,
            cloud.spatial.length_unit,
        ):
            raise InvalidRequestError("法向评价面与源云空间不一致")
    else:
        ref = HeightMapReference.model_validate_json(
            chains.pairs.candidates.height_map_json
        )
        if evaluation is not None:
            raise InvalidRequestError("高度边评价面由高度图提供，不允许覆盖")
        cloud = ref.cloud
        evaluation = height_evaluation(ref)
        chain_settings = EdgeChainSettings.model_validate_json(chains.settings_json)
    for target in parameters.targets:
        if any(
            (r.frame_id, r.length_unit) != (evaluation.frame_id, evaluation.length_unit)
            for r in target.region.rois
        ):
            raise InvalidRequestError("实测边目标 ROI 与源云空间不一致")
    units = dict(
        support_count="1",
        length=evaluation.length_unit,
        max_pair_distance=evaluation.length_unit,
    )
    if not normal:
        units["max_planar_gap"] = evaluation.length_unit
    policies = [
        parameters.quality_policy,
        *(
            t.fragment_quality_policy
            for t in parameters.targets
            if isinstance(t, BoundaryFragmentTarget)
        ),
    ]
    if any(
        r.item_id not in units or r.unit != units[r.item_id]
        for p in policies
        for r in p.rules
    ):
        raise InvalidRequestError("实测边质量包含未知指标或错误单位")
    output, keys = None, []
    try:
        with (
            runtime.producing(),
            chains.borrow(runtime) as data,
            chains.pairs.borrow(runtime) as pairs,
            runtime.borrow(cloud) as view,
        ):
            with chains.pairs.candidates.borrow(runtime) as candidates:
                held = sum(
                    v.nbytes
                    for v in (*data.values(), *pairs.values(), *candidates.values())
                )
            if not normal:
                with resolve_height_map(runtime, ref).borrow(runtime) as grid:
                    held += sum(v.nbytes for v in grid.values())
            width = sum(np.dtype(f.dtype).itemsize * f.components for f in cloud.fields)
            planned = (
                len(pairs["status"]) * 128
                + len(data["positions"]) * 2048
                + len(parameters.targets) * 2048
            )
            available = runtime.policy.max_working_bytes - held - planned
            chunk = min(runtime.policy.chunk_rows, available // (width * 2 + 512))
            if chunk < 1:
                raise InvalidRequestError("完整实测边目标及诊断超过工作预算")
            dtype = next(f.dtype for f in cloud.fields if f.name == "positions")
            records = np.empty((len(pairs["status"]), 3), dtype=dtype)
            for start in range(0, len(records), chunk):
                cancel()
                stop = min(start + chunk, len(records))
                block, _ = view.gather(pairs["input_rows"][start:stop, 0])
                records[start:stop] = block["positions"]
            block = None
            points = records[data["pair_rows"][:, 0]]
            reports, selected, offsets, used = [], [], [0], set()
            for target in parameters.targets:
                cancel()
                reason, counts, rows, topology = _target(
                    points,
                    records,
                    data,
                    pairs,
                    target,
                    parameters,
                    evaluation,
                    chain_settings,
                    budget=available,
                    cancel=cancel,
                )
                quality, checks = None, []
                if reason is None:
                    if any(int(row) in used for row in rows):
                        reason = "target_conflict"
                    else:
                        used.update(map(int, rows))
                    quality = _quality(
                        points,
                        rows,
                        topology,
                        pairs,
                        data,
                        parameters.quality_policy,
                        cloud.observation_id,
                        evaluation.length_unit,
                        planar=not normal,
                    )
                    for segment in topology.segments:
                        part_rows = rows[segment.start : segment.start + segment.count]
                        part_topology = topology.model_copy(
                            update={
                                "point_count": segment.count,
                                "segments": (segment.model_copy(update={"start": 0}),),
                            }
                        )
                        policy = (
                            target.fragment_quality_policy
                            if isinstance(target, BoundaryFragmentTarget)
                            else parameters.quality_policy
                        )
                        checked = _quality(
                            points,
                            part_rows,
                            part_topology,
                            pairs,
                            data,
                            policy,
                            cloud.observation_id,
                            evaluation.length_unit,
                            planar=not normal,
                        )
                        checks.append(
                            dict(
                                segment_id=segment.segment_id,
                                group_id=segment.group_id,
                                quality=checked,
                            )
                        )
                        if not checked.usable:
                            reason = reason or "insufficient_quality"
                    if not quality.usable:
                        reason = reason or "insufficient_quality"
                if reason is None:
                    selected.append(rows)
                    offsets.append(offsets[-1] + len(rows))
                else:
                    offsets.append(offsets[-1])
                reports.append(
                    EdgeTargetReport(
                        target_id=target.target_id,
                        reason=reason,
                        record_counts=counts,
                        topology=topology if reason is None else None,
                        quality=quality,
                        segments=checks,
                    ).model_dump_json()
                )
            chosen = (
                np.concatenate(selected) if selected else np.empty(0, dtype=np.int64)
            )
            output = dict(
                chain_rows=chosen.reshape(-1, 1),
                offsets=np.asarray(offsets, dtype="<u8").reshape(-1, 1),
                input_rows=data["input_rows"][chosen].copy(),
                source_rows=data["source_rows"][chosen].copy(),
            )
            cancel()
            owner = own_output(runtime, output, keys)
            output = None
            cancel()
            return EdgeTargetResults(
                chains,
                parameters.model_dump_json(),
                evaluation.model_dump_json(),
                tuple(reports),
                owner,
                keys[0],
            )
    except BaseException as error:
        output = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
