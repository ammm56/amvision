"""原始轮廓行表沿用数组预算和 Scope；不建立独立资源注册表。"""

from hashlib import sha256
from uuid import uuid4

import numpy as np

from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays


def _check_values(name, values, start, total, spec, previous):
    """运行数组和资产流共用行表值域，允许空行但不允许行身份重排。"""
    if not len(values) or name == "encoder_positions":
        return previous
    if name == "line_offsets":
        if (
            (start == 0 and values[0] != 0)
            or (previous is not None and values[0] < previous)
            or np.any(values[1:] < values[:-1])
            or np.any(values > spec.point_count)
            or (start + len(values) == total and values[-1] != spec.point_count)
        ):
            raise InvalidRequestError("轮廓行偏移首尾、范围或顺序无效")
    elif (
        np.any(values > 2**53 - 1)
        or (previous is not None and values[0] <= previous)
        or np.any(values[1:] <= values[:-1])
    ):
        raise InvalidRequestError("原采集行号必须严格递增且可由公开整数精确表达")
    return int(values[-1])


def validate_profile_rows(arrays, spec, *, policy, cancel):
    """有界检查空行/缺行身份；采集行号不能排序，编码器位置不要求单调。"""
    for name, dtype, shape in spec.row_layout():
        value = arrays.get(name)
        if (
            not isinstance(value, np.ndarray)
            or value.shape != shape
            or value.dtype != np.dtype(dtype).newbyteorder("<")
            or value.flags.writeable
            or not value.flags.c_contiguous
        ):
            raise InvalidRequestError("轮廓原始行表类型、形状或只读边界不一致")
    rows = min(policy.chunk_rows, policy.max_working_bytes // 64)
    if rows < 1:
        raise InvalidRequestError("轮廓行表检查工作预算不足")
    for name, _, shape in spec.row_layout():
        previous = None
        for start in range(0, shape[0], rows):
            cancel()
            previous = _check_values(
                name,
                arrays[name][start : start + rows],
                start,
                shape[0],
                spec,
                previous,
            )
    cancel()


class ProfileRowsBytesValidator:
    """资源 ZIP/保存入口按块检查同一行表布局，只保留不足一个数值的尾部。"""

    def __init__(self, spec):
        self.spec, self.fields, self.tail, self.previous = spec, [], b"", None
        cursor = 0
        for name, dtype, shape in spec.row_layout():
            stop = cursor + np.dtype(dtype).itemsize * shape[0]
            self.fields.append((name, dtype, shape[0], cursor, stop))
            cursor = stop

    def check(self, data, offset):
        """校验跨块偏移/身份，不依赖整个 NPZ 或整表载入。"""
        for name, dtype, total, start, stop in self.fields:
            low, high = max(offset, start), min(offset + len(data), stop)
            if low >= high:
                continue
            if low == start:
                self.previous = None
            width = np.dtype(dtype).itemsize
            index = (low - start - len(self.tail)) // width
            joined = self.tail + data[low - offset : high - offset]
            end = len(joined) // width * width
            self.tail = joined[end:]
            values = np.frombuffer(
                joined[:end], dtype=np.dtype(dtype).newbyteorder("<")
            )
            self.previous = _check_values(
                name, values, index, total, self.spec, self.previous
            )
        if not data and self.tail:
            raise InvalidRequestError("轮廓行表数值截断")


def row_chunks(arrays, spec, *, chunk_bytes, cancel):
    """同一固定布局用于摘要与持久块，不生成整表 bytes。"""
    for name, dtype, _ in spec.row_layout():
        count = chunk_bytes // np.dtype(dtype).itemsize
        if count < 1:
            raise InvalidRequestError("轮廓行表工作块不能容纳一个数值")
        for start in range(0, len(arrays[name]), count):
            cancel()
            yield arrays[name][start : start + count].tobytes(order="C")


def row_digest(arrays, spec, *, policy, cancel):
    """冻结全部行表，包括无对应样点的编码器记录。"""
    digest = sha256()
    for chunk in row_chunks(
        arrays,
        spec,
        chunk_bytes=min(policy.chunk_bytes, policy.max_working_bytes),
        cancel=cancel,
    ):
        digest.update(chunk)
    return digest.hexdigest()


def retain_profile_rows(arrays, spec, *, runtime, cancel):
    """在调用方输入释放前复制原行表；只复制一次，后续派生沿可信父链借用。"""
    validate_profile_rows(arrays, spec, policy=runtime.policy, cancel=cancel)
    if spec.row_bytes() > runtime.policy.max_decoded_bytes:
        raise InvalidRequestError("轮廓行表超过解码预算")
    reservation = runtime.budget.reserve(spec.row_bytes())
    copied, owner = {}, None
    try:
        for name, dtype, shape in spec.row_layout():
            cancel()
            copied[name] = np.empty(shape, dtype=np.dtype(dtype).newbyteorder("<"))
            rows = min(
                runtime.policy.chunk_rows, runtime.policy.max_working_bytes // 16
            )
            if rows < 1:
                raise InvalidRequestError("轮廓行表复制工作预算不足")
            for start in range(0, shape[0], rows):
                cancel()
                copied[name][start : start + rows] = arrays[name][start : start + rows]
        owner = OwnedCloudArrays(copied, reservation)
        copied.clear()
        runtime.storage_scope.register(
            ("profile-rows", uuid4().hex), owner, lambda value: value.close()
        )
        return owner
    except BaseException as error:
        copied.clear()
        release_exception_frames(error)
        owner.close() if owner is not None else reservation.close()
        raise


def validate_profile_points(arrays, table, source, *, count, indices, policy, cancel):
    """源点和原始行表双向核对；生成点不调用此检查，不能伪造唯一原记录。"""
    required = {
        f.name: f
        for f in source.profiles.cloud_fields(has_validity=source.has_validity)
        if f.name != "positions"
    }
    for name, field in required.items():
        value = arrays.get(name)
        if (
            value is None
            or value.shape != (count, 1)
            or value.dtype != np.dtype(field.dtype).newbyteorder("<")
        ):
            raise InvalidRequestError("轮廓源点缺少完整原值及身份字段")
    rows = min(policy.chunk_rows, policy.max_working_bytes // 256)
    if rows < 1:
        raise InvalidRequestError("轮廓源点核对工作预算不足")
    for start in range(0, count, rows):
        cancel()
        stop = min(count, start + rows)
        identities = (
            indices[start:stop, 0]
            if indices is not None
            else np.arange(start, stop, dtype=np.uint64)
        )
        if np.any(identities >= source.profiles.point_count):
            raise InvalidRequestError("轮廓原记录编号越界")
        lines = np.searchsorted(table["line_offsets"], identities, side="right") - 1
        if not np.array_equal(
            arrays["acquisition_line_id"][start:stop, 0], table["line_ids"][lines]
        ) or not np.array_equal(
            arrays["profile_sample_index"][start:stop, 0],
            identities - table["line_offsets"][lines],
        ):
            raise InvalidRequestError("轮廓点身份与完整原行表不一致")
        if "encoder_positions" in table and (
            arrays["raw_encoder_position"][start:stop, 0].tobytes()
            != table["encoder_positions"][lines].tobytes()
        ):
            raise InvalidRequestError("轮廓点编码器原值与行表不一致")
        status = profile_sample_status(
            arrays["raw_profile_x"][start:stop, 0],
            arrays["raw_profile_height"][start:stop, 0],
            arrays["raw_encoder_position"][start:stop, 0]
            if "raw_encoder_position" in arrays
            else None,
            arrays["input_mask"][start:stop, 0] if "input_mask" in arrays else None,
        )
        if not np.array_equal(
            status, arrays["sample_status"][start:stop, 0]
        ) or not np.array_equal(status == 0, arrays["validity"][start:stop, 0]):
            raise InvalidRequestError("轮廓点有效状态与原始观测不一致")


def profile_sample_status(x, height, encoder=None, mask=None):
    """投影和持久重读共用互斥状态，不把坏掩码当作正常无效测点。"""
    status = np.zeros(len(x), dtype=np.uint8)
    status[~np.isfinite(x) | ~np.isfinite(height)] = 1
    if encoder is not None:
        status[(status == 0) & ~np.isfinite(encoder)] = 2
    if mask is not None:
        if np.any(mask > 1):
            raise InvalidRequestError("轮廓有效标记只能包含 0/1")
        status[(status == 0) & (mask == 0)] = 3
    return status
