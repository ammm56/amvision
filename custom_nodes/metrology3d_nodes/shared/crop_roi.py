"""物理坐标闭集裁剪；派生云只增加受管索引，不复制原始属性。"""

from hashlib import sha256
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.point_cloud_runtime import (
    CropCloudMethod,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.roi_mask import RoiMaskPlan


def crop_roi(runtime, reference, parameters, *, cancel):
    """只读一遍原始字段；受预算掩码生成精确索引，失败不保留临时资源。"""
    cancel()
    if reference.run_id != runtime.run_id:
        raise InvalidRequestError("点云不属于当前运行")
    roi = next(roi for roi in parameters.rois if roi.roi_id == parameters.roi_id)
    if (reference.spatial.frame_id, reference.spatial.length_unit) != (
        roi.frame_id,
        roi.length_unit,
    ):
        raise InvalidRequestError("ROI 与点云坐标或单位不一致")
    if reference.state == "unavailable":
        return reference, dict(
            state="unavailable",
            reason=reference.reason,
            input_count=None,
            kept_count=None,
            removed_count=None,
        )
    row_bytes = sum(np.dtype(f.dtype).itemsize * f.components for f in reference.fields)
    plan = RoiMaskPlan(
        parameters, max_working_bytes=runtime.policy.max_working_bytes, cancel=cancel
    )
    rows = min(
        runtime.policy.chunk_rows,
        (runtime.policy.max_working_bytes - plan.metadata_bytes)
        // (row_bytes * 2 + plan.row_bytes),
    )
    if rows < 1:
        raise InvalidRequestError("ROI 工作预算不能容纳一行")
    reservation = owner = block = positions = mask = indices = selected = None
    mask_reservation = keep_mask = None
    registered = False
    key = ("cropped", uuid4().hex)
    with runtime.borrow(reference) as view:
        try:
            mask_reservation = runtime.budget.reserve(reference.point_count)
            keep_mask = np.empty(reference.point_count, dtype=bool)
            kept = 0
            for start in range(0, reference.point_count, rows):
                cancel()
                stop = min(start + rows, reference.point_count)
                block = view.chunk(start, stop)
                positions = np.asarray(block["positions"], dtype=np.float64)
                if not np.isfinite(positions).all() or (
                    "validity" in block and not block["validity"].all()
                ):
                    raise InvalidRequestError(
                        "ROI 输入包含无效位置，请先执行 Filter Valid"
                    )
                mask = plan.mask(positions, cancel=cancel)
                keep_mask[start:stop] = mask
                kept += int(np.count_nonzero(mask))
            block = positions = mask = None
            dtype = np.dtype("uint32" if reference.point_count <= 2**32 else "uint64")
            reservation = runtime.budget.reserve(kept * dtype.itemsize)
            indices = np.empty((kept, 1), dtype=dtype)
            offset = 0
            for start in range(0, reference.point_count, rows):
                cancel()
                selected = np.flatnonzero(keep_mask[start : start + rows])
                indices[offset : offset + len(selected), 0] = selected + start
                offset += len(selected)
            block = positions = selected = None
            if offset != kept:
                raise InvalidRequestError("只读点云在裁剪期间发生变化")
            keep_mask = None
            mask_reservation.close()
            cancel()
            owner = OwnedCloudArrays({"indices": indices}, reservation)
            indices = None
            runtime.storage_scope.register(key, owner, lambda value: value.close())
            registered = True
            method = CropCloudMethod(
                method_id="crop-roi",
                method_version=1,
                parameters=parameters,
                parameters_sha256=sha256(
                    canonical_cloud_json(parameters.model_dump(mode="json"))
                ).hexdigest(),
            )
            result = runtime.register_subset(
                parent=reference, method=method, indices=owner, cancel=cancel
            )
            return result, dict(
                state="ready",
                reason=None,
                input_count=reference.point_count,
                kept_count=kept,
                removed_count=reference.point_count - kept,
            )
        except BaseException as error:
            block = positions = mask = indices = selected = None
            release_exception_frames(error)
            if owner is None:
                if reservation is not None:
                    reservation.close()
            elif registered:
                runtime.storage_scope.close_resource(key)
            else:
                owner.close()
            raise
        finally:
            keep_mask = None
            if mask_reservation is not None:
                mask_reservation.close()
