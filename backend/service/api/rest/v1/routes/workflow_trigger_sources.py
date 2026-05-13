"""workflow trigger source REST 路由。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from pydantic import BaseModel, Field

from backend.contracts.workflows import WorkflowTriggerSourceContract
from backend.service.api.deps.auth import AuthenticatedPrincipal, require_scopes
from backend.service.application.errors import (
    PermissionDeniedError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.trigger_sources import (
    WorkflowTriggerSourceCreateRequest,
    WorkflowTriggerSourceService,
)
from backend.service.application.workflows.trigger_sources.trigger_source_supervisor import (
    TriggerSourceSupervisor,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.db.session import SessionFactory


workflow_trigger_sources_router = APIRouter(
    prefix="/workflows/trigger-sources", tags=["workflow-trigger-sources"]
)


class WorkflowTriggerSourceCreateRequestBody(BaseModel):
    """描述 WorkflowTriggerSource 创建请求体。

    字段：
    - trigger_source_id：触发源 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - trigger_kind：触发类型。
    - workflow_runtime_id：绑定的 WorkflowAppRuntime id。
    - submit_mode：提交模式。
    - enabled：创建后是否启用。
    - transport_config：协议连接配置。
    - match_rule：触发匹配规则。
    - input_binding_mapping：输入绑定映射。
    - result_mapping：结果回执映射。
    - default_execution_metadata：默认执行元数据。
    - ack_policy：接收确认策略。
    - result_mode：结果回执模式。
    - reply_timeout_seconds：同步回执超时秒数。
    - debounce_window_ms：去抖窗口毫秒数。
    - idempotency_key_path：幂等键来源路径。
    - metadata：附加元数据。
    """

    trigger_source_id: str = Field(description="触发源 id")
    project_id: str = Field(description="所属 Project id")
    display_name: str = Field(description="展示名称")
    trigger_kind: str = Field(description="触发类型")
    workflow_runtime_id: str = Field(description="绑定的 WorkflowAppRuntime id")
    submit_mode: str = Field(default="async", description="提交模式")
    enabled: bool = Field(default=False, description="创建后是否启用")
    transport_config: dict[str, object] = Field(
        default_factory=dict, description="协议连接配置"
    )
    match_rule: dict[str, object] = Field(
        default_factory=dict, description="触发匹配规则"
    )
    input_binding_mapping: dict[str, object] = Field(
        default_factory=dict, description="输入绑定映射"
    )
    result_mapping: dict[str, object] = Field(
        default_factory=dict, description="结果回执映射"
    )
    default_execution_metadata: dict[str, object] = Field(
        default_factory=dict, description="默认执行元数据"
    )
    ack_policy: str = Field(default="ack-after-run-created", description="接收确认策略")
    result_mode: str = Field(default="accepted-then-query", description="结果回执模式")
    reply_timeout_seconds: int | None = Field(
        default=None, description="同步回执超时秒数"
    )
    debounce_window_ms: int | None = Field(default=None, description="去抖窗口毫秒数")
    idempotency_key_path: str | None = Field(default=None, description="幂等键来源路径")
    metadata: dict[str, object] = Field(default_factory=dict, description="附加元数据")


@workflow_trigger_sources_router.post(
    "",
    response_model=WorkflowTriggerSourceContract,
    status_code=status.HTTP_201_CREATED,
)
def create_workflow_trigger_source(
    body: WorkflowTriggerSourceCreateRequestBody,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowTriggerSourceContract:
    """创建一条 WorkflowTriggerSource。"""

    _ensure_project_visible(principal=principal, project_id=body.project_id)
    trigger_source = _build_trigger_source_service(request).create_trigger_source(
        WorkflowTriggerSourceCreateRequest(
            trigger_source_id=body.trigger_source_id,
            project_id=body.project_id,
            display_name=body.display_name,
            trigger_kind=body.trigger_kind,
            workflow_runtime_id=body.workflow_runtime_id,
            submit_mode=body.submit_mode,
            enabled=body.enabled,
            transport_config=dict(body.transport_config),
            match_rule=dict(body.match_rule),
            input_binding_mapping=dict(body.input_binding_mapping),
            result_mapping=dict(body.result_mapping),
            default_execution_metadata=dict(body.default_execution_metadata),
            ack_policy=body.ack_policy,
            result_mode=body.result_mode,
            reply_timeout_seconds=body.reply_timeout_seconds,
            debounce_window_ms=body.debounce_window_ms,
            idempotency_key_path=body.idempotency_key_path,
            metadata=dict(body.metadata),
        ),
        created_by=principal.principal_id,
    )
    return _build_trigger_source_contract(trigger_source)


@workflow_trigger_sources_router.get(
    "", response_model=list[WorkflowTriggerSourceContract]
)
def list_workflow_trigger_sources(
    project_id: Annotated[str, Query(description="所属 Project id")],
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> list[WorkflowTriggerSourceContract]:
    """按 Project id 列出 WorkflowTriggerSource。"""

    _ensure_project_visible(principal=principal, project_id=project_id)
    trigger_sources = _build_trigger_source_service(request).list_trigger_sources(
        project_id=project_id
    )
    return [_build_trigger_source_contract(item) for item in trigger_sources]


@workflow_trigger_sources_router.get(
    "/{trigger_source_id}", response_model=WorkflowTriggerSourceContract
)
def get_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> WorkflowTriggerSourceContract:
    """读取一条 WorkflowTriggerSource。"""

    trigger_source = _build_trigger_source_service(request).get_trigger_source(
        trigger_source_id
    )
    _ensure_project_visible(principal=principal, project_id=trigger_source.project_id)
    return _build_trigger_source_contract(trigger_source)


@workflow_trigger_sources_router.post(
    "/{trigger_source_id}/enable", response_model=WorkflowTriggerSourceContract
)
def enable_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowTriggerSourceContract:
    """启用一条 WorkflowTriggerSource。"""

    current_trigger_source = _build_trigger_source_service(request).get_trigger_source(
        trigger_source_id
    )
    _ensure_project_visible(
        principal=principal, project_id=current_trigger_source.project_id
    )
    trigger_source = _build_trigger_source_service(request).enable_trigger_source(
        trigger_source_id
    )
    return _build_trigger_source_contract(trigger_source)


@workflow_trigger_sources_router.post(
    "/{trigger_source_id}/disable", response_model=WorkflowTriggerSourceContract
)
def disable_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> WorkflowTriggerSourceContract:
    """停用一条 WorkflowTriggerSource。"""

    current_trigger_source = _build_trigger_source_service(request).get_trigger_source(
        trigger_source_id
    )
    _ensure_project_visible(
        principal=principal, project_id=current_trigger_source.project_id
    )
    trigger_source = _build_trigger_source_service(request).disable_trigger_source(
        trigger_source_id
    )
    return _build_trigger_source_contract(trigger_source)


@workflow_trigger_sources_router.delete(
    "/{trigger_source_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_workflow_trigger_source(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:write"))
    ],
) -> Response:
    """删除一条 WorkflowTriggerSource。"""

    current_trigger_source = _build_trigger_source_service(request).get_trigger_source(
        trigger_source_id
    )
    _ensure_project_visible(
        principal=principal, project_id=current_trigger_source.project_id
    )
    _build_trigger_source_service(request).delete_trigger_source(trigger_source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@workflow_trigger_sources_router.get("/{trigger_source_id}/health")
def get_workflow_trigger_source_health(
    trigger_source_id: str,
    request: Request,
    principal: Annotated[
        AuthenticatedPrincipal, Depends(require_scopes("workflows:read"))
    ],
) -> dict[str, object]:
    """读取一条 WorkflowTriggerSource 的健康摘要。"""

    trigger_source = _build_trigger_source_service(request).get_trigger_source(
        trigger_source_id
    )
    _ensure_project_visible(principal=principal, project_id=trigger_source.project_id)
    return _build_trigger_source_service(request).get_trigger_source_health(
        trigger_source_id
    )


def _build_trigger_source_service(request: Request) -> WorkflowTriggerSourceService:
    """基于 application.state 构建 WorkflowTriggerSourceService。"""

    return WorkflowTriggerSourceService(
        session_factory=_require_session_factory(request),
        trigger_source_supervisor=_read_trigger_source_supervisor(request),
    )


def _require_session_factory(request: Request) -> SessionFactory:
    """从 application.state 中读取 SessionFactory。"""

    session_factory = getattr(request.app.state, "session_factory", None)
    if not isinstance(session_factory, SessionFactory):
        raise ServiceConfigurationError("当前服务尚未完成 session_factory 装配")
    return session_factory


def _read_trigger_source_supervisor(request: Request) -> TriggerSourceSupervisor | None:
    """从 application.state 中读取 TriggerSourceSupervisor。"""

    supervisor = getattr(request.app.state, "trigger_source_supervisor", None)
    if supervisor is None:
        return None
    if not isinstance(supervisor, TriggerSourceSupervisor):
        raise ServiceConfigurationError("当前服务 trigger_source_supervisor 装配无效")
    return supervisor


def _ensure_project_visible(
    *, principal: AuthenticatedPrincipal, project_id: str
) -> None:
    """校验当前主体是否可访问指定 Project。"""

    if principal.project_ids and project_id not in principal.project_ids:
        raise PermissionDeniedError(
            "当前主体无权访问该 Project",
            details={"project_id": project_id},
        )


def _build_trigger_source_contract(
    trigger_source: WorkflowTriggerSource,
) -> WorkflowTriggerSourceContract:
    """把领域对象转换为 REST 合同。"""

    return WorkflowTriggerSourceContract(
        trigger_source_id=trigger_source.trigger_source_id,
        project_id=trigger_source.project_id,
        display_name=trigger_source.display_name,
        trigger_kind=trigger_source.trigger_kind,
        workflow_runtime_id=trigger_source.workflow_runtime_id,
        submit_mode=trigger_source.submit_mode,
        enabled=trigger_source.enabled,
        desired_state=trigger_source.desired_state,
        observed_state=trigger_source.observed_state,
        transport_config=dict(trigger_source.transport_config),
        match_rule=dict(trigger_source.match_rule),
        input_binding_mapping=dict(trigger_source.input_binding_mapping),
        result_mapping=dict(trigger_source.result_mapping)
        or {"result_binding": "workflow_result"},
        default_execution_metadata=dict(trigger_source.default_execution_metadata),
        ack_policy=trigger_source.ack_policy,
        result_mode=trigger_source.result_mode,
        reply_timeout_seconds=trigger_source.reply_timeout_seconds,
        debounce_window_ms=trigger_source.debounce_window_ms,
        idempotency_key_path=trigger_source.idempotency_key_path,
        last_triggered_at=trigger_source.last_triggered_at,
        last_error=trigger_source.last_error,
        health_summary=dict(trigger_source.health_summary),
        metadata=dict(trigger_source.metadata),
        created_at=trigger_source.created_at,
        updated_at=trigger_source.updated_at,
        created_by=trigger_source.created_by,
    )
