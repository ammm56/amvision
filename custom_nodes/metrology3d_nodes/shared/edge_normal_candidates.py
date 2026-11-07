"""已有法向发现折角候选，完整双侧 ROI 复核；不生成理论交线。"""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum

import numpy as np
from scipy.spatial import cKDTree

from backend.contracts.workflows.edge3d import NormalCreaseSettings
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
from custom_nodes.metrology3d_nodes.shared.edge_support import verify_edge_support
from custom_nodes.metrology3d_nodes.shared.roi_mask import RoiMaskPlan


class NormalNeighborhoodStatus(IntEnum):
    """逐输入点的搜索诊断；失败点不从统计或来源中删除。"""

    COMPLETE = 0
    INVALID_NORMAL = 1
    SATURATED = 2
    INSUFFICIENT = 3
    INVALID_NEIGHBOR_NORMAL = 4


SUPPORT_REASONS = (
    None,
    "insufficient_support",
    "degenerate_support",
    "side_quality_failed",
    "smooth_surface",
    "support_overlap",
    "unassigned_support",
    "normal_angle_insufficient",
)


@dataclass(frozen=True)
class NormalCreaseCandidates:
    """只读逐点诊断和实际点对，父云关闭后不能借用。"""

    cloud_json: str
    settings_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    candidate_count: int
    supported_count: int

    @contextmanager
    def borrow(self, runtime):
        """沿 CloudRuntime 和 Scope 验证运行身份，不另建引用注册表。"""
        cloud = CloudReference.model_validate_json(self.cloud_json)
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("法向边候选资源已释放")
        with runtime.borrow(cloud), self.owner.borrow() as arrays:
            yield arrays


def normal_crease_candidates(runtime, cloud, settings, *, cancel):
    """按完整半径计数后查候选，超查询上限明确失败而非截断拟合。"""
    settings = NormalCreaseSettings.model_validate(settings.model_dump())
    if cloud.normal_info is None:
        raise InvalidRequestError("法向折边需要已有计算法向及有效状态")
    if cloud.vertex_kind != "source":
        raise InvalidRequestError("法向折边原始点候选不接受生成顶点")
    plans, metadata = [], 0
    for region in (settings.support_a, settings.support_b):
        if any(
            (r.frame_id, r.length_unit)
            != (cloud.spatial.frame_id, cloud.spatial.length_unit)
            for r in region.rois
        ):
            raise InvalidRequestError("法向折边支持 ROI 与源云空间不一致")
        plan = RoiMaskPlan(
            region,
            max_working_bytes=runtime.policy.max_working_bytes - metadata,
            cancel=cancel,
        )
        plans.append(plan)
        metadata += plan.metadata_bytes
    count = cloud.point_count
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in cloud.fields)
    # 原云访问块、坐标/法向副本、精确树、身份和查询临时数组同时计费。
    base = count * 512 + metadata
    available = runtime.policy.max_working_bytes - base
    chunk = min(runtime.policy.chunk_rows, available // (2 * width + 512))
    if chunk < 1:
        raise InvalidRequestError("法向折边完整索引超过工作预算")
    output, keys, block, tree = None, [], None, None
    try:
        with runtime.producing(), runtime.borrow(cloud) as view:
            points = np.empty((count, 3), dtype="<f8")
            normals = np.empty((count, 3), dtype="<f8")
            valid = np.empty(count, dtype=bool)
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
                        "法向折边输入含无效位置，请先执行 Filter Valid"
                    )
                points[start:stop] = block["positions"]
                normals[start:stop] = block["normals"]
                valid[start:stop] = block["normal_valid"][:, 0] == 1
                identities[start:stop, 0] = view.source_indices(start, stop)
            block = None
            if count:
                with np.errstate(over="ignore"):
                    span = points.max(axis=0) - points.min(axis=0)
                if not np.isfinite(span).all() or np.any(
                    span > np.sqrt(np.finfo(float).max) / 4
                ):
                    raise InvalidRequestError("法向折边坐标跨度超过精确查询范围")
            cancel()
            tree = cKDTree(points, copy_data=True)
            cancel()
            neighbors = np.empty((count, 1), dtype="<u8")
            status = np.zeros((count, 1), dtype="u1")
            for start in range(0, count, chunk):
                cancel()
                stop = min(count, start + chunk)
                neighbors[start:stop, 0] = tree.query_ball_point(
                    points[start:stop],
                    settings.radius,
                    eps=0,
                    workers=1,
                    return_length=True,
                )
            # 搜索只需要自身和一个对点；拟面最少支持由显式 support.min_points 判定。
            status[neighbors[:, 0] < 2, 0] = NormalNeighborhoodStatus.INSUFFICIENT
            status[neighbors[:, 0] > settings.max_neighbors, 0] = (
                NormalNeighborhoodStatus.SATURATED
            )
            status[~valid, 0] = NormalNeighborhoodStatus.INVALID_NORMAL

            def neighborhood(row):
                """查询已计数的完整邻域；查询上限只决定失败，不删除邻点。"""
                cancel()
                size = int(neighbors[row, 0])
                if size * 160 > available:
                    raise InvalidRequestError("单点完整折边邻域超过工作预算")
                return np.asarray(
                    tree.query_ball_point(
                        points[row], settings.radius, eps=0, workers=1
                    ),
                    dtype=np.int64,
                )

            for row in range(count):
                cancel()
                if status[row, 0] == 0 and not valid[neighborhood(row)].all():
                    status[row, 0] = NormalNeighborhoodStatus.INVALID_NEIGHBOR_NORMAL

            def pairs():
                """确定性枚举完整候选；两端都必须有完整有效邻域。"""
                for row in range(count):
                    cancel()
                    if status[row, 0]:
                        continue
                    selected = neighborhood(row)
                    selected = selected[(selected > row) & (status[selected, 0] == 0)]
                    distances = np.linalg.norm(points[selected] - points[row], axis=1)
                    # 只比较方向夹角，反转合法法向不改变折角。
                    cosine = np.abs(normals[selected] @ normals[row]) / (
                        np.linalg.norm(normals[selected], axis=1)
                        * np.linalg.norm(normals[row])
                    )
                    angles = np.arccos(np.clip(cosine, 0, 1))
                    for index in np.flatnonzero(
                        (distances <= settings.max_pair_distance)
                        & (angles >= settings.min_angle)
                    ):
                        cancel()
                        yield row, int(selected[index]), float(angles[index])

            total = 0
            for _ in pairs():
                total += 1
                if total * 201 + (2 * width + 512) > available:
                    raise InvalidRequestError("完整法向候选输出超过工作预算")
            available -= total * 201
            if available < (2 * width + 512):
                raise InvalidRequestError("完整法向候选输出超过工作预算")
            output = dict(
                source_rows=identities,
                neighbors=neighbors,
                status=status,
                pairs=np.empty((total, 2), dtype="<u8"),
                angle=np.empty((total, 1), dtype="<f8"),
                counts=np.empty((total, 2), dtype="<u8"),
                window_counts=np.empty((total, 3), dtype="<u8"),
                rms=np.full((total, 3), np.nan, dtype="<f8"),
                maximum=np.full((total, 2), np.nan, dtype="<f8"),
                model_origins=np.full((total, 6), np.nan, dtype="<f8"),
                model_normals=np.full((total, 6), np.nan, dtype="<f8"),
                reason=np.empty((total, 1), dtype="u1"),
            )
            supported = 0
            for index, (first, second, angle) in enumerate(pairs()):
                cancel()
                # 中点仅定义完整支持窗口，不作为生成测量点或实体边输出。
                center = points[first] / 2 + points[second] / 2
                size = int(
                    tree.query_ball_point(
                        center,
                        settings.support.radius,
                        eps=0,
                        workers=1,
                        return_length=True,
                    )
                )
                if size * (256 + sum(p.row_bytes for p in plans)) > available:
                    raise InvalidRequestError("法向边完整双侧支持超过工作预算")
                selected = np.asarray(
                    tree.query_ball_point(
                        center, settings.support.radius, eps=0, workers=1
                    ),
                    dtype=np.int64,
                )
                local = points[selected]
                masks = np.column_stack([p.mask(local, cancel=cancel) for p in plans])
                sizes, unassigned, overlap, rms, maximum, joint, models, reason = (
                    verify_edge_support(local, masks, settings, chunk, cancel)
                )
                output["pairs"][index] = first, second
                output["angle"][index, 0] = angle
                output["counts"][index] = sizes
                output["window_counts"][index] = len(local), unassigned, overlap
                if rms is not None:
                    output["rms"][index, :2] = rms
                    output["maximum"][index] = maximum
                if joint is not None:
                    output["rms"][index, 2] = joint
                if models is not None:
                    for side, (origin, normal) in enumerate(models):
                        output["model_origins"][index, side * 3 : side * 3 + 3] = origin
                        output["model_normals"][index, side * 3 : side * 3 + 3] = normal
                output["reason"][index, 0] = SUPPORT_REASONS.index(reason)
                supported += reason is None
            cancel()
            owner = own_output(runtime, output, keys)
            output = None
            cancel()
            return NormalCreaseCandidates(
                cloud.model_dump_json(),
                settings.model_dump_json(),
                owner,
                keys[0],
                total,
                supported,
            )
    except BaseException as error:
        output = block = tree = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
