"""采样诊断随完整输入点云保存，沿用既有资源事务、流和 Scope。"""

from contextlib import contextmanager
from uuid import uuid4

import numpy as np

from backend.contracts.workflows.edge3d import SamplingBoundarySettings
from backend.contracts.workflows.edge_sampling_evidence import SamplingEvidence
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from backend.service.application.runtime.exception_cleanup import (
    release_exception_frames,
)
from backend.service.application.workflows.documents.cloud_resource_blobs import (
    CheckedBlobStream,
    cloud_blob_key,
)
from backend.service.application.workflows.point_cloud.arrays import OwnedCloudArrays
from backend.service.application.workflows.point_cloud.sampling_bytes import (
    SAMPLING_DTYPE,
    validate_records,
)
from custom_nodes.metrology3d_nodes.shared.edge_sampling import SamplingCandidates
from custom_nodes.metrology3d_nodes.shared.edge_sampling_context import (
    SamplingDiagnostic,
)


def _check_identities(view, records, start, cancel):
    """内容摘要之外还核对原始行号；生成点身份由固定布局检查。"""
    cancel()
    if view.reference.vertex_kind == "source" and not np.array_equal(
        records["identity_rows"], view.source_indices(start, start + len(records))
    ):
        raise InvalidRequestError("采样诊断原始行号与保存点云不一致")


@contextmanager
def prepare_sampling(runtime, reference, result, *, mode, chunk_bytes, cancel):
    """冻结同次诊断，逐点证据不依赖调试捕获，也不伪装成有效边界。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _Chunks, _blob

    if (
        mode != "derived"
        or CloudReference.model_validate_json(result.candidates.cloud_json) != reference
    ):
        raise InvalidRequestError("采样诊断需要同一完整点云的派生保存")
    evidence = SamplingEvidence(
        parameters=SamplingBoundarySettings.model_validate_json(
            result.candidates.settings_json
        ),
        input_count=reference.point_count,
        vertex_kind=reference.vertex_kind,
        candidate_count=result.candidates.candidate_count,
    )
    rows = min(
        runtime.policy.chunk_rows,
        chunk_bytes // 19,
        runtime.policy.max_working_bytes // 64,
    )
    if rows < 1:
        raise InvalidRequestError("采样诊断保存预算不足一个完整记录")
    with result.borrow(runtime) as (data, facts), runtime.borrow(reference) as view:
        arrays = {**data, "context": facts["context"]}
        expected = {"logical_rows", *SAMPLING_DTYPE.names}
        if set(arrays) != expected:
            raise InvalidRequestError("采样诊断数组不完整")
        for name, array in arrays.items():
            dtype = np.dtype("<u8") if name == "logical_rows" else SAMPLING_DTYPE[name]
            if array.shape != (reference.point_count, 1) or array.dtype != dtype:
                raise InvalidRequestError("采样诊断数组类型或长度不一致")

        def chunks():
            """同一只读 owner 二次流式遍历，第一遍摘要、第二遍原子提交。"""
            candidates = 0
            for start in range(0, reference.point_count, rows):
                cancel()
                stop = min(reference.point_count, start + rows)
                if not np.array_equal(
                    data["logical_rows"][start:stop, 0], np.arange(start, stop)
                ):
                    raise InvalidRequestError("采样诊断逻辑行号不连续")
                records = np.empty(stop - start, dtype=SAMPLING_DTYPE)
                for name in SAMPLING_DTYPE.names:
                    records[name] = arrays[name][start:stop, 0]
                validate_records(
                    records,
                    evidence,
                    runtime.source_point_count(reference),
                    start=start,
                )
                _check_identities(view, records, start, cancel)
                candidates += int(records["candidate"].sum())
                yield records.tobytes()
            if candidates != evidence.candidate_count:
                raise InvalidRequestError("采样诊断候选数量不一致")

        blob = _blob("sampling", "sampling.bin", chunks())
        yield evidence, blob, _Chunks(chunks())


def read_sampling(runtime, reference, *, document, service, project_id, policy, cancel):
    """按原始证据恢复并绑定当前云；不重新运行分类或接续历史依赖。"""
    from custom_nodes.metrology3d_nodes.shared.cloud_assets import _fill

    if (
        service.read(document.reference, project_id=project_id) != document
        or reference.source.kind != "asset"
        or reference.source.reference != document.reference
    ):
        raise InvalidRequestError("采样诊断与读取资产身份不一致")
    asset = document.content.point_cloud
    evidence = asset.sampling
    if evidence is None:
        return None
    chunk = min(
        policy.chunk_bytes, runtime.policy.chunk_bytes, runtime.policy.max_working_bytes
    )
    rows = min(
        runtime.policy.chunk_rows, chunk // 19, runtime.policy.max_working_bytes // 64
    )
    array_bytes = evidence.input_count * 27
    if (
        rows < 1
        or evidence.byte_length() > policy.max_asset_bytes
        or array_bytes > runtime.policy.max_decoded_bytes
    ):
        raise InvalidRequestError("采样诊断超过显式读取容量")
    arrays, owner = {}, None
    key = ("sampling-diagnostic", uuid4().hex)
    with runtime.producing(), runtime.borrow(reference) as view:
        reservation = runtime.budget.reserve(array_bytes)
        try:
            arrays["logical_rows"] = np.arange(
                evidence.input_count, dtype="<u8"
            ).reshape(-1, 1)
            for name in SAMPLING_DTYPE.names:
                cancel()
                arrays[name] = np.empty(
                    (evidence.input_count, 1), dtype=SAMPLING_DTYPE[name]
                )
            blob = next(b for b in asset.blobs if b.role == "sampling")
            with service.storage.open_read_snapshot(
                cloud_blob_key(service, document.reference, blob)
            ) as snapshot:
                stream = CheckedBlobStream(snapshot.stream, blob, cancel, asset)
                for start in range(0, evidence.input_count, rows):
                    cancel()
                    stop = min(evidence.input_count, start + rows)
                    records = np.empty(stop - start, dtype=SAMPLING_DTYPE)
                    _fill(stream, records, chunk, cancel)
                    _check_identities(view, records, start, cancel)
                    for name in SAMPLING_DTYPE.names:
                        arrays[name][start:stop, 0] = records[name]
                if stream.read(1):
                    raise InvalidRequestError("采样诊断含多余字节")
            owner = OwnedCloudArrays(arrays, reservation)
            arrays.clear()
            runtime.storage_scope.register(key, owner, lambda value: value.close())
            cancel()
            candidates = SamplingCandidates(
                reference.model_dump_json(),
                evidence.parameters.model_dump_json(),
                owner,
                key,
                evidence.candidate_count,
            )
            return SamplingDiagnostic(candidates, owner, key)
        except BaseException as error:
            arrays.clear()
            release_exception_frames(error)
            runtime.storage_scope.close_resource(key)
            if owner is not None:
                owner.close()
            reservation.close()
            raise
