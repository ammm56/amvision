"""只消费同次定位的刚体变换，保留字段精度和原始行身份。"""

from hashlib import sha256
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.geometry3d import TransformCloudParameters
from backend.contracts.workflows.point_cloud import CloudAxes
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
    TransformCloudMethod,
    canonical_cloud_json,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays


def transform_cloud(runtime, reference, pose, *, cancel):
    """失效定位只产生缺测引用；错线和数值溢出作为执行错误。"""
    cancel()
    if (
        reference.run_id,
        reference.observation_id,
        reference.spatial.frame_id,
        reference.spatial.length_unit,
    ) != (
        runtime.run_id,
        pose.observation_id,
        pose.source_frame_id,
        pose.length_unit,
    ) or pose.run_id != runtime.run_id:
        raise InvalidRequestError("点云与位姿运行、观测、源坐标或单位不一致")
    if reference.spatial.axes.handedness != "right":
        raise InvalidRequestError("刚体变换要求明确的右手源坐标")
    for support in pose.support:
        if support.state == "ready":
            with runtime.borrow(support):
                pass
    if reference.state == "ready":
        with runtime.borrow(reference):
            pass
    spatial = reference.spatial.model_copy(
        update=dict(
            frame_id=pose.target_frame_id,
            axes=CloudAxes(
                handedness="right",
                axis_labels=("X", "Y", "Z"),
                definition_source="configuration",
            ),
        )
    )
    if reference.state == "unavailable" or pose.state != "found":
        raw = reference.model_dump(mode="json")
        raw.update(
            state="unavailable",
            reason=reference.reason or pose.reason,
            spatial=spatial.model_dump(mode="json"),
            cloud_id=None,
            revision=None,
            point_count=None,
            fields=None,
            source_metadata=None,
            sample_origin=None,
        )
        return CloudReference.model_validate(raw)
    parameters = TransformCloudParameters(
        pose_id=pose.pose_id,
        pose_sha256=sha256(
            canonical_cloud_json(pose.model_dump(mode="json"))
        ).hexdigest(),
        transform=pose.transform,
    )
    method = TransformCloudMethod(
        method_id="transform-cloud",
        method_version=1,
        parameters=parameters,
        parameters_sha256=sha256(
            canonical_cloud_json(parameters.model_dump(mode="json"))
        ).hexdigest(),
    )
    matrix = np.asarray(pose.transform.target_from_source, dtype=np.float64)
    width = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
    rows = min(
        runtime.policy.chunk_rows, runtime.policy.max_working_bytes // (width * 2 + 128)
    )
    if rows < 1:
        raise InvalidRequestError("点云变换工作预算不能容纳一行")
    reservation = runtime.budget.reserve(reference.point_count * width)
    arrays = {}
    owner = block = values = target = transformed = None
    registered = False
    key = ("transformed", uuid4().hex)
    try:
        for field in reference.fields:
            cancel()
            arrays[field.name] = np.empty(
                (reference.point_count, field.components), dtype=field.dtype
            )
        with (
            runtime.borrow(reference) as view,
            np.errstate(over="raise", invalid="raise"),
        ):
            for start in range(0, reference.point_count, rows):
                cancel()
                stop = min(start + rows, reference.point_count)
                block = view.chunk(start, stop)
                if "validity" in block and not block["validity"].all():
                    raise InvalidRequestError(
                        "变换输入包含无效点，请先执行 Filter Valid"
                    )
                for field in reference.fields:
                    values = block[field.name]
                    target = arrays[field.name][start:stop]
                    if field.semantic in {"position", "normal"}:
                        if not np.isfinite(values).all():
                            raise InvalidRequestError("变换输入包含非有限位置或法向")
                        transformed = values.astype(np.float64) @ matrix[:3, :3].T
                        if field.semantic == "position":
                            transformed += matrix[:3, 3]
                        target[:] = transformed
                        if not np.isfinite(target).all():
                            raise InvalidRequestError("变换结果超出字段精度范围")
                    else:
                        target[:] = values
                block = values = target = transformed = None
        cancel()
        owner = OwnedCloudArrays(arrays, reservation)
        arrays.clear()
        runtime.storage_scope.register(key, owner, lambda value: value.close())
        registered = True
        return runtime.register_derived(
            parent=reference,
            method=method,
            owner=owner,
            fields=reference.fields,
            spatial=spatial,
            cancel=cancel,
        )
    except BaseException as error:
        arrays.clear()
        block = values = target = transformed = None
        release_exception_frames(error)
        if owner is None:
            reservation.close()
        elif registered:
            runtime.storage_scope.close_resource(key)
        else:
            owner.close()
        raise
