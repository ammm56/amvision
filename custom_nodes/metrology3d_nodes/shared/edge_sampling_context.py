"""从仍存在的观测和裁剪依赖解释采样候选，不推断材料或传感器故障。"""

from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntFlag

import numpy as np
from scipy.spatial import cKDTree

from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.boundary_runtime import own_output
from custom_nodes.metrology3d_nodes.shared.edge_sampling import SamplingCandidates
from custom_nodes.metrology3d_nodes.shared.roi_mask import RoiMaskPlan


class SamplingContext(IntFlag):
    """多个已知邻接事实可同时存在，不把事实当作唯一物理原因。"""

    UNKNOWN = 1
    INVALID_OBSERVATION = 2
    MISSING_ACQUISITION_ROW = 4
    ROI_CUT = 8
    ACQUISITION_LIMIT = 16


@dataclass(frozen=True)
class SamplingDiagnostic:
    """仅诊断，不包含可被尺寸算法消费的 geometry 或有效实体边。"""

    candidates: SamplingCandidates
    owner: OwnedCloudArrays
    resource_key: tuple

    @contextmanager
    def borrow(self, runtime):
        """同时校验候选、原云与分类证据的所有权。"""
        if not runtime.storage_scope.owns(self.owner):
            raise InvalidRequestError("采样来源诊断已释放")
        with (
            self.candidates.borrow(runtime) as candidates,
            self.owner.borrow() as arrays,
        ):
            yield candidates, arrays


def _observations(runtime, cloud, source_rows, flags, *, available, cancel):
    """只按原始采集邻接解释事实，原始记录不存在时保留未知。"""
    raster, profiles = runtime.raster_source(cloud), runtime.profile_source(cloud)
    if cloud.vertex_kind != "source" or (raster is None and profiles is None):
        return
    root, _ = runtime.original_source(cloud)
    total = runtime.source_point_count(cloud)
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in root.fields)
    rows = min(runtime.policy.chunk_rows, (available - total) // (width * 2 + 64))
    if rows < 1:
        raise InvalidRequestError("原始观测有效性诊断超过工作预算")
    # 2 表示未保留该原记录，不能用当前子集缺点代替原始无效观测。
    state = np.full(total, 2, dtype="u1")
    if root.vertex_kind == "source":
        with runtime.borrow(root) as view:
            for start in range(0, root.point_count, rows):
                cancel()
                stop = min(root.point_count, start + rows)
                block = view.chunk(start, stop)
                if "validity" in block:
                    state[view.source_indices(start, stop)] = (
                        block["validity"][:, 0] == 0
                    ).astype("u1")

    if raster is not None:
        for index, source in enumerate(source_rows):
            cancel()
            row, column = divmod(int(source), raster.width)
            neighbors = []
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                r, c = row + dy, column + dx
                if 0 <= r < raster.height and 0 <= c < raster.width:
                    neighbors.append(r * raster.width + c)
                else:
                    flags[index] |= int(SamplingContext.ACQUISITION_LIMIT)
            if np.any(state[neighbors] == 1):
                flags[index] |= int(SamplingContext.INVALID_OBSERVATION)
        return

    with runtime.borrow_profile_rows(cloud) as table:
        offsets = table["line_offsets"].reshape(-1)
        ids = table["line_ids"].reshape(-1)
        for index, source in enumerate(source_rows):
            cancel()
            source = int(source)
            row = int(np.searchsorted(offsets, source, side="right") - 1)
            begin, end = int(offsets[row]), int(offsets[row + 1])
            if source in (begin, end - 1) or row in (0, len(ids) - 1):
                flags[index] |= int(SamplingContext.ACQUISITION_LIMIT)
            for other in (row - 1, row + 1):
                if 0 <= other < len(ids) and (
                    abs(int(ids[row]) - int(ids[other])) != 1
                    or offsets[other] == offsets[other + 1]
                ):
                    flags[index] |= int(SamplingContext.MISSING_ACQUISITION_ROW)
            neighbors = [n for n in (source - 1, source + 1) if begin <= n < end]
            if np.any(state[neighbors] == 1):
                flags[index] |= int(SamplingContext.INVALID_OBSERVATION)


def _crop_context(runtime, cloud, positions, flags, radius, *, available, cancel):
    """仅以被明确裁掉且仍可访问的邻点证明裁剪影响，不按包围盒猜测。"""
    if not len(positions):
        return
    held = len(positions) * 256
    if held >= available:
        raise InvalidRequestError("裁剪诊断候选索引超过工作预算")
    tree = cKDTree(positions, copy_data=True)
    current = cloud
    while current.provenance.method is not None:
        cancel()
        method = current.provenance.method
        parent = runtime.parent_reference(current)
        if parent is None:
            break
        # 跨坐标变换或生成点不能拿不同空间的距离证明裁剪影响。
        if (
            method.method_id in {"transform-cloud", "normalize-units"}
            or current.vertex_kind != "source"
        ):
            break
        if method.method_id == "crop-roi":
            plan = RoiMaskPlan(
                method.parameters, max_working_bytes=available - held, cancel=cancel
            )
            width = sum(
                np.dtype(f.dtype).itemsize * f.components for f in parent.fields
            )
            remaining = available - held - plan.metadata_bytes
            rows = min(
                runtime.policy.chunk_rows,
                remaining // (width * 2 + plan.row_bytes + 128),
            )
            if rows < 1:
                raise InvalidRequestError("裁剪诊断完整支持超过工作预算")

            def mark(points):
                """先数完整邻接再分块；不截断缺支持证据。"""
                cancel()
                sizes = tree.query_ball_point(
                    points, radius, workers=1, return_length=True
                )
                if int(sizes.sum()) * 64 + len(points) * 128 > remaining // 2:
                    if len(points) <= 1:
                        raise InvalidRequestError("裁剪诊断完整邻域超过工作预算")
                    mid = len(points) // 2
                    mark(points[:mid])
                    mark(points[mid:])
                    return
                for hits in tree.query_ball_point(points, radius, workers=1):
                    cancel()
                    flags[hits] |= int(SamplingContext.ROI_CUT)

            with runtime.borrow(parent) as view:
                for start in range(0, parent.point_count, rows):
                    cancel()
                    block = view.chunk(start, min(parent.point_count, start + rows))
                    points = block["positions"]
                    keep = plan.mask(points, cancel=cancel)
                    excluded_mask = ~keep & np.isfinite(points).all(axis=1)
                    if "validity" in block:
                        excluded_mask &= block["validity"][:, 0] == 1
                    excluded = points[excluded_mask]
                    if len(excluded):
                        mark(excluded)
        current = parent


def sampling_context(runtime, candidates, *, cancel):
    """必要事实与调试开关无关；分类失败回收新 owner，不损坏父候选。"""
    from backend.contracts.workflows.edge3d import SamplingBoundarySettings

    cloud = CloudReference.model_validate_json(candidates.cloud_json)
    settings = SamplingBoundarySettings.model_validate_json(candidates.settings_json)
    keys, output = [], None
    try:
        with runtime.producing(), candidates.borrow(runtime) as data:
            selected = np.flatnonzero(data["candidate"][:, 0])
            held = (
                sum(a.nbytes for a in data.values())
                + cloud.point_count
                + len(selected) * 64
            )
            available = runtime.policy.max_working_bytes - held
            width = sum(np.dtype(f.dtype).itemsize * f.components for f in cloud.fields)
            rows = min(runtime.policy.chunk_rows, available // (2 * width + 128))
            if rows < 1:
                raise InvalidRequestError("采样来源工作集超过预算")
            flags = np.zeros(len(selected), dtype="u1")
            positions = np.empty((len(selected), 3), dtype="<f8")
            with runtime.borrow(cloud) as view:
                for start in range(0, len(selected), rows):
                    cancel()
                    stop = min(len(selected), start + rows)
                    block, _ = view.gather(selected[start:stop])
                    positions[start:stop] = block["positions"]
            _observations(
                runtime,
                cloud,
                data["identity_rows"][selected, 0],
                flags,
                available=available,
                cancel=cancel,
            )
            _crop_context(
                runtime,
                cloud,
                positions,
                flags,
                settings.radius,
                available=available,
                cancel=cancel,
            )
            flags[flags == 0] = int(SamplingContext.UNKNOWN)
            output = {"context": np.zeros((cloud.point_count, 1), dtype="u1")}
            output["context"][selected, 0] = flags
            cancel()
            owner = own_output(runtime, output, keys)
            output = None
            cancel()
            return SamplingDiagnostic(candidates, owner, keys[0])
    except BaseException as error:
        output = None
        release_exception_frames(error)
        for key in reversed(keys):
            runtime.storage_scope.close_resource(key)
        raise
