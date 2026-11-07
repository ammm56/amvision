"""B09 高度跃变的同云候选与完整双侧验证，不发布未完成的边界拓扑。"""

from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite

import numpy as np

from backend.contracts.workflows.edge3d import (
    EdgePairEvidence,
    HeightJumpCandidateSettings,
)
from backend.contracts.workflows.height_map_reference import HeightMapReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.height_grid import grid_local_points
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)
from custom_nodes.metrology3d_nodes.shared.edge_support import verify_edge_support
from custom_nodes.metrology3d_nodes.shared.roi_mask import RoiMaskPlan
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays


REASONS = (
    None,
    "insufficient_support",
    "degenerate_support",
    "side_quality_failed",
    "smooth_surface",
    "height_direction_ambiguous",
    "support_overlap",
    "unassigned_support",
)


@dataclass(frozen=True)
class HeightJumpCandidates:
    """Scope 持有紧凑格对/指标；身份仍引用完整高度图，不复制完整输入。"""

    height_map_json: str
    settings_json: str
    owner: OwnedCloudArrays
    resource_key: tuple
    candidate_count: int
    supported_count: int
    missing_pair_count: int

    @contextmanager
    def borrow(self, runtime):
        """结果依赖原高度图和完整云，释放任何父资源后都不能继续解析。"""
        ref = HeightMapReference.model_validate_json(self.height_map_json)
        parent = resolve_height_map(runtime, ref)
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("边候选资源已释放")
        with parent.borrow(runtime), self.owner.borrow() as arrays:
            yield arrays


def grid_pairs(width, height, adjacency, counts, *, cancel):
    """规范行序枚举唯一邻接，对角必须有两正交桥格，不能穿过空角。"""
    directions = ((0, 1), (1, 0))
    if adjacency == 8:
        directions += ((1, -1), (1, 1))
    for row in range(height):
        cancel()
        for column in range(width):
            if column % 4096 == 0:
                cancel()
            first = row * width + column
            for dr, dc in directions:
                rr, cc = row + dr, column + dc
                if not (0 <= rr < height and 0 <= cc < width):
                    continue
                second = rr * width + cc
                if not counts[first] and not counts[second]:
                    continue
                if (
                    dr
                    and dc
                    and (
                        not counts[row * width + cc] or not counts[rr * width + column]
                    )
                ):
                    continue
                yield first, second


def pair_evidence(arrays, index):
    """将一条紧凑诊断转成经过校验的有界证据，不展开整个候选表。"""
    rms = arrays["rms"][index]
    residual = arrays["maximum"][index]
    code = int(arrays["reason"][index, 0])
    return EdgePairEvidence(
        cells=tuple(int(v) for v in arrays["cells"][index]),
        candidate_delta=float(arrays["delta"][index, 0]),
        side_counts=tuple(int(v) for v in arrays["counts"][index]),
        window_count=int(arrays["window_counts"][index, 0]),
        unassigned_count=int(arrays["window_counts"][index, 1]),
        overlap_count=int(arrays["window_counts"][index, 2]),
        side_rms=tuple(float(v) for v in rms[:2])
        if np.isfinite(rms[:2]).all()
        else None,
        side_max_residual=tuple(float(v) for v in residual)
        if np.isfinite(residual).all()
        else None,
        joint_rms=float(rms[2]) if np.isfinite(rms[2]) else None,
        models=tuple(
            dict(
                origin=arrays["model_origins"][index, side * 3 : side * 3 + 3],
                normal=arrays["model_normals"][index, side * 3 : side * 3 + 3],
            )
            for side in range(2)
        )
        if np.isfinite(arrays["model_normals"][index]).all()
        else None,
        supported=code == 0,
        reason=REASONS[code],
    )


def _window(
    view, arrays, grid, center, radius, transform, runtime, held, plans, cancel
):
    """先计数/准入，再逐格读取完整贡献；不创建整云坐标或邻接图副本。"""
    steps = np.array((grid.grid.column_step, grid.grid.row_step))
    with np.errstate(over="ignore"):
        lower = np.clip(
            np.ceil((center - radius) / steps - 0.5),
            0,
            (grid.width - 1, grid.height - 1),
        ).astype(np.int64)
        upper = np.clip(
            np.floor((center + radius) / steps + 0.5),
            0,
            (grid.width - 1, grid.height - 1),
        ).astype(np.int64)
    offsets = arrays["member_offsets"][:, 0]

    def cells():
        """反复遍历有限格域，不保留与格数同阶的 Python 对象列表。"""
        for row in range(int(lower[1]), int(upper[1]) + 1):
            cancel()
            yield row * grid.width + int(lower[0]), row * grid.width + int(upper[0]) + 1

    total = sum(int(offsets[stop] - offsets[start]) for start, stop in cells())
    width = sum(
        np.dtype(f.dtype).itemsize * f.components for f in view.reference.fields
    )
    # 局部坐标、掩码/索引、两侧/联合 QR 与 gather 工作副本同时计费。
    available = runtime.policy.max_working_bytes - held - total * 256
    chunk = min(
        runtime.policy.chunk_rows,
        available // (width * 2 + 256 + sum(p.row_bytes for p in plans)),
    )
    if chunk < 1:
        raise InvalidRequestError("边缘完整双侧窗口超过工作预算")
    local = np.empty((total, 3), dtype=np.float64)
    masks = np.empty((total, 2), dtype=bool)
    cursor = 0
    for first, last in cells():
        for start in range(int(offsets[first]), int(offsets[last]), chunk):
            cancel()
            stop = min(start + chunk, int(offsets[last]))
            block, _ = view.gather(arrays["input_rows"][start:stop, 0])
            part = grid_local_points(
                block["positions"], grid, target_from_source=transform
            )
            local[cursor : cursor + len(part)] = part
            for side, plan in enumerate(plans):
                masks[cursor : cursor + len(part), side] = plan.mask(
                    block["positions"], cancel=cancel
                )
            cursor += len(part)
    keep = np.linalg.norm(local[:, :2] - center, axis=1) <= radius
    return local[keep], masks[keep], chunk


def height_jump_candidates(runtime, cloud, height_map, settings, *, cancel):
    """生成同云格对诊断；连续边选择/公开接线完成前不输出 BoundaryFeature。"""
    settings = HeightJumpCandidateSettings.model_validate(settings.model_dump())
    ref = HeightMapReference.model_validate(height_map)
    with runtime.producing():
        result = resolve_height_map(runtime, ref, cloud=cloud)
        if result.reason is not None:
            raise InvalidRequestError("高度图不可用，不能提取边候选")
        grid = ref.evidence.parameters
        with result.borrow(runtime) as parent_arrays:
            parent_bytes = sum(a.nbytes for a in parent_arrays.values())
        plans, metadata = [], 0
        for region in (settings.support_a, settings.support_b):
            if any(
                (roi.frame_id, roi.length_unit)
                != (cloud.spatial.frame_id, cloud.spatial.length_unit)
                for roi in region.rois
            ):
                raise InvalidRequestError("边缘支持 ROI 与点云坐标或单位不一致")
            plan = RoiMaskPlan(
                region,
                max_working_bytes=runtime.policy.max_working_bytes
                - parent_bytes
                - metadata,
                cancel=cancel,
            )
            plans.append(plan)
            metadata += plan.metadata_bytes
        transform = (
            np.asarray(ref.evidence.pose.transform.matrix)
            if ref.evidence.pose
            else None
        )
        keys, output = [], None
        try:
            with result.borrow(runtime) as arrays, runtime.borrow(cloud) as view:
                counts, heights = arrays["counts"][:, 0], arrays["heights"][:, 0]
                total, missing = 0, 0
                for first, second in grid_pairs(
                    grid.width, grid.height, settings.adjacency, counts, cancel=cancel
                ):
                    if bool(counts[first]) != bool(counts[second]):
                        missing += 1
                    elif (
                        counts[first]
                        and abs(float(heights[first]) - float(heights[second]))
                        >= settings.candidate_delta
                    ):
                        total += 1
                held = total * 201 + parent_bytes + metadata
                if held + 1024 > runtime.policy.max_working_bytes:
                    raise InvalidRequestError("完整高度图与边候选超过工作预算")
                output = {
                    "cells": np.empty((total, 2), dtype="<u8"),
                    "delta": np.empty((total, 1), dtype="<f8"),
                    "counts": np.empty((total, 2), dtype="<u8"),
                    "window_counts": np.empty((total, 3), dtype="<u8"),
                    "rms": np.full((total, 3), np.nan, dtype="<f8"),
                    "maximum": np.full((total, 2), np.nan, dtype="<f8"),
                    "model_origins": np.full((total, 6), np.nan, dtype="<f8"),
                    "model_normals": np.full((total, 6), np.nan, dtype="<f8"),
                    "reason": np.empty((total, 1), dtype="u1"),
                }
                index, supported = 0, 0
                steps = np.array((grid.grid.column_step, grid.grid.row_step))
                for first, second in grid_pairs(
                    grid.width, grid.height, settings.adjacency, counts, cancel=cancel
                ):
                    if not counts[first] or not counts[second]:
                        continue
                    delta = abs(float(heights[first]) - float(heights[second]))
                    if not isfinite(delta):
                        raise InvalidRequestError("高度差超出有限数值范围")
                    if delta < settings.candidate_delta:
                        continue
                    cancel()
                    a = np.array((first % grid.width, first // grid.width)) * steps
                    b = np.array((second % grid.width, second // grid.width)) * steps
                    center = (a + b) / 2
                    points, masks, chunk = _window(
                        view,
                        arrays,
                        grid,
                        center,
                        settings.support.radius,
                        transform,
                        runtime,
                        held,
                        plans,
                        cancel,
                    )
                    sizes, unassigned, overlap, rms, maximum, joint, models, reason = (
                        verify_edge_support(points, masks, settings, chunk, cancel)
                    )
                    output["cells"][index] = (first, second)
                    output["delta"][index, 0] = delta
                    output["counts"][index] = sizes
                    output["window_counts"][index] = (len(points), unassigned, overlap)
                    if rms is not None:
                        output["rms"][index, :2] = rms
                        output["maximum"][index] = maximum
                    if joint is not None:
                        output["rms"][index, 2] = joint
                    if models is not None:
                        for side, (origin, normal) in enumerate(models):
                            output["model_origins"][index, side * 3 : side * 3 + 3] = (
                                origin
                            )
                            output["model_normals"][index, side * 3 : side * 3 + 3] = (
                                normal
                            )
                    output["reason"][index, 0] = REASONS.index(reason)
                    supported += reason is None
                    index += 1
                    points = None
                    masks = None
                cancel()
                owner = own_output(runtime, output, keys)
                output = None
                cancel()
                return HeightJumpCandidates(
                    ref.model_dump_json(),
                    settings.model_dump_json(),
                    owner,
                    keys[0],
                    total,
                    supported,
                    missing,
                )
        except BaseException as error:
            output = None
            release_exception_frames(error)
            for key in reversed(keys):
                runtime.storage_scope.close_resource(key)
            raise
