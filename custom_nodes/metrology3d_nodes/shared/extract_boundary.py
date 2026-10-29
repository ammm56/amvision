"""有限点集的边界计算；Runtime 的索引所有权与发布由调用方负责。"""

from dataclasses import dataclass

import numpy as np

from backend.contracts.workflows.boundary3d import (
    BoundaryTopology,
    ExtractBoundaryParameters,
)
from backend.contracts.workflows.geometry3d import PlaneGeometry
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.boundary_section import intersect_surface
from custom_nodes.metrology3d_nodes.shared.boundary_surface import build_surface
from custom_nodes.metrology3d_nodes.shared.boundary_topology import (
    order_segments,
    selected_runs,
)
from custom_nodes.metrology3d_nodes.shared.roi_mask import roi_mask


@dataclass(frozen=True)
class BoundaryExtraction:
    """计算结果中的行号指父逻辑行；不能直接充当最初输入的 source_indices。"""

    reason: str | None
    positions: np.ndarray | None
    topology: BoundaryTopology | None
    source_rows: np.ndarray | None
    source_edges: np.ndarray | None
    weights: np.ndarray | None
    face_offsets: np.ndarray | None
    source_faces: np.ndarray | None
    metrics: dict[str, float | int | None]
    failed_segment_id: str | None = None


def extract_boundary_array(
    positions, parameters, *, max_working_bytes, cancel, contour_plane=None
):
    """完整明确 ROI 内求边界；参数不允许选择本次连通域序号。"""
    cancel()
    points = np.asarray(positions)
    if not isinstance(parameters, ExtractBoundaryParameters) or (
        points.ndim != 2
        or points.shape[1] != 3
        or points.dtype.kind != "f"
        or type(max_working_bytes) is not int
        or max_working_bytes <= 0
    ):
        raise InvalidRequestError("边界计算参数或输入不合法")
    if (parameters.method.kind == "contour") != isinstance(
        contour_plane, PlaneGeometry
    ):
        raise InvalidRequestError("等高方法必须且仅使用明确的基准平面")
    # 保守计入剖分、两向求交、来源字典和段数组同时存活，不等同原生 RSS 限额。
    geometry_working_bytes = len(points) * 12288
    if geometry_working_bytes > max_working_bytes:
        raise InvalidRequestError(
            f"边界完整局部支持超过显式工作预算：点数 {len(points)}，"
            f"预计 {geometry_working_bytes} B，上限 {max_working_bytes} B",
            details=dict(
                stage="extract_boundary_array",
                point_count=len(points),
                estimated_bytes=geometry_working_bytes,
                limit_bytes=max_working_bytes,
            ),
        )
    # ROI 计划可能远大于点数；不能与仍存活的几何工作集重复使用同一额度。
    roi_working_bytes = max_working_bytes - geometry_working_bytes
    if not np.isfinite(points).all():
        raise InvalidRequestError("边界输入包含无效坐标，请先执行 Filter Valid")
    metrics = dict(
        input_count=len(points),
        surface_point_count=0,
        face_count=0,
        candidate_count=0,
        support_count=None,
        length=None,
    )

    def missing(reason, segment_id=None):
        """缺测不返回半条成功边界，也不保留上一轮几何。"""
        return BoundaryExtraction(
            reason, None, None, None, None, None, None, None, metrics, segment_id
        )

    selected = np.flatnonzero(
        roi_mask(
            points,
            parameters.region,
            max_working_bytes=roi_working_bytes,
            cancel=cancel,
        )
    )
    local_points = points[selected]
    metrics["surface_point_count"] = len(selected)
    evaluation = parameters.evaluation
    surface = build_surface(
        local_points,
        origin=evaluation.origin,
        rotation=evaluation.rotation,
        **parameters.surface.model_dump(),
        max_working_bytes=max_working_bytes,
        cancel=cancel,
    )
    if surface.reason:
        return missing(surface.reason)
    metrics["face_count"] = len(surface.faces)
    section = None
    if parameters.method.kind == "projection":
        vertices, edges = local_points, surface.boundary_edges
    else:
        method = parameters.method
        if method.kind == "section":
            origin, normal = method.origin, method.normal
        else:
            normal = np.asarray(contour_plane.normal)
            alignment = float(normal @ method.positive_normal)
            if abs(alignment) < method.min_orientation_cosine:
                return missing("normal_direction_ambiguous")
            offset = contour_plane.offset
            if alignment < 0:
                normal, offset = -normal, -offset
            # 基准的法向垂足加显式高度；不猜测点云质心作为基准原点。
            origin = normal * (method.height - offset)
        section = intersect_surface(
            local_points,
            surface.faces,
            origin=origin,
            normal=normal,
            numeric_tolerance=method.numeric_tolerance,
            max_working_bytes=max_working_bytes,
            cancel=cancel,
        )
        if section.reason:
            return missing(section.reason)
        vertices, edges = section.positions, section.edges
    reason, candidates = order_segments(
        vertices, edges, max_working_bytes=max_working_bytes, cancel=cancel
    )
    if reason:
        return missing(reason)
    metrics["candidate_count"] = len(candidates)
    chosen, layouts, used, cursor, length = [], [], set(), 0, 0.0
    rotation = np.asarray(evaluation.rotation)
    for target in parameters.targets:
        cancel()
        matches = []
        for candidate in candidates:
            cancel()
            mask = roi_mask(
                vertices[candidate.indices],
                target.region,
                max_working_bytes=roi_working_bytes,
                cancel=cancel,
            )
            for part in selected_runs(candidate, mask, cancel=cancel):
                if part.closed == target.closed:
                    matches.append(part)
                    if len(matches) > 1:
                        return missing("target_ambiguous", target.segment_id)
        if not matches:
            return missing("target_not_found", target.segment_id)
        candidate = matches[0]
        if len(candidate.indices) < (3 if candidate.closed else 2):
            return missing("insufficient_support", target.segment_id)
        if any(int(index) in used for index in candidate.indices):
            return missing("target_conflict", target.segment_id)
        used.update(map(int, candidate.indices))
        actual = vertices[candidate.indices]
        orientation = "open"
        if candidate.closed:
            uv = ((actual.astype(np.float64) - actual[0]) @ rotation)[:, :2]
            area2 = float(
                np.sum(
                    uv[:, 0] * np.roll(uv[:, 1], -1) - uv[:, 1] * np.roll(uv[:, 0], -1)
                )
            )
            if abs(area2) < 2 * parameters.surface.min_projected_area:
                return missing("degenerate_boundary_projection", target.segment_id)
            orientation = "ccw" if area2 > 0 else "cw"
        length += float(
            np.linalg.norm(np.diff(actual.astype(np.float64), axis=0), axis=1).sum()
        )
        if candidate.closed:
            length += float(np.linalg.norm(actual[-1].astype(float) - actual[0]))
        chosen.append(candidate.indices)
        layouts.append(
            dict(
                segment_id=target.segment_id,
                start=cursor,
                count=len(actual),
                closed=candidate.closed,
                role=target.role,
                orientation=orientation,
            )
        )
        cursor += len(actual)
    ordered = np.concatenate(chosen)
    topology = BoundaryTopology(point_count=len(ordered), segments=layouts)
    metrics.update(support_count=len(ordered), length=length)
    if section is None:
        return BoundaryExtraction(
            None,
            vertices[ordered],
            topology,
            selected[ordered],
            None,
            None,
            None,
            None,
            metrics,
        )
    # 顶点记录全部相交源面的原始三顶点；共享边去重不丢失第二侧来源。
    incidence = {}
    for edge_id, (a, b) in enumerate(section.edges):
        cancel()
        faces = section.face_indices[
            section.face_offsets[edge_id] : section.face_offsets[edge_id + 1]
        ]
        incidence.setdefault(int(a), set()).update(map(int, faces))
        incidence.setdefault(int(b), set()).update(map(int, faces))
    offsets = np.zeros(len(ordered) + 1, dtype=np.int64)
    offsets[1:] = np.cumsum([len(incidence[int(v)]) for v in ordered])
    face_ids = np.array(
        [face for v in ordered for face in sorted(incidence[int(v)])], dtype=np.int64
    )
    cancel()
    return BoundaryExtraction(
        None,
        vertices[ordered],
        topology,
        None,
        selected[section.source_vertices[ordered]],
        section.weights[ordered],
        offsets,
        selected[surface.faces[face_ids]],
        metrics,
    )
