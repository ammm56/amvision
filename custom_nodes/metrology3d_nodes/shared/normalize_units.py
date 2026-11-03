"""单位归一的完整数据算法；只在有界块内使用 float64。"""

from hashlib import sha256
from typing import Callable
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud import CloudField
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    NormalizeCloudMethod,
    NormalizeCloudUnits,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.runtime import CloudRuntime


def normalize_units(
    runtime: CloudRuntime,
    reference: CloudReference,
    parameters: NormalizeCloudUnits,
    *,
    cancel: Callable[[], None],
) -> CloudReference:
    """保留字段、精度与行顺序；不能用单位确认覆盖已有源声明。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    source_unit = reference.spatial.length_unit
    if parameters.source_unit is not None:
        if source_unit is not None and source_unit != parameters.source_unit:
            raise InvalidRequestError("source_unit 与源点云已声明单位不一致")
        source_unit = parameters.source_unit
    if reference.state == "unavailable":
        return reference
    with runtime.borrow(reference) as cloud:
        cancel()
        if source_unit is None:
            raise InvalidRequestError("源点云单位未知，必须显式确认")
        scaled = {
            field.name: (source_unit if field.name == "positions" else field.unit)
            for field in reference.fields
            if field.name == "positions" or field.unit in {"m", "mm", "um"}
        }
        if reference.spatial.length_unit == "mm" and all(
            unit == "mm" for unit in scaled.values()
        ):
            return reference
        fields = tuple(
            CloudField.model_validate({**field.model_dump(), "unit": "mm"})
            if field.semantic == "scalar" and field.unit in {"m", "mm", "um"}
            else field
            for field in reference.fields
        )
        row_bytes = sum(
            np.dtype(field.dtype).itemsize * field.components for field in fields
        )
        rows = min(
            runtime.policy.chunk_rows,
            runtime.policy.max_working_bytes // (row_bytes * 2 + 64),
        )
        if rows < 1:
            raise InvalidRequestError("单位归一工作预算不能容纳一行")
        reservation = runtime.budget.reserve(reference.point_count * row_bytes)
        arrays = {}
        owner = None
        block = source = target = None
        key = ("normalized", uuid4().hex)
        registered = False
        try:
            for field in fields:
                cancel()
                arrays[field.name] = np.empty(
                    (reference.point_count, field.components),
                    dtype=np.dtype(field.dtype).newbyteorder("<"),
                )
            for start in range(0, reference.point_count, rows):
                cancel()
                stop = min(start + rows, reference.point_count)
                block = cloud.chunk(start, stop)
                for field in fields:
                    source = block[field.name]
                    target = arrays[field.name][start:stop]
                    unit = scaled.get(field.name)
                    if unit is None or unit == "mm":
                        target[:] = source
                    else:
                        _convert(source, target, multiply=unit == "m")
                del block, source, target
            cancel()
            owner = OwnedCloudArrays(arrays, reservation)
            arrays.clear()
            runtime.storage_scope.register(key, owner, lambda value: value.close())
            registered = True
            method = NormalizeCloudMethod(
                method_id="normalize-units",
                method_version=1,
                parameters=parameters,
                parameters_sha256=sha256(
                    canonical_cloud_json(parameters.model_dump(mode="json"))
                ).hexdigest(),
            )
            spatial = reference.spatial.model_copy(
                update={"length_unit": "mm", "unit_source": "configuration"}
            )
            return runtime.register_derived(
                parent=reference,
                method=method,
                owner=owner,
                fields=fields,
                spatial=spatial,
                cancel=cancel,
            )
        except BaseException as error:
            arrays.clear()
            block = source = target = None  # noqa: F841 - 异常对象不能继续持有数组别名。
            release_exception_frames(error)
            if owner is None:
                reservation.close()
            elif registered:
                runtime.storage_scope.close_resource(key)
            else:
                owner.close()
            raise


def _convert(source: np.ndarray, target: np.ndarray, *, multiply: bool) -> None:
    """整数不经 double，避免 uint64 精度损失；有限浮点溢出不能伪装成无效点。"""
    if source.dtype.kind in "iu":
        wide = source.astype(np.int64 if source.dtype.kind == "i" else np.uint64)
        if multiply:
            limits = np.iinfo(source.dtype)
            if np.any(source > limits.max // 1000) or np.any(
                source < -(-int(limits.min) // 1000)
            ):
                raise InvalidRequestError("整数长度属性换算超出源 dtype 范围")
            target[:] = wide * 1000
        else:
            if np.any(wide % 1000):
                raise InvalidRequestError("整数长度属性换算结果不是整数")
            target[:] = wide // 1000
        return
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        wide = source.astype(np.float64)
        if multiply:
            wide *= 1000
        else:
            wide /= 1000
        target[:] = wide
    finite = np.isfinite(source)
    if np.any(finite & ~np.isfinite(target)) or np.any(
        finite & (source != 0) & (target == 0)
    ):
        raise InvalidRequestError("单位换算超出源浮点 dtype 的可表示范围")
