"""标定标量转点云；只做显式数学映射，不执行补洞、去畸变或定位。"""

from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud import (
    CloudField,
)
from backend.contracts.workflows.raster3d import CalibratedRaster, PinholeDepth
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays


STATUS_NAMES = (
    "valid",
    "non_finite_sample",
    "masked",
    "raw_sentinel",
    "outside_range",
    "non_positive_depth",
)


@dataclass(frozen=True)
class ConvertedRaster:
    """内部所有权交接结果；来源与 Scope 由现有运行入口发布。"""

    arrays: OwnedCloudArrays
    fields: tuple[CloudField, ...]
    counts: dict[str, int]


def project_samples(values, logical_indices, spec: CalibratedRaster):
    """有界块反投影；整数像素中心与针孔方程一致，不加隐式半像素偏移。"""
    row, column = np.divmod(logical_indices, spec.width)
    p = spec.projection
    if isinstance(p, PinholeDepth):
        rays = np.column_stack(
            ((column - p.cx) / p.fx, (row - p.cy) / p.fy, np.ones(len(values)))
        )
        if p.depth_kind == "ray-range":
            rays /= np.hypot(np.hypot(rays[:, 0], rays[:, 1]), rays[:, 2])[:, None]
        return rays * values[:, None]
    return (
        np.asarray(p.origin)
        + column[:, None] * p.column_step * np.asarray(p.column_direction)
        + row[:, None] * p.row_step * np.asarray(p.row_direction)
        + values[:, None] * np.asarray(p.height_direction)
    )


def convert_raster(samples, mask, spec, *, policy, budget, scope, cancel):
    """完整像素逐行转换，输入借用由调用方保持；输出复用现有数组预算和 Scope。"""
    cancel()
    if scope.closed or budget.limit != policy.max_live_array_bytes:
        raise RuntimeError("网格转换作用域或预算无效")
    if (
        not isinstance(samples, np.ndarray)
        or samples.shape != (spec.height, spec.width)
        or samples.dtype.name != spec.dtype
        or not samples.flags.c_contiguous
        or samples.flags.writeable
    ):
        raise InvalidRequestError("标量网格必须是符合声明的只读连续 HW 数组")
    if mask is not None and (
        not isinstance(mask, np.ndarray)
        or mask.shape != samples.shape
        or mask.dtype != np.uint8
        or not mask.flags.c_contiguous
        or mask.flags.writeable
    ):
        raise InvalidRequestError("网格掩码必须是同尺寸只读连续 uint8 HW 数组")
    fields = spec.cloud_fields(has_mask=mask is not None)
    count = spec.point_count()
    if samples.nbytes + (0 if mask is None else mask.nbytes) > policy.max_decoded_bytes:
        raise InvalidRequestError("标量与掩码超过解码预算")
    retained = count * sum(np.dtype(f.dtype).itemsize * f.components for f in fields)
    rows = min(policy.chunk_rows, policy.max_working_bytes // 256)
    if rows < 1 or retained > policy.max_decoded_bytes:
        raise InvalidRequestError("网格坐标、原标量及有效性超过解码或工作预算")
    # 哨兵必须能由输入 dtype 精确表达，禁止截断/取模后匹配其他实际值。
    for value in spec.validity.invalid_raw_values:
        with np.errstate(all="ignore"):
            try:
                encoded = np.asarray(value).astype(samples.dtype).item()
            except (OverflowError, ValueError) as error:
                raise InvalidRequestError("无效哨兵不能由输入类型精确表示") from error
        if encoded != value:
            raise InvalidRequestError("无效哨兵不能由输入类型精确表示")
    reservation = budget.reserve(retained)
    arrays, owner = {}, None
    raw = physical = status = valid = indices = positions = part_mask = None
    flat = flat_mask = stored = None
    try:
        arrays = {
            f.name: np.empty(
                (count, f.components), dtype=np.dtype(f.dtype).newbyteorder("<")
            )
            for f in fields
        }
        counts = dict.fromkeys(STATUS_NAMES, 0)
        flat = samples.reshape(-1)
        flat_mask = None if mask is None else mask.reshape(-1)
        for start in range(0, count, rows):
            cancel()
            stop = min(count, start + rows)
            raw = flat[start:stop]
            status = np.zeros(stop - start, dtype=np.uint8)
            status[~np.isfinite(raw)] = 1
            if mask is not None:
                part_mask = flat_mask[start:stop]
                if np.any(part_mask > 1):
                    raise InvalidRequestError("网格掩码只能包含 0/1")
                status[(status == 0) & (part_mask == 0)] = 2
                arrays["input_mask"][start:stop, 0] = part_mask
            for sentinel in spec.validity.invalid_raw_values:
                status[(status == 0) & (raw == sentinel)] = 3
            with np.errstate(all="ignore"):
                physical = raw.astype(np.float64) * spec.value_scale + spec.value_offset
            if np.any((status == 0) & ~np.isfinite(physical)):
                raise InvalidRequestError("有效标量的尺度转换溢出")
            if spec.validity.minimum is not None:
                status[(status == 0) & (physical < spec.validity.minimum)] = 4
            if spec.validity.maximum is not None:
                status[(status == 0) & (physical > spec.validity.maximum)] = 4
            if isinstance(spec.projection, PinholeDepth):
                status[(status == 0) & (physical <= 0)] = 5
            valid = status == 0
            indices = np.arange(start, stop, dtype=np.int64)
            positions = np.full((stop - start, 3), np.nan)
            with np.errstate(all="ignore"):
                positions[valid] = project_samples(
                    physical[valid], indices[valid], spec
                )
                stored = positions.astype(spec.position_dtype)
            if not np.isfinite(stored[valid]).all():
                raise InvalidRequestError("有效标定位置超过声明坐标精度的可表示范围")
            arrays["positions"][start:stop] = stored
            arrays["raw_samples"][start:stop, 0] = raw
            arrays["validity"][start:stop, 0] = valid
            arrays["sample_status"][start:stop, 0] = status
            for index, total in enumerate(
                np.bincount(status, minlength=len(STATUS_NAMES))
            ):
                counts[STATUS_NAMES[index]] += int(total)
        cancel()
        owner = OwnedCloudArrays(arrays, reservation)
        arrays.clear()
        scope.register(
            ("point-cloud-arrays", uuid4().hex), owner, lambda value: value.close()
        )
        return ConvertedRaster(owner, fields, counts)
    except BaseException as error:
        raw = physical = status = valid = indices = positions = part_mask = None
        flat = flat_mask = stored = None
        arrays.clear()
        release_exception_frames(error)
        owner.close() if owner is not None else reservation.close()
        raise
