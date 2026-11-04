"""法向内核接入现有不可变派生云、预算和 Scope，不注册空壳节点。"""

from uuid import uuid4

import numpy as np

from backend.contracts.workflows.cloud_normal_info import (
    CloudNormalInfo,
    EstimateNormalsMethod,
    NORMAL_FIELDS,
)
from backend.contracts.workflows.geometry3d_methods import parameter_digest
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.normal_estimation import (
    estimate_normal_arrays,
)


def estimate_normals(runtime, reference, parameters, *, cancel):
    """保持全部行和非计算属性；失败不发布部分云，父云不变。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    if reference.state == "unavailable":
        return reference, dict(state="unavailable", reason=reference.reason)
    if (reference.spatial.frame_id, reference.spatial.length_unit) != (
        parameters.frame_id,
        parameters.length_unit,
    ):
        raise InvalidRequestError("法向输入坐标系或单位与参数不一致")
    present = {f.name for f in reference.fields} & set(NORMAL_FIELDS)
    if present and parameters.existing_normals == "reject":
        raise InvalidRequestError("输入已有法向字段，必须显式选择替换")
    if reference.normal_info is None and present - {"normals"}:
        raise InvalidRequestError("未声明计算来源的同名标量不能被法向替换覆盖")
    method = EstimateNormalsMethod(
        method_id="estimate-normals",
        method_version=1,
        parameters=parameters,
        parameters_sha256=parameter_digest(parameters),
    )
    info = CloudNormalInfo(
        method=method,
        support={
            name: getattr(reference, name)
            for name in ("run_id", "observation_id", "cloud_id", "revision")
        },
        frame_id=parameters.frame_id,
        length_unit=parameters.length_unit,
        orientation=parameters.orientation,
    )
    position = next(f for f in reference.fields if f.name == "positions")
    kept = tuple(f for f in reference.fields if f.name not in NORMAL_FIELDS)
    fields = (*kept, *info.fields(position.dtype))
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in fields)
    input_width = sum(
        np.dtype(f.dtype).itemsize * f.components for f in reference.fields
    )
    count = reference.point_count
    # 输出及身份单独预留，内核预算再扣除它们，避免工作副本漏计。
    output_size, identity_size = count * width, count * 8
    remaining = runtime.policy.max_working_bytes - output_size - identity_size
    rows = min(
        runtime.policy.chunk_rows, (remaining - count * 256) // (input_width * 2 + 128)
    )
    if rows < 1:
        raise InvalidRequestError("法向完整输出、空间索引和访问块超过工作预算")
    reservation = runtime.budget.reserve(output_size)
    arrays, computed = {}, {}
    identities = owner = block = None
    key = ("normals", uuid4().hex)
    registered = False
    try:
        with runtime.borrow(reference) as view:
            identities = np.empty(count, dtype="<u8")
            for field in kept:
                cancel()
                arrays[field.name] = np.empty(
                    (count, field.components), dtype=field.dtype
                )
            for start in range(0, count, rows):
                cancel()
                stop = min(start + rows, count)
                block = view.chunk(start, stop)
                if "validity" in block and not block["validity"].all():
                    raise InvalidRequestError(
                        "法向输入包含无效点，请先执行 Filter Valid"
                    )
                for field in kept:
                    arrays[field.name][start:stop] = block[field.name]
                identities[start:stop] = (
                    view.source_indices(start, stop)
                    if reference.vertex_kind == "source"
                    else np.arange(start, stop, dtype="u8")
                )
            block = None
        computed = estimate_normal_arrays(
            arrays["positions"],
            identities,
            parameters,
            max_working_bytes=remaining,
            chunk_rows=rows,
            cancel=cancel,
        )
        identities = None
        summary = dict(
            state="ready",
            reason=None,
            input_count=count,
            valid_count=int(np.count_nonzero(computed["normal_valid"])),
            oriented_count=int(np.count_nonzero(computed["normal_oriented"])),
            reason_counts={
                str(i): int(np.count_nonzero(computed["normal_reason"] == i))
                for i in range(6)
            },
            parameters=parameters.model_dump(mode="json"),
        )
        arrays.update(computed)
        computed.clear()
        cancel()
        owner = OwnedCloudArrays(arrays, reservation)
        arrays.clear()
        runtime.storage_scope.register(key, owner, lambda value: value.close())
        registered = True
        output = runtime.register_derived(
            parent=reference,
            method=method,
            owner=owner,
            fields=fields,
            spatial=reference.spatial,
            cancel=cancel,
        )
        return output, summary
    except BaseException as error:
        arrays.clear()
        computed.clear()
        identities = block = None
        release_exception_frames(error)
        if owner is None:
            reservation.close()
        elif registered:
            runtime.storage_scope.close_resource(key)
        else:
            owner.close()
        raise
