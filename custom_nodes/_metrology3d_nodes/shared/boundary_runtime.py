"""边界算法接入现有 CloudRuntime；只有有限局部支持进入数值内核。"""

from hashlib import sha256
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.boundary3d import BoundaryTopology
from backend.contracts.workflows.boundary3d_observations import (
    BoundaryFeature,
    BoundaryMethod,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.geometry3d_observations import Features3d
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.point_cloud_runtime import (
    BoundaryCloudMethod,
    BoundarySelectionMethod,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes._metrology3d_nodes.shared.crop_roi import crop_roi
from custom_nodes._metrology3d_nodes.shared.boundary_source import (
    resolve_boundary_source,
)
from custom_nodes._metrology3d_nodes.shared.extract_boundary import (
    extract_boundary_array,
)
from custom_nodes._metrology3d_nodes.shared.geometry_quality import (
    geometry_quality,
)


def require_space(runtime, reference, evaluation):
    """不自动转换单位、坐标或输入来源。"""
    if (
        reference.run_id,
        reference.spatial.frame_id,
        reference.spatial.length_unit,
    ) != (runtime.run_id, evaluation.frame_id, evaluation.length_unit):
        raise InvalidRequestError("边界输入运行、坐标或单位不一致")
    if reference.state == "ready":
        with runtime.borrow(reference):
            pass


def materialize_positions(runtime, reference, *, factor, cancel, with_sources=False):
    """物化前核验完整局部工作集，保留原坐标 dtype，不整云隐式升精度。"""
    count = reference.point_count
    if count * factor > runtime.policy.max_working_bytes:
        raise InvalidRequestError("完整局部支持超过工作预算，请缩小 ROI")
    field = next(f for f in reference.fields if f.name == "positions")
    positions = np.empty((count, 3), dtype=field.dtype)
    sources = np.empty(count, dtype="<u8") if with_sources else None
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
    remaining = (
        runtime.policy.max_working_bytes
        - positions.nbytes
        - (sources.nbytes if sources is not None else 0)
    )
    rows = min(runtime.policy.chunk_rows, remaining // (width * 2 + 128))
    if rows < 1:
        raise InvalidRequestError("局部点云访问预算不能容纳一行")
    with runtime.borrow(reference) as view:
        for start in range(0, count, rows):
            cancel()
            stop = min(start + rows, count)
            block = view.chunk(start, stop)
            if not np.isfinite(block["positions"]).all() or (
                "validity" in block and not block["validity"].all()
            ):
                raise InvalidRequestError("边界输入包含无效点，请先执行 Filter Valid")
            positions[start:stop] = block["positions"]
            if sources is not None:
                sources[start:stop] = view.source_indices(start, stop)
    return positions, sources


def own_output(runtime, arrays, keys):
    """将已纳入工作预算的输出移交给既有只读数组所有权。"""
    reservation = runtime.budget.reserve(sum(value.nbytes for value in arrays.values()))
    owner = None
    try:
        owner = OwnedCloudArrays(arrays, reservation)
        key = ("boundary", uuid4().hex)
        runtime.storage_scope.register(key, owner, lambda value: value.close())
        keys.append(key)
        return owner
    except BaseException:
        if owner is not None:
            owner.close()
        else:
            reservation.close()
        raise


def select_boundary(runtime, reference, selection, *, cancel):
    """实际段选择保持顺序和来源，不把所有点重新拟合成一个连续段。"""
    topology = reference.topology
    if topology is None:
        raise InvalidRequestError("拟合输入缺少真实边界连接")
    available = {s.segment_id: s for s in topology.segments}
    if any(key not in available for key in selection.segment_ids):
        raise InvalidRequestError("拟合指定的边界段不存在")
    if tuple(available) == selection.segment_ids:
        return reference
    count = sum(available[key].count for key in selection.segment_ids)
    dtype = "<u4" if reference.point_count <= 2**32 else "<u8"
    if count * 16 > runtime.policy.max_working_bytes:
        raise InvalidRequestError("边界段索引超过工作预算")
    indices = np.empty((count, 1), dtype=dtype)
    cursor, segments, keys = 0, [], []
    try:
        for key in selection.segment_ids:
            cancel()
            part = available[key]
            rows = min(
                runtime.policy.chunk_rows, runtime.policy.max_working_bytes // 16
            )
            for start in range(0, part.count, rows):
                stop = min(start + rows, part.count)
                indices[cursor + start : cursor + stop, 0] = np.arange(
                    part.start + start, part.start + stop, dtype=dtype
                )
            segments.append(part.model_copy(update={"start": cursor}))
            cursor += part.count
        owner = own_output(runtime, {"indices": indices}, keys)
        indices = None
        return runtime.register_ordered(
            parent=reference,
            indices=owner,
            topology=BoundaryTopology(point_count=count, segments=segments),
            method=BoundarySelectionMethod(
                method_id="select-boundary",
                method_version=1,
                parameters=selection,
                parameters_sha256=parameter_digest(selection),
            ),
            cancel=cancel,
        )
    except BaseException as error:
        indices = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise


def _extraction_quality(values, parameters, observation_id, reason):
    """边界计数与长度使用现有逐项限值，不增加产品三态实现。"""
    units = {
        name: parameters.evaluation.length_unit if name == "length" else "1"
        for name in values
    }
    if any(
        r.item_id not in units or r.unit != units[r.item_id]
        for r in parameters.quality_policy.rules
    ):
        raise InvalidRequestError("边界质量规则包含未知指标或错误单位")
    return geometry_quality(
        observation_id,
        {key: (value, units[key]) for key, value in values.items()},
        parameters.quality_policy,
        reason=reason or "metric_unavailable",
    )


def extract_boundary(
    runtime,
    reference,
    parameters,
    *,
    cancel,
    contour_plane=None,
    pose=None,
    measurement=None,
    measurement_planes=(),
):
    """ROI 分块裁剪后运行真实内核，统一发布引用、质量和失败目标。"""
    require_space(runtime, reference, parameters.evaluation)
    if reference.vertex_kind not in (None, "source"):
        raise InvalidRequestError("边界表面提取需要原始实测支持点，不递归插值生成点")
    resolution, kernel = resolve_boundary_source(
        runtime,
        reference,
        parameters,
        datum=contour_plane,
        pose=pose,
        measurement=measurement,
        measurement_planes=measurement_planes,
        cancel=cancel,
    )
    if resolution.reason:
        support = reference.unavailable(resolution.reason)
    else:
        support, _ = crop_roi(runtime, reference, parameters.region, cancel=cancel)
    reason = resolution.reason or (
        support.reason if support.state == "unavailable" else None
    )
    if reason is None and contour_plane is not None and not contour_plane.valid:
        reason = contour_plane.reason
    values = dict(
        input_count=support.point_count,
        surface_point_count=None,
        face_count=None,
        candidate_count=None,
        support_count=None,
        length=None,
    )
    result = positions = sources = None
    keys, segment_checks = [], []
    failed = None
    try:
        if reason is None:
            positions, sources = materialize_positions(
                runtime, support, factor=12544, with_sources=True, cancel=cancel
            )
            result = extract_boundary_array(
                positions,
                kernel,
                max_working_bytes=runtime.policy.max_working_bytes
                - positions.nbytes
                - sources.nbytes,
                cancel=cancel,
                contour_plane=contour_plane.geometry
                if parameters.method.kind == "contour"
                else None,
            )
            reason, values, failed = (
                result.reason,
                result.metrics,
                result.failed_segment_id,
            )
        quality = _extraction_quality(
            values, parameters, reference.observation_id, reason
        )
        if result is not None and result.reason is None:
            for segment in result.topology.segments:
                part = result.positions[
                    segment.start : segment.start + segment.count
                ].astype(np.float64)
                length = float(np.linalg.norm(np.diff(part, axis=0), axis=1).sum())
                if segment.closed:
                    length += float(np.linalg.norm(part[-1] - part[0]))
                checked = _extraction_quality(
                    {**values, "support_count": segment.count, "length": length},
                    parameters,
                    reference.observation_id,
                    None,
                )
                segment_checks.append(
                    dict(segment_id=segment.segment_id, quality=checked)
                )
                if not checked.usable and reason is None:
                    reason, failed = "insufficient_quality", segment.segment_id
            if reason is None and not quality.usable:
                reason = "insufficient_quality"
        if reason is None:
            digest = sha256(
                canonical_cloud_json(result.topology.model_dump(mode="json"))
            )
            for array in (
                result.positions,
                result.source_rows,
                result.source_edges,
                result.weights,
                result.face_offsets,
                result.source_faces,
            ):
                if array is not None:
                    digest.update(np.ascontiguousarray(array).tobytes())
            method = BoundaryCloudMethod(
                method_id="extract-boundary",
                method_version=1,
                parameters=parameters,
                parameters_sha256=parameter_digest(parameters),
                vertices_sha256=digest.hexdigest(),
                resolution=resolution,
            )
            if result.source_rows is not None:
                dtype = "<u4" if support.point_count <= 2**32 else "<u8"
                owner = own_output(
                    runtime,
                    {"indices": result.source_rows.astype(dtype).reshape(-1, 1)},
                    keys,
                )
                support = runtime.register_ordered(
                    parent=support,
                    method=method,
                    indices=owner,
                    topology=result.topology,
                    cancel=cancel,
                )
            else:
                lineage = own_output(
                    runtime,
                    dict(
                        source_edges=sources[result.source_edges],
                        weights=result.weights.astype("<f8", copy=False),
                        face_offsets=result.face_offsets.astype("<u8").reshape(-1, 1),
                        source_faces=sources[result.source_faces],
                    ),
                    keys,
                )
                owner = own_output(runtime, {"positions": result.positions}, keys)
                field = next(
                    f for f in support.fields if f.name == "positions"
                ).model_copy(update={"dtype": result.positions.dtype.name})
                support = runtime.register_generated(
                    parent=support,
                    method=method,
                    owner=owner,
                    lineage=lineage,
                    point_count=len(result.positions),
                    fields=(field,),
                    topology=result.topology,
                    cancel=cancel,
                )
        cancel()
        feature = BoundaryFeature(
            feature_id=parameters.feature_id,
            valid=reason is None,
            reason=reason,
            failed_segment_id=failed,
            geometry=result.topology if reason is None else None,
            support=support,
            quality=quality,
            segments=segment_checks,
            method=BoundaryMethod(
                parameters=parameters,
                parameters_sha256=parameter_digest(parameters),
                resolution=resolution,
            ),
        )
        return Features3d(
            run_id=runtime.run_id,
            observation_id=reference.observation_id,
            frame_id=parameters.evaluation.frame_id,
            length_unit=parameters.evaluation.length_unit,
            items=(feature,),
        )
    except BaseException as error:
        result = positions = sources = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
