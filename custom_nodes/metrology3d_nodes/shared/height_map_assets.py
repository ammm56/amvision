"""高度图随实际输入点云原子保存；复用现有资产流、Scope 和完整来源。"""

from contextlib import contextmanager
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.height_map3d import HeightMapParameters
from backend.contracts.workflows.height_map_evidence import HeightMapEvidence
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.contracts.workflows.pose3d_operations import PoseEvidence
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from custom_nodes.metrology3d_nodes.shared.height_map import HeightMapResult


def result_evidence(result, reference):
    """冻结计算参数和历史位姿，实际输入身份必须逐字段一致。"""
    if (
        result.reason is not None
        or CloudReference.model_validate_json(result.input_json) != reference
    ):
        raise InvalidRequestError("高度图无效或不属于保存点云")
    return HeightMapEvidence(
        parameters=HeightMapParameters.model_validate_json(result.parameters_json),
        pose=PoseEvidence.model_validate_json(result.pose_json)
        if result.pose_json
        else None,
        input_count=reference.point_count,
        vertex_kind=reference.vertex_kind,
        dtype=next(f.dtype for f in reference.fields if f.name == "positions"),
        outside_count=result.outside_count,
        occupied_count=result.occupied_count,
        max_rounding_error=result.max_rounding_error,
    )


def validate_arrays(runtime, reference, evidence, arrays, cancel):
    """有界核对统计、成员唯一性和输入身份；不重新拟合或填补高度。"""
    expected = {name for name, _, _ in evidence.layout()}
    if set(arrays) != expected:
        raise InvalidRequestError("高度图数组字段不完整")
    for name, dtype, count in evidence.layout():
        a = arrays[name]
        if a.shape != (count, 1) or a.dtype != np.dtype(dtype).newbyteorder("<"):
            raise InvalidRequestError("高度图数组精度或长度不一致")
    field_bytes = sum(
        np.dtype(f.dtype).itemsize * f.components for f in reference.fields
    )
    rows = min(
        runtime.policy.chunk_rows,
        (runtime.policy.max_working_bytes - reference.point_count)
        // (field_bytes + 256),
    )
    if rows < 1:
        raise InvalidRequestError("高度图来源核验超过工作预算")
    counts, offsets = arrays["counts"][:, 0], arrays["member_offsets"][:, 0]
    members = evidence.input_count - evidence.outside_count
    if int(offsets[0]) != 0 or int(offsets[-1]) != members:
        raise InvalidRequestError("高度图成员总数不一致")
    occupied = 0
    for start in range(0, len(counts), rows):
        cancel()
        stop = min(start + rows, len(counts))
        a, b = offsets[start:stop], offsets[start + 1 : stop + 1]
        c = counts[start:stop]
        if np.any(b < a) or np.any(b - a != c):
            raise InvalidRequestError("高度图 CSR 与计数不一致")
        used = c > 0
        occupied += int(np.count_nonzero(used))
        h, low, high = (
            arrays[k][start:stop, 0] for k in ("heights", "minimum", "maximum")
        )
        if any(
            np.any(np.isfinite(v) != used) or np.isinf(v).any() for v in (h, low, high)
        ):
            raise InvalidRequestError("高度图空格不能包含数值")
        if np.any(low[used] > h[used]) or np.any(h[used] > high[used]):
            raise InvalidRequestError("高度图统计超出本格高度范围")
        method = evidence.parameters.aggregation
        if method in ("minimum", "maximum") and np.any(
            h[used] != arrays[method][start:stop, 0][used]
        ):
            raise InvalidRequestError("高度图聚合值与所选方法不一致")
    if occupied != evidence.occupied_count:
        raise InvalidRequestError("高度图有数据格数不一致")
    seen = np.zeros(reference.point_count, dtype=bool)
    with runtime.borrow(reference) as view:
        for start in range(0, members, rows):
            cancel()
            indices = arrays["input_rows"][start : start + rows, 0]
            if (
                np.any(indices >= reference.point_count)
                or len(np.unique(indices)) != len(indices)
                or seen[indices].any()
            ):
                raise InvalidRequestError("高度图贡献记录重复或越界")
            seen[indices] = True
            if reference.vertex_kind == "source":
                attributes, source = view.gather(indices)
                if np.any(source != arrays["source_rows"][start : start + rows, 0]):
                    raise InvalidRequestError("高度图原始行号与保存输入不一致")
                del attributes, source


@contextmanager
def prepare_height_map(runtime, reference, result, *, mode, chunk_bytes, cancel):
    """只为显式派生保存准备同次不可变流，借用持续到版本提交结束。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _Chunks, _blob

    if mode != "derived":
        raise InvalidRequestError("高度图只允许随派生点云保存")
    evidence = result_evidence(result, reference)
    with result.borrow(runtime) as arrays:
        validate_arrays(runtime, reference, evidence, arrays, cancel)

        def chunks():
            for name, _, _ in evidence.layout():
                array = arrays[name]
                rows = max(1, chunk_bytes // array.dtype.itemsize)
                for start in range(0, len(array), rows):
                    cancel()
                    yield array[start : start + rows].tobytes(order="C")

        blob = _blob("height-map", "height-map.bin", chunks())
        yield evidence, blob, _Chunks(chunks())


def read_height_map(
    runtime, reference, *, document, service, project_id, policy, cancel
):
    """恢复保存的统计和来源，不以历史 Pose 发起新测量，也不重新聚合。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _fill

    checked_document = service.read(document.reference, project_id=project_id)
    if (
        checked_document != document
        or reference.source.kind != "asset"
        or reference.source.reference != document.reference
    ):
        raise InvalidRequestError("高度图与读取资产身份不一致")
    cloud = document.content.point_cloud
    evidence = cloud.height_map
    if evidence is None:
        return None
    chunk = min(
        policy.chunk_bytes, runtime.policy.chunk_bytes, runtime.policy.max_working_bytes
    )
    if evidence.byte_length() > min(
        policy.max_asset_bytes, runtime.policy.max_decoded_bytes
    ):
        raise InvalidRequestError("高度图数组超过显式容量")
    with runtime.producing(), runtime.borrow(reference):
        reservation = runtime.budget.reserve(evidence.byte_length())
        arrays, owner, key = {}, None, ("height-map", uuid4().hex)
        try:
            for name, dtype, count in evidence.layout():
                cancel()
                arrays[name] = np.empty(
                    (count, 1), dtype=np.dtype(dtype).newbyteorder("<")
                )
            blob = next(b for b in cloud.blobs if b.role == "height-map")
            with service.storage.open_read_snapshot(
                cloud_blob_key(service, document.reference, blob)
            ) as snapshot:
                stream = CheckedBlobStream(snapshot.stream, blob, cancel, cloud)
                for array in arrays.values():
                    _fill(stream, array, chunk, cancel)
                array = None
                if stream.read(1):
                    raise InvalidRequestError("高度图含多余字节")
            validate_arrays(runtime, reference, evidence, arrays, cancel)
            owner = OwnedCloudArrays(arrays, reservation)
            arrays.clear()
            runtime.storage_scope.register(key, owner, lambda v: v.close())
            cancel()
            return HeightMapResult(
                input_json=canonical_cloud_json(reference.model_dump(mode="json")),
                parameters_json=evidence.parameters.model_dump_json().encode(),
                pose_json=evidence.pose.model_dump_json().encode()
                if evidence.pose
                else None,
                owner=owner,
                resource_key=key,
                reason=None,
                outside_count=evidence.outside_count,
                occupied_count=evidence.occupied_count,
                max_rounding_error=evidence.max_rounding_error,
            )
        except BaseException as error:
            arrays.clear()
            array = None
            release_exception_frames(error)
            runtime.storage_scope.close_resource(key)
            if owner is not None:
                owner.close()
            reservation.close()
            raise
