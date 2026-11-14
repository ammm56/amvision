"""受控 Open3D 采样边界诊断；候选只说明缺支持，不产生可测实体边。"""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntFlag

import numpy as np
from scipy.spatial import cKDTree

from backend.contracts.workflows.edge3d import SamplingBoundarySettings
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.normal_fields import (
    validate_normal_arrays,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.native_geometry import require_open3d


class SamplingStatus(IntFlag):
    """逐逻辑点完整诊断，多个失败原因不互相覆盖。"""

    COMPLETE = 0
    INVALID_NORMAL = 1
    INSUFFICIENT = 2
    SATURATED = 4
    DUPLICATE = 8
    INVALID_NEIGHBOR_NORMAL = 16


@dataclass(frozen=True)
class SamplingCandidates:
    """候选数组依赖当前云；生成点仍依赖其原 lineage，不伪造源行号。"""

    cloud_json: str
    settings_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    candidate_count: int

    @contextmanager
    def borrow(self, runtime):
        """原云和输出 owner 均需仍在同一运行内存活。"""
        cloud = CloudReference.model_validate_json(self.cloud_json)
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("采样诊断资源已释放")
        with runtime.borrow(cloud), self.owner.borrow() as arrays:
            yield arrays


def sampling_candidates(runtime, cloud, settings, *, cancel):
    """带完整邻域调用原生算子，分块只改变临时存储而不改变计算点集。"""
    settings = SamplingBoundarySettings.model_validate(settings.model_dump())
    if cloud.normal_info is None:
        raise InvalidRequestError("采样边界需要已有计算法向和有效性状态")
    count = cloud.point_count
    if cloud.state != "ready" or count is None:
        raise InvalidRequestError("采样边界需要有效点云引用")
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in cloud.fields)
    # 坐标/法向、精确树及副本、逐点计数/状态/身份和输出同时存活。
    base = count * 256
    available = runtime.policy.max_working_bytes - base
    chunk = min(runtime.policy.chunk_rows, available // (width * 2 + 128))
    if chunk < 1:
        raise InvalidRequestError("采样边界完整索引超过工作预算")
    radius_squared = settings.radius * settings.radius
    if not np.isfinite(radius_squared) or radius_squared == 0:
        raise InvalidRequestError("采样半径平方超出原生浮点范围")
    query_radius = np.nextafter(settings.radius, np.inf)
    o3d = require_open3d()
    keys, output = [], None
    points = normals = tree = block = None
    try:
        with runtime.producing(), runtime.borrow(cloud) as view:
            points = np.empty((count, 3), dtype="<f8")
            normals = np.empty((count, 3), dtype="<f8")
            valid = np.empty(count, dtype=bool)
            duplicate = np.empty(count, dtype=bool)
            identities = np.empty((count, 1), dtype="<u8")
            for start in range(0, count, chunk):
                cancel()
                stop = min(count, start + chunk)
                block = view.chunk(start, stop)
                validate_normal_arrays(
                    block, cloud.normal_info, chunk_rows=chunk, cancel=cancel
                )
                if not np.isfinite(block["positions"]).all() or (
                    "validity" in block and not block["validity"].all()
                ):
                    raise InvalidRequestError(
                        "采样边界输入含无效位置，请先执行 Filter Valid"
                    )
                points[start:stop] = block["positions"]
                normals[start:stop] = block["normals"]
                valid[start:stop] = block["normal_valid"][:, 0] == 1
                identities[start:stop, 0] = (
                    view.source_indices(start, stop)
                    if cloud.vertex_kind == "source"
                    else np.arange(start, stop, dtype="u8")
                )
            block = None
            if count:
                with np.errstate(over="ignore"):
                    span = points.max(axis=0) - points.min(axis=0)
                if not np.isfinite(span).all() or np.any(
                    span > np.sqrt(np.finfo(float).max) / 4
                ):
                    raise InvalidRequestError("采样边界坐标跨度超过精确查询范围")
            cancel()
            tree = cKDTree(points, copy_data=True)
            output = dict(
                logical_rows=np.arange(count, dtype="<u8").reshape(-1, 1),
                identity_rows=identities,
                neighbors=np.empty((count, 1), dtype="<u8"),
                status=np.zeros((count, 1), dtype="u1"),
                candidate=np.zeros((count, 1), dtype="u1"),
            )
            for start in range(0, count, chunk):
                cancel()
                stop = min(count, start + chunk)
                sizes = tree.query_ball_point(
                    points[start:stop],
                    query_radius,
                    eps=0,
                    workers=1,
                    return_length=True,
                )
                duplicates = tree.query_ball_point(
                    points[start:stop], 0.0, eps=0, workers=1, return_length=True
                )
                duplicate[start:stop] = duplicates > 1
                output["neighbors"][start:stop, 0] = sizes
            upper_counts = output["neighbors"][:, 0].copy()

            def exact_neighbors(rows):
                """SciPy 提供完整候选，按原生 squared-distance < radius² 核对边界。"""
                neighborhoods = tree.query_ball_point(
                    points[rows], query_radius, eps=0, workers=1
                )
                result = []
                for row, neighbors in zip(rows, neighborhoods):
                    cancel()
                    ids = np.asarray(neighbors, dtype=np.int64)
                    delta = points[ids] - points[row]
                    squared = (delta[:, 0] ** 2 + delta[:, 1] ** 2) + delta[:, 2] ** 2
                    result.append(ids[squared < radius_squared])
                return result

            def classify(rows):
                """先用闭区间计数限制临时邻接表，再记录原生开区间的实际数量。"""
                cancel()
                if not len(rows):
                    return
                needed = int(upper_counts[rows].sum()) * 128
                if needed > available:
                    if len(rows) == 1:
                        raise InvalidRequestError("采样边界完整邻域计数超过工作预算")
                    half = len(rows) // 2
                    classify(rows[:half])
                    classify(rows[half:])
                    return
                for row, neighbors in zip(rows, exact_neighbors(rows)):
                    size = len(neighbors)
                    state = 0
                    if not valid[row]:
                        state |= int(SamplingStatus.INVALID_NORMAL)
                    if size < settings.min_neighbors + 1:
                        state |= int(SamplingStatus.INSUFFICIENT)
                    if size > settings.max_neighbors:
                        state |= int(SamplingStatus.SATURATED)
                    if duplicate[neighbors].any():
                        state |= int(SamplingStatus.DUPLICATE)
                    if not valid[neighbors].all():
                        state |= int(SamplingStatus.INVALID_NEIGHBOR_NORMAL)
                    output["neighbors"][row, 0] = size
                    output["status"][row, 0] = state

            for start in range(0, count, chunk):
                classify(np.arange(start, min(count, start + chunk)))

            def native_batch(rows):
                """完整半径 halo；大块递分为小块，单点也超预算时明确拒绝。"""
                cancel()
                if not len(rows):
                    return
                worst = int(output["neighbors"][rows, 0].sum())
                native_bytes = (
                    worst * (256 + settings.max_neighbors * 24)
                    + int(upper_counts[rows].sum()) * 128
                )
                if native_bytes > available:
                    if len(rows) == 1:
                        raise InvalidRequestError("采样边界完整原生邻域超过工作预算")
                    half = len(rows) // 2
                    native_batch(rows[:half])
                    native_batch(rows[half:])
                    return
                neighborhoods = exact_neighbors(rows)
                halo = np.unique(np.concatenate(neighborhoods).astype(np.int64))
                native = o3d.t.geometry.PointCloud(
                    o3d.core.Tensor(np.ascontiguousarray(points[halo]))
                )
                native.point.normals = o3d.core.Tensor(
                    np.ascontiguousarray(normals[halo])
                )
                cancel()
                _, mask = native.compute_boundary_points(
                    settings.radius, settings.max_neighbors, settings.angle_degrees
                )
                actual = mask.numpy()[np.searchsorted(halo, rows)]
                cancel()
                output["candidate"][rows, 0] = actual & (output["status"][rows, 0] == 0)

            for start in range(0, count, chunk):
                cancel()
                stop = min(count, start + chunk)
                selected = np.flatnonzero(output["status"][start:stop, 0] == 0) + start
                native_batch(selected)
            cancel()
            candidate_count = int(output["candidate"].sum())
            owner = own_output(runtime, output, keys)
            output = None
            cancel()
            return SamplingCandidates(
                cloud.model_dump_json(),
                settings.model_dump_json(),
                owner,
                keys[0],
                candidate_count,
            )
    except BaseException as error:
        output = points = normals = tree = block = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
