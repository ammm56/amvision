"""有效点过滤：严格哨兵、有界扫描和稳定源索引，不复制整云属性。"""

from hashlib import sha256
from typing import Callable
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    FilterCloudMethod,
    FilterCloudValid,
    FilterCloudSummary,
    canonical_cloud_json,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.runtime import CloudRuntime


def filter_valid(
    runtime: CloudRuntime,
    reference: CloudReference,
    parameters: FilterCloudValid,
    *,
    cancel: Callable[[], None],
) -> tuple[CloudReference, dict]:
    """两次扫描精确分配索引；原因计数允许重叠，保留数由联合掩码决定。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    if reference.state == "unavailable":
        return reference, FilterCloudSummary(
            state="unavailable", reason=reference.reason, input_count=None,
            kept_count=None, removed_count=None, invalid_counts=None,
        ).model_dump(mode="json")
    with runtime.borrow(reference) as cloud:
        cancel()
        fields = {field.name: field for field in reference.fields}
        if set(parameters.finite_fields) - fields.keys():
            raise InvalidRequestError("finite_fields 包含不存在的字段")
        sentinels = []
        for sentinel in parameters.sentinels:
            field = fields.get(sentinel.field)
            if field is None or len(sentinel.values) != field.components:
                raise InvalidRequestError("哨兵字段或分量数不合法")
            values = []
            for value in sentinel.values:
                if field.dtype in {"int64", "uint64"}:
                    if not isinstance(value, str):
                        raise InvalidRequestError(
                            "int64/uint64 哨兵必须用十进制整数字符串"
                        )
                    value = int(value)
                elif isinstance(value, str) or (
                    field.dtype.startswith(("int", "uint")) and type(value) is not int
                ):
                    raise InvalidRequestError("哨兵值类型与点云字段不一致")
                try:
                    with np.errstate(over="ignore", invalid="ignore"):
                        converted = np.asarray(value, dtype=field.dtype).item()
                except (ValueError, OverflowError) as error:
                    raise InvalidRequestError("哨兵超出 dtype 范围") from error
                if converted != value:
                    raise InvalidRequestError("哨兵不能由字段 dtype 精确表示")
                values.append(converted)
            sentinels.append(
                (sentinel.field, np.asarray(values, dtype=field.dtype), sentinel.match)
            )
        row_bytes = sum(
            np.dtype(field.dtype).itemsize * field.components
            for field in reference.fields
        )
        rows = min(
            runtime.policy.chunk_rows,
            runtime.policy.max_working_bytes // (row_bytes * 2 + 64),
        )
        if rows < 1:
            raise InvalidRequestError("过滤工作预算不能容纳一行")
        counts = {"mask": 0, "non_finite": 0, "sentinel": 0}
        kept = 0
        try:
            for start in range(0, reference.point_count, rows):
                cancel()
                block = cloud.chunk(start, min(start + rows, reference.point_count))
                valid, invalid = _valid_mask(block, parameters.finite_fields, sentinels)
                kept += int(np.count_nonzero(valid))
                for reason, count in invalid.items():
                    counts[reason] += count
        except BaseException as error:
            block = valid = None
            release_exception_frames(error)
            raise
        block = valid = None
        dtype = np.dtype("uint32" if reference.point_count <= 2**32 else "uint64")
        reservation = runtime.budget.reserve(kept * dtype.itemsize)
        indices = owner = None
        key = ("filtered", uuid4().hex)
        registered = False
        try:
            indices = np.empty((kept, 1), dtype=dtype)
            offset = 0
            for start in range(0, reference.point_count, rows):
                cancel()
                block = cloud.chunk(start, min(start + rows, reference.point_count))
                valid, _ = _valid_mask(block, parameters.finite_fields, sentinels)
                selected = np.flatnonzero(valid)
                indices[offset : offset + len(selected), 0] = selected + start
                offset += len(selected)
            block = valid = selected = None
            if offset != kept:
                raise InvalidRequestError("只读点云在过滤期间发生变化")
            cancel()
            owner = OwnedCloudArrays({"indices": indices}, reservation)
            indices = None
            runtime.storage_scope.register(key, owner, lambda value: value.close())
            registered = True
            method = FilterCloudMethod(
                method_id="filter-valid",
                method_version=1,
                parameters=parameters,
                parameters_sha256=sha256(
                    canonical_cloud_json(parameters.model_dump(mode="json"))
                ).hexdigest(),
            )
            reference = runtime.register_subset(
                parent=reference, method=method, indices=owner, cancel=cancel
            )
            summary = FilterCloudSummary(
                state="ready",
                reason=None,
                input_count=cloud.reference.point_count,
                kept_count=kept,
                removed_count=cloud.reference.point_count - kept,
                invalid_counts=counts,
            )
            return reference, summary.model_dump(mode="json")
        except BaseException as error:
            indices = block = valid = selected = None
            release_exception_frames(error)
            if owner is None:
                reservation.close()
            elif registered:
                runtime.storage_scope.close_resource(key)
            else:
                owner.close()
            raise


def _valid_mask(block, finite_fields, sentinels):
    """缺省不把零点当无效；validity、有限性和哨兵分别统计。"""
    count = len(block["positions"])
    mask = (
        block["validity"][:, 0] == 0
        if "validity" in block
        else np.zeros(count, dtype=bool)
    )
    non_finite = np.zeros(count, dtype=bool)
    for name in finite_fields:
        non_finite |= ~np.isfinite(block[name]).all(axis=1)
    sentinel_mask = np.zeros(count, dtype=bool)
    for name, values, match in sentinels:
        equal = block[name] == values
        sentinel_mask |= equal.all(axis=1) if match == "all" else equal.any(axis=1)
    valid = ~(mask | non_finite | sentinel_mask)
    return valid, {
        "mask": int(np.count_nonzero(mask)),
        "non_finite": int(np.count_nonzero(non_finite)),
        "sentinel": int(np.count_nonzero(sentinel_mask)),
    }
