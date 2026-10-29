"""完整支持的投影尺寸；分块访问不改变源精度及所有权。"""

from hashlib import sha256

import numpy as np

from backend.contracts.workflows.dimension3d_evidence import (
    ContactEvidence,
    ExtentsGeometry,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    materialize_positions,
    select_boundary,
)
from custom_nodes.metrology3d_nodes.shared.dimension_runtime import (
    dimension_result,
    dimension_support,
    select_features,
)
from custom_nodes.metrology3d_nodes.shared.extents_rectangle import rectangle_axes
from custom_nodes.metrology3d_nodes.shared.fit_plane import _positions, _rows
from custom_nodes.metrology3d_nodes.shared.measurement_support import require_cloud


def _scan(runtime, cloud, origin, basis, cancel):
    """累积范围、极值代表及局部 QR；不物化整云的 float64 副本。"""
    rows = _rows(runtime, cloud)
    low, high = np.full(2, np.inf), np.full(2, -np.inf)
    counts, indices = np.zeros(4, dtype=np.int64), np.zeros(4, dtype=np.int64)
    representatives = np.zeros((4, 3))
    anchor = None
    reduced = np.empty((0, 2))
    with runtime.borrow(cloud) as view:
        for start in range(0, cloud.point_count, rows):
            cancel()
            stop = min(start + rows, cloud.point_count)
            points = _positions(view, start, stop)
            uv = (points - origin) @ basis
            if anchor is None:
                anchor = uv[0].copy()
            relative = uv - anchor
            reduced = np.linalg.qr(np.concatenate((reduced, relative)), mode="r")
            for j in range(4):
                axis, lower = j % 2, j < 2
                column = uv[:, axis]
                local = int(column.argmin() if lower else column.argmax())
                value, old = column[local], low[axis] if lower else high[axis]
                better = value < old if lower else value > old
                if better:
                    counts[j] = 0
                    indices[j], representatives[j] = start + local, points[local]
                    if lower:
                        low[axis] = value
                    else:
                        high[axis] = value
                if better or value == old:
                    counts[j] += int(np.count_nonzero(column == value))
    rank_two = cloud.point_count >= 3 and np.linalg.matrix_rank(reduced) == 2
    return np.r_[low, high], indices, representatives, counts, rank_two


def _contacts(runtime, cloud, scan, origin, normal, cancel):
    """只输出四个代表；生成顶点使用最初源边和插值摘要。"""
    _, indices, positions, counts, _ = scan
    result = []
    with runtime.borrow(cloud) as view:
        for index, point, count in zip(indices, positions, counts):
            cancel()
            index, source, lineage = int(index), None, None
            if cloud.vertex_kind == "source":
                source = int(view.source_indices(index, index + 1).reshape(-1)[0])
            else:
                block = view.lineage_chunk(index, index + 1)
                lineage = dict(
                    source_edge=tuple(int(row) for row in block["source_edges"][0]),
                    weights=block["weights"][0],
                    source_face_count=len(block["source_faces"]),
                    source_faces_sha256=sha256(
                        block["source_faces"].tobytes()
                    ).hexdigest(),
                )
            result.append(
                ContactEvidence(
                    point=point,
                    projected=point - float((point - origin) @ normal) * normal,
                    vertex_index=index,
                    source_index=source,
                    lineage=lineage,
                    tied_count=int(count),
                )
            )
    return tuple(result)


def measure_extents(runtime, parameters, *, cloud=None, groups=(), cancel):
    """保留执行异常语义，同时释放已退栈的局部数组。"""
    try:
        return _measure_extents(
            runtime, parameters, cloud=cloud, groups=groups, cancel=cancel
        )
    except BaseException as error:
        release_exception_frames(error)
        raise


def _measure_extents(runtime, parameters, *, cloud=None, groups=(), cancel):
    """显式二选一输入；失败保留 U/V 或 L/W，不猜被遮挡的工件尺寸。"""
    boundary = None
    if parameters.source.kind == "cloud":
        if cloud is None or groups:
            raise InvalidRequestError("点云长宽必须且仅连接 cloud")
        require_cloud(runtime, cloud, parameters, cloud.observation_id)
    else:
        if cloud is not None:
            raise InvalidRequestError("边界长宽不能同时连接 cloud")
        boundary = select_features(
            runtime,
            groups,
            parameters,
            [parameters.source.selection.feature_id],
            "boundary",
        )[0]
        cloud = boundary.support
        if boundary.valid:
            cloud = select_boundary(
                runtime, cloud, parameters.source.selection, cancel=cancel
            )
    support = dimension_support(
        runtime, cloud, "source", feature=boundary, cancel=cancel
    )
    from custom_nodes.metrology3d_nodes.shared.dimension_runtime import (
        dimension_evaluation,
    )

    evaluation, _ = dimension_evaluation(parameters, boundary)
    reason = (
        cloud.reason
        if cloud.state == "unavailable"
        else boundary.reason
        if boundary and not boundary.valid
        else None
    )
    metrics = {"support_count": (support.point_count, "1")}
    geometry = candidates = None
    values = {}
    stage = "input"
    if reason is None:
        origin = np.asarray(evaluation.origin)
        rotation = np.asarray(evaluation.rotation)
        basis = rotation[:, :2]
        scan = _scan(runtime, cloud, origin, basis, cancel)
        if not scan[-1]:
            reason, stage = "degenerate_envelope", "geometry"
        elif parameters.mode.kind == "minimum-area-rectangle":
            positions, _ = materialize_positions(
                runtime, cloud, factor=1024, cancel=cancel
            )
            projected = (positions.astype(np.float64) - origin) @ basis
            local_axes, candidates = rectangle_axes(
                projected,
                parameters.mode,
                max_working_bytes=runtime.policy.max_working_bytes - positions.nbytes,
                cancel=cancel,
            )
            positions = projected = None
            if not candidates.dimensions_consistent:
                reason, stage = "ambiguous_dimensions", "candidates"
            else:
                basis = basis @ local_axes
                scan = _scan(runtime, cloud, origin, basis, cancel)
        if reason is None:
            a, b, c, d = scan[0]
            contacts = _contacts(runtime, cloud, scan, origin, rotation[:, 2], cancel)
            geometry = ExtentsGeometry(
                origin=origin,
                axes=basis.T,
                limits=scan[0],
                corners=[
                    origin + basis @ (u, v) for u, v in ((a, b), (c, b), (c, d), (a, d))
                ],
                contacts=contacts,
                candidates=candidates,
            )
            components = (
                ("u", "v")
                if parameters.mode.kind == "axis-spans"
                else ("length", "width")
            )
            values = dict(zip(components, (c - a, d - b)))
    for key in ("span_u", "span_v"):
        index = 0 if key == "span_u" else 1
        metrics[key] = (
            float(scan[0][index + 2] - scan[0][index]) if reason is None else None,
            parameters.length_unit,
        )
    if parameters.mode.kind == "minimum-area-rectangle":
        for key in (
            "hull_point_count",
            "candidate_count",
            "tied_count",
            "dimensions_consistent",
            "orientation_unique",
        ):
            metrics[key] = (
                int(getattr(candidates, key)) if candidates is not None else None,
                "1",
            )
    cancel()
    return dimension_result(
        "measure-extents",
        parameters,
        cloud.observation_id,
        (support,),
        geometry=geometry,
        metrics=metrics,
        values=values,
        reason=reason,
        stage=stage,
        candidates=candidates,
        evaluation=evaluation,
    )
