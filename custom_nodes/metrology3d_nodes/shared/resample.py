"""明确采样定义，复用 Open3D trace、只读子集和既有 Scope。"""

import numpy as np

from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.contracts.workflows.point_cloud_runtime import ResampleCloudMethod
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import (
    materialize_positions,
    own_output,
)


def voxel_resample(
    points, identities, settings, *, max_working_bytes, chunk_rows, cancel
):
    """完整格分区只限制原生工作集；trace 是实际分组来源，不平均分块质心。"""
    import open3d as o3d

    count = len(points)
    base = count * 192
    rows = min(chunk_rows, 2**31 - 1, (max_working_bytes - base) // 768)
    if rows < 1:
        raise InvalidRequestError("体素索引及原生工作块超过工作预算")
    cancel()
    keys = np.empty((count, 3), dtype=np.int64)
    origin = np.asarray(settings.grid_origin, dtype=np.float64)
    for start in range(0, count, rows):
        cancel()
        block = points[start : start + rows].astype(np.float64)
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            scaled = np.floor((block - origin) / settings.voxel_size)
        if not np.isfinite(scaled).all() or np.any(np.abs(scaled) >= 2**31 - 2):
            raise InvalidRequestError("体素键超过 Open3D 精确整数范围")
        keys[start : start + rows] = scaled.astype(np.int64)
    cancel()
    order = np.lexsort((identities, keys[:, 2], keys[:, 1], keys[:, 0]))
    sorted_keys = keys[order]
    starts = np.r_[
        0,
        np.flatnonzero(np.any(sorted_keys[1:] != sorted_keys[:-1], axis=1)) + 1,
        count,
    ]
    if not count:
        starts = np.array([0], dtype=np.int64)
    cells = len(starts) - 1
    output_keys = sorted_keys[starts[:-1]].copy()
    del keys, sorted_keys
    centroid = settings.kind == "voxel-centroid"
    if centroid:
        ordered_ids = np.sort(identities)
        if np.any(ordered_ids[1:] == ordered_ids[:-1]):
            raise InvalidRequestError("体素质心不能重复计入同一原始行")
        del ordered_ids
    output = np.empty((cells, 3), dtype=points.dtype)
    representatives = np.empty(cells, dtype=np.int64)
    member_rows = identities[order] if centroid else None
    max_error = max_offset = 0.0
    first_cell = 0
    while first_cell < cells:
        cancel()
        first = int(starts[first_cell])
        last_cell = max(
            first_cell + 1, int(np.searchsorted(starts, first + rows, side="right") - 1)
        )
        last_cell = min(last_cell, cells)
        last = int(starts[last_cell])
        if (last - first) * 768 + base > max_working_bytes:
            raise InvalidRequestError("单个完整体素的原生工作集超过预算")
        logical = order[first:last]
        local = points[logical].astype(np.float64)
        cloud = o3d.geometry.PointCloud(o3d.utility.Vector3dVector(local))
        # min_bound 是全局固定格原点；不是随分块变化的包围盒或 ROI。
        _, _, groups = cloud.voxel_down_sample_and_trace(
            settings.voxel_size,
            origin,
            np.maximum(local.max(axis=0), origin) + settings.voxel_size,
            approximate_class=False,
        )
        cancel()
        expected = {
            tuple(map(int, output_keys[i])): i for i in range(first_cell, last_cell)
        }
        seen = set()
        for group in groups:
            cancel()
            indices = np.asarray(group, dtype=np.int64)
            if (
                len(indices) == 0
                or np.any(indices < 0)
                or np.any(indices >= len(local))
            ):
                raise InvalidRequestError("Open3D 体素成员无效")
            grid = np.floor((local[indices] - origin) / settings.voxel_size).astype(
                np.int64
            )
            key = tuple(map(int, grid[0]))
            cell = expected.get(key)
            if cell is None or cell in seen or np.any(grid != grid[0]):
                raise InvalidRequestError("Open3D 体素分组与固定格定义不一致")
            seen.add(cell)
            members = logical[indices]
            # 顺序以真实身份固定，抵消原生 hash 与输入视图遍历差异。
            members = members[np.lexsort((members, identities[members]))]
            expected_members = order[starts[cell] : starts[cell + 1]]
            if not np.array_equal(members, expected_members):
                raise InvalidRequestError("Open3D 体素成员遗漏或重复")
            values = points[members].astype(np.float64)
            mean = values[0] + (values - values[0]).mean(axis=0)
            cast = mean.astype(points.dtype)
            error = float(np.linalg.norm(cast.astype(np.float64) - mean))
            if not np.isfinite(mean).all() or not np.isfinite(error):
                raise InvalidRequestError("体素质心超出有限精度")
            max_error = max(max_error, error)
            distances = np.sum((values - mean) ** 2, axis=1)
            nearest = int(np.argmin(distances))
            representatives[cell] = members[nearest]
            max_offset = max(max_offset, float(np.sqrt(distances[nearest])))
            output[cell] = cast
        if len(seen) != last_cell - first_cell:
            raise InvalidRequestError("Open3D 体素数与输入格不一致")
        del cloud, groups, local
        first_cell = last_cell
    if centroid and max_error > settings.max_position_error:
        raise InvalidRequestError("体素质心回写误差超过显式限值")
    cancel()
    return dict(
        positions=output,
        representatives=np.sort(representatives),
        voxel_keys=output_keys,
        member_offsets=starts.astype("<u8").reshape(-1, 1),
        source_rows=member_rows,
        max_position_error=max_error,
        max_representative_offset=max_offset,
        member_count_min=int(np.min(np.diff(starts))) if cells else None,
        member_count_max=int(np.max(np.diff(starts))) if cells else None,
    )


def resample_cloud(runtime, reference, parameters, *, cancel):
    """完整输入验证后注册一个不可变结果；失败只释放本次创建的资源。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    if reference.state == "unavailable":
        return reference, dict(state="unavailable", reason=reference.reason)
    settings = parameters.settings
    with runtime.borrow(reference) as view:
        if settings.kind == "voxel-centroid" and any(
            f.name == "sample_origin" for f in reference.fields
        ):
            for start in range(0, reference.point_count, runtime.policy.chunk_rows):
                cancel()
                if np.any(
                    view.chunk(
                        start,
                        min(reference.point_count, start + runtime.policy.chunk_rows),
                    )["sample_origin"]
                    != 0
                ):
                    raise InvalidRequestError("体素质心只接受全部成员为实测点的输入")
    if settings.kind != "stride" and (
        reference.spatial.frame_id,
        reference.spatial.length_unit,
    ) != (settings.frame_id, settings.length_unit):
        raise InvalidRequestError("体素格的坐标和单位与输入不一致")
    if settings.kind == "voxel-centroid" and reference.vertex_kind != "source":
        raise InvalidRequestError("体素质心只接受有原始行号的实测输入")
    method = ResampleCloudMethod(
        method_id="resample-cloud",
        method_version=1,
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
    )
    keys, points, identities, result, indices = [], None, None, None, None
    try:
        metrics = {}
        if settings.kind == "stride":
            n = max(
                0,
                (reference.point_count - settings.offset + settings.every_k_points - 1)
                // settings.every_k_points,
            )
            dtype = "uint32" if reference.point_count <= 2**32 else "uint64"
            if n * 16 > runtime.policy.max_working_bytes:
                raise InvalidRequestError("规则采样索引超过工作预算")
            indices = np.empty((n, 1), dtype=dtype)
            with runtime.borrow(reference) as view:
                for start in range(0, reference.point_count, runtime.policy.chunk_rows):
                    cancel()
                    block = view.chunk(
                        start,
                        min(start + runtime.policy.chunk_rows, reference.point_count),
                    )
                    if not np.isfinite(block["positions"]).all() or (
                        "validity" in block and not block["validity"].all()
                    ):
                        raise InvalidRequestError(
                            "采样输入含无效点，请先执行 Filter Valid"
                        )
                for start in range(0, n, runtime.policy.chunk_rows):
                    cancel()
                    stop = min(n, start + runtime.policy.chunk_rows)
                    indices[start:stop, 0] = (
                        settings.offset
                        + np.arange(start, stop, dtype=np.uint64)
                        * settings.every_k_points
                    )
        else:
            points, identities = materialize_positions(
                runtime,
                reference,
                factor=192,
                cancel=cancel,
                with_sources=reference.vertex_kind == "source",
            )
            if identities is None:
                identities = np.arange(reference.point_count, dtype=np.uint64)
            result = voxel_resample(
                points,
                identities,
                settings,
                max_working_bytes=runtime.policy.max_working_bytes,
                chunk_rows=runtime.policy.chunk_rows,
                cancel=cancel,
            )
            metric = (
                "max_position_error"
                if settings.kind == "voxel-centroid"
                else "max_representative_offset"
            )
            metrics = {metric: result[metric]}
            metrics.update(
                {k: result[k] for k in ("member_count_min", "member_count_max")}
            )
            if settings.kind == "voxel-representative":
                dtype = "uint32" if reference.point_count <= 2**32 else "uint64"
                indices = result["representatives"].astype(dtype).reshape(-1, 1)
        cancel()
        if settings.kind == "voxel-centroid":
            source_dtype = (
                "uint32" if runtime.source_point_count(reference) <= 2**32 else "uint64"
            )
            owner = own_output(runtime, {"positions": result["positions"]}, keys)
            lineage = own_output(
                runtime,
                dict(
                    voxel_keys=result["voxel_keys"],
                    member_offsets=result["member_offsets"],
                    source_rows=result["source_rows"]
                    .astype(source_dtype)
                    .reshape(-1, 1),
                ),
                keys,
            )
            output = runtime.register_generated(
                parent=reference,
                method=method,
                owner=owner,
                lineage=lineage,
                point_count=len(result["positions"]),
                fields=tuple(f for f in reference.fields if f.name == "positions"),
                topology=None,
                cancel=cancel,
            )
        else:
            owner = own_output(runtime, {"indices": indices}, keys)
            output = runtime.register_subset(
                parent=reference, method=method, indices=owner, cancel=cancel
            )
        return output, dict(
            state="ready",
            reason=None,
            method=settings.kind,
            input_count=reference.point_count,
            output_count=output.point_count,
            source_point_count=runtime.source_point_count(reference),
            input_identity=dict(
                run_id=reference.run_id,
                cloud_id=reference.cloud_id,
                revision=reference.revision,
                observation_id=reference.observation_id,
            ),
            retained_fraction=output.point_count / reference.point_count
            if reference.point_count
            else None,
            fields_omitted=[
                f.name
                for f in reference.fields
                if f.name not in {v.name for v in output.fields}
            ],
            sample_origin=output.sample_origin,
            settings=settings.model_dump(mode="json"),
            **metrics,
        )
    except BaseException as error:
        points = identities = result = indices = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
