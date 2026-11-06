"""变长轮廓分块投影；保留采集身份，不补洞、不排序、不压缩缺行位移。"""

from dataclasses import dataclass
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud import (
    CloudField,
)
from backend.contracts.workflows.profile3d import FixedProfileStep
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.profile_rows import (
    validate_profile_rows,
    profile_sample_status,
)


STATUS_NAMES = ("valid", "non_finite_profile", "non_finite_encoder", "masked")


@dataclass(frozen=True)
class ConvertedProfiles:
    """同次点数组、严格字段及互斥状态计数；输入行表仍由入口所有者持有。"""

    arrays: OwnedCloudArrays
    fields: tuple[CloudField, ...]
    counts: dict[str, int]


def validate_profile_arrays(arrays, spec, *, has_validity, policy, cancel):
    """在输出分配前分块检查结构和原始行身份，不将坏行表当无效测点。"""
    cancel()
    layout = spec.input_layout(has_validity=has_validity)
    if set(arrays) != {name for name, _, _ in layout}:
        raise InvalidRequestError("轮廓输入字段缺失或包含未声明字段")
    if spec.input_bytes(has_validity=has_validity) > policy.max_decoded_bytes:
        raise InvalidRequestError("轮廓输入超过载荷或解码预算")
    for name, dtype, shape in layout:
        value = arrays[name]
        if (
            not isinstance(value, np.ndarray)
            or value.shape != shape
            or value.dtype.name != dtype
            or value.flags.writeable
            or not value.flags.c_contiguous
        ):
            raise InvalidRequestError(f"轮廓字段 {name} 必须为符合声明的只读连续数组")
    validate_profile_rows(arrays, spec, policy=policy, cancel=cancel)
    rows = min(policy.chunk_rows, policy.max_working_bytes // 64)
    if has_validity:
        for start in range(0, spec.point_count, rows):
            cancel()
            if np.any(arrays["validity"][start : start + rows] > 1):
                raise InvalidRequestError("轮廓有效标记只能包含 0/1")
    cancel()


def convert_profiles(arrays, spec, *, has_validity, policy, budget, scope, cancel):
    """按原始记录顺序输出；只在计算块使用 float64，不修改原坐标精度。"""
    cancel()
    if scope.closed or budget.limit != policy.max_live_array_bytes:
        raise RuntimeError("轮廓转换作用域或预算无效")
    validate_profile_arrays(
        arrays, spec, has_validity=has_validity, policy=policy, cancel=cancel
    )
    fields = spec.cloud_fields(has_validity=has_validity)
    retained = spec.point_count * sum(
        np.dtype(f.dtype).itemsize * f.components for f in fields
    )
    rows = min(policy.chunk_rows, policy.max_working_bytes // 512)
    if rows < 1 or retained > policy.max_decoded_bytes:
        raise InvalidRequestError("轮廓输出超过解码或工作预算")
    reservation = budget.reserve(retained)
    output, owner = {}, None
    logical = lines = raw = ids = displacement = encoder = status = valid = (
        positions
    ) = stored = None
    try:
        output = {
            f.name: np.empty(
                (spec.point_count, f.components),
                dtype=np.dtype(f.dtype).newbyteorder("<"),
            )
            for f in fields
        }
        counts = dict.fromkeys(STATUS_NAMES, 0)
        offsets = arrays["line_offsets"]
        for start in range(0, spec.point_count, rows):
            cancel()
            end = min(spec.point_count, start + rows)
            logical = np.arange(start, end, dtype=np.uint64)
            # 相同偏移表示空轮廓，right 选择包含实际记录的行，不合成空行样点。
            lines = np.searchsorted(offsets, logical, side="right") - 1
            ids = arrays["line_ids"][lines]
            raw = arrays["profiles"][start:end]
            if isinstance(spec.displacement, FixedProfileStep):
                with np.errstate(all="ignore"):
                    displacement = (
                        ids.astype(np.float64) - spec.displacement.origin_line_id
                    ) * spec.displacement.step
                if not np.isfinite(displacement).all():
                    raise InvalidRequestError("固定步距换算溢出")
            else:
                encoder = arrays["encoder_positions"][lines]
                with np.errstate(all="ignore"):
                    displacement = (
                        encoder.astype(np.float64) - spec.displacement.origin
                    ) * spec.displacement.scale
                if np.any(np.isfinite(encoder) & ~np.isfinite(displacement)):
                    raise InvalidRequestError("编码器尺度换算溢出")
                output["raw_encoder_position"][start:end, 0] = encoder
            if has_validity:
                output["input_mask"][start:end, 0] = arrays["validity"][start:end]
            status = profile_sample_status(
                raw[:, 0],
                raw[:, 1],
                encoder,
                arrays["validity"][start:end] if has_validity else None,
            )
            valid = status == 0
            positions = np.full((end - start, 3), np.nan)
            with np.errstate(all="ignore"):
                positions[valid] = (
                    np.asarray(spec.origin)
                    + raw[valid, 0:1].astype(np.float64) * np.asarray(spec.x_direction)
                    + displacement[valid, None] * np.asarray(spec.scan_direction)
                    + raw[valid, 1:2].astype(np.float64)
                    * np.asarray(spec.height_direction)
                )
                stored = positions.astype(spec.position_dtype)
            if not np.isfinite(stored[valid]).all():
                raise InvalidRequestError("有效轮廓位置超过声明坐标精度的可表示范围")
            output["positions"][start:end] = stored
            output["raw_profile_x"][start:end, 0] = raw[:, 0]
            output["raw_profile_height"][start:end, 0] = raw[:, 1]
            output["acquisition_line_id"][start:end, 0] = ids
            output["profile_sample_index"][start:end, 0] = logical - offsets[lines]
            output["validity"][start:end, 0] = valid
            output["sample_status"][start:end, 0] = status
            for index, total in enumerate(
                np.bincount(status, minlength=len(STATUS_NAMES))
            ):
                counts[STATUS_NAMES[index]] += int(total)
        cancel()
        owner = OwnedCloudArrays(output, reservation)
        output.clear()
        scope.register(
            ("point-cloud-arrays", uuid4().hex), owner, lambda value: value.close()
        )
        return ConvertedProfiles(owner, fields, counts)
    except BaseException as error:
        logical = lines = raw = ids = displacement = encoder = status = valid = (
            positions
        ) = stored = None
        arrays = offsets = None
        output.clear()
        release_exception_frames(error)
        owner.close() if owner is not None else reservation.close()
        raise
