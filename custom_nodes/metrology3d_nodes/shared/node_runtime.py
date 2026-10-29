"""节点接入现有显式 Runtime、Scope 和取消控制，不创建进程或全局点云缓存。"""

from dataclasses import dataclass
from hashlib import sha256
from pydantic import TypeAdapter
from backend.contracts.workflows.metrology import Identifier
from backend.contracts.workflows.point_cloud_runtime import (
    CloudReference,
)
from backend.contracts.workflows.point_cloud import canonical_cloud_json
from backend.service.application.errors import (
    InvalidRequestError,
    ServiceConfigurationError,
)
from backend.service.application.runtime.resource_scope import (
    get_or_create_workflow_resource_scope,
)
from backend.service.application.workflows.execution.execution_control import (
    build_node_execution_control,
)
from backend.service.application.workflows.point_cloud.runtime import get_cloud_runtime
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)


@dataclass(frozen=True)
class CloudNodeRuntime:
    """一次节点调用借用的现有运行资源，不拥有独立生命周期。"""

    runtime: object
    policy: object
    service: MeasurementResourceService
    project_id: str
    cancel: object


def require_node_runtime(request):
    """缺少显式策略时关闭能力；不从节点参数或客户端元数据猜预算。"""
    context = request.runtime_context
    if (
        not isinstance(context, WorkflowServiceNodeRuntimeContext)
        or context.point_cloud_policy is None
    ):
        raise ServiceConfigurationError("3D Metrology 未配置完整运行策略，不能执行")
    try:
        project = TypeAdapter(Identifier).validate_python(
            request.execution_metadata.get("project_id")
        )
        run_id = TypeAdapter(Identifier).validate_python(
            request.execution_metadata.get("workflow_run_id")
        )
    except ValueError as error:
        raise InvalidRequestError("点云节点缺少合法的项目或运行身份") from error
    policy = context.point_cloud_policy
    scope = get_or_create_workflow_resource_scope(request.execution_metadata)
    runtime = get_cloud_runtime(scope, run_id=run_id, policy=policy.io)
    storage = request.execution_metadata.get("dataset_storage", context.dataset_storage)
    return CloudNodeRuntime(
        runtime,
        policy,
        MeasurementResourceService(storage, cloud_policy=policy.assets()),
        project,
        build_node_execution_control(request).raise_if_cancelled_or_expired,
    )


def cloud_input(request, runtime):
    """解析闭合引用并核对当前 run；ready 引用的完整身份由运行 registry 核对。"""
    try:
        cloud = CloudReference.model_validate(request.input_values.get("cloud"))
    except ValueError as error:
        raise InvalidRequestError("cloud 输入不是合法点云引用") from error
    if cloud.run_id != runtime.run_id:
        raise InvalidRequestError("cloud 输入不属于当前运行")
    return cloud


def write_identity(request, project_id):
    """平台已有 run/node/invocation 形成提交身份，用户参数不能指定它。"""
    values = (
        project_id,
        request.execution_metadata.get("workflow_run_id"),
        request.node_id,
        request.node_invocation_id,
    )
    try:
        for value in values:
            TypeAdapter(Identifier).validate_python(value)
    except ValueError as error:
        raise InvalidRequestError("保存节点缺少完整调用身份") from error
    return sha256(canonical_cloud_json(values)).hexdigest()
