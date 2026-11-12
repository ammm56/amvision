"""边诊断复用 CloudRuntime 的 Scope；引用不拥有另一份数组或跨运行缓存。"""

from contextlib import ExitStack
from uuid import uuid4

from backend.contracts.workflows.edge_reference import EdgeDiagnosticReference
from backend.contracts.workflows.edge_evidence import EdgeEvidence
from backend.contracts.workflows.edge_sampling_evidence import SamplingEvidence
from backend.contracts.workflows.edge3d import SamplingBoundarySettings
from backend.contracts.workflows.point_cloud_runtime import CloudReference
from backend.service.application.errors import InvalidRequestError
from custom_nodes.metrology3d_nodes.shared.edge_assets import (
    StoredEdgeResult,
    _metadata,
)
from custom_nodes.metrology3d_nodes.shared.edge_sampling_context import (
    SamplingDiagnostic,
)
from custom_nodes.metrology3d_nodes.shared.height_map_reference import (
    resolve_height_map,
)


def publish_edge_diagnostic(
    runtime, cloud, result=None, *, sampling_result=None, height_map=None
):
    """登记同次不可变快照；恢复时仅重绑报告身份，不重算质量或算法。"""
    with runtime.producing(), runtime.borrow(cloud), ExitStack() as stack:
        edge = sampling = None
        if sampling_result is not None:
            if not isinstance(sampling_result, SamplingDiagnostic):
                raise InvalidRequestError("采样诊断结果类型错误")
            parent = CloudReference.model_validate_json(
                sampling_result.candidates.cloud_json
            )
            if parent != cloud:
                raise InvalidRequestError("采样诊断不属于当前完整点云")
            stack.enter_context(sampling_result.borrow(runtime))
            sampling = SamplingEvidence(
                parameters=SamplingBoundarySettings.model_validate_json(
                    sampling_result.candidates.settings_json
                ),
                input_count=cloud.point_count,
                vertex_kind=cloud.vertex_kind,
                candidate_count=sampling_result.candidates.candidate_count,
            )
        if isinstance(result, StoredEdgeResult):
            parent = CloudReference.model_validate_json(result.cloud_json)
            stack.enter_context(result.borrow(runtime))
            edge = EdgeEvidence.model_validate_json(result.evidence_json).model_copy(
                update={"reports": result.reports(cloud)}
            )
        elif result is not None:
            objects = (
                result.chains.pairs.candidates,
                result.chains.pairs,
                result.chains,
                result,
            )
            groups = {
                name: stack.enter_context(value.borrow(runtime))
                for name, value in zip(
                    ("candidates", "pairs", "chains", "targets"), objects
                )
            }
            edge = _metadata(cloud, result, groups)
            parent = cloud  # _metadata 已检查真实候选的完整父云。
        else:
            parent = cloud
        if parent != cloud:
            raise InvalidRequestError("边诊断不属于当前完整点云")
        if height_map is not None:
            if edge is None or edge.method.kind != "height-jump":
                raise InvalidRequestError("只有高度实测边可携带高度图")
            resolve_height_map(runtime, height_map, cloud=cloud)
            if isinstance(result, StoredEdgeResult):
                if result.height_evidence_json != height_map.evidence.model_dump_json():
                    raise InvalidRequestError("恢复边诊断与指定高度图证据不一致")
            else:
                from backend.contracts.workflows.height_map_reference import (
                    HeightMapReference,
                )

                actual = HeightMapReference.model_validate_json(
                    result.chains.pairs.candidates.height_map_json
                )
                if actual != height_map:
                    raise InvalidRequestError("边诊断不是指定高度图的同次计算")
        ref = EdgeDiagnosticReference(
            run_id=runtime.run_id,
            diagnostic_id=uuid4().hex,
            cloud=cloud,
            edge=edge,
            sampling=sampling,
            height_map=height_map,
        )
        runtime.storage_scope.register(
            ("edge-diagnostic-result", ref.diagnostic_id),
            (ref.model_dump_json(), result, sampling_result),
            lambda value: None,
        )
        return ref


def resolve_edge_diagnostic(runtime, value, *, cloud=None):
    """未知、被修改、错分支及已释放的引用均拒绝，不创建替代资源。"""
    ref = EdgeDiagnosticReference.model_validate(value)
    if ref.run_id != runtime.run_id or (cloud is not None and ref.cloud != cloud):
        raise InvalidRequestError("边诊断不属于当前运行或完整点云")

    def missing():
        raise InvalidRequestError("边诊断引用失效")

    with runtime.producing():
        encoded, result, sampling = runtime.storage_scope.get_or_create(
            ("edge-diagnostic-result", ref.diagnostic_id), missing, lambda value: None
        )
        if encoded != ref.model_dump_json():
            raise InvalidRequestError("边诊断引用内容被修改")
        for value in (result, sampling):
            if value is not None:
                with value.borrow(runtime):
                    pass
        if ref.height_map is not None:
            resolve_height_map(runtime, ref.height_map, cloud=ref.cloud)
        return ref, result, sampling
