"""WorkflowTriggerSource 控制面服务。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from backend.service.application.errors import (
    InvalidRequestError,
    ResourceNotFoundError,
    ServiceConfigurationError,
    ServiceError,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork

if TYPE_CHECKING:
    from backend.service.application.workflows.trigger_sources.trigger_source_supervisor import (
        TriggerSourceSupervisor,
    )


_TRIGGER_KINDS = {
    "plc-register",
    "mqtt-topic",
    "zeromq-topic",
    "grpc-method",
    "io-change",
    "sensor-read",
    "schedule",
    "webhook",
    "http-api",
}
_SUBMIT_MODES = {"sync", "async"}
_ACK_POLICIES = {
    "ack-after-received",
    "ack-after-run-created",
    "ack-after-run-finished",
}
_RESULT_MODES = {"sync-reply", "accepted-then-query", "async-report", "event-only"}


@dataclass(frozen=True)
class WorkflowTriggerSourceCreateRequest:
    """描述创建 WorkflowTriggerSource 的请求。

    字段：
    - trigger_source_id：触发源 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - trigger_kind：触发类型。
    - workflow_runtime_id：绑定的 WorkflowAppRuntime id。
    - submit_mode：提交模式，sync 或 async。
    - enabled：创建后是否标记为启用。
    - transport_config：协议连接配置。
    - match_rule：触发匹配、过滤或去抖规则。
    - input_binding_mapping：事件到 input binding 的映射。
    - result_mapping：workflow 输出到协议回执的映射。
    - default_execution_metadata：默认执行元数据。
    - ack_policy：接收确认策略。
    - result_mode：结果回执模式。
    - reply_timeout_seconds：同步回执超时秒数。
    - debounce_window_ms：去抖窗口毫秒数。
    - idempotency_key_path：幂等键来源路径。
    - metadata：附加元数据。
    """

    trigger_source_id: str
    project_id: str
    display_name: str
    trigger_kind: str
    workflow_runtime_id: str
    submit_mode: str = "async"
    enabled: bool = False
    transport_config: dict[str, object] | None = None
    match_rule: dict[str, object] | None = None
    input_binding_mapping: dict[str, object] | None = None
    result_mapping: dict[str, object] | None = None
    default_execution_metadata: dict[str, object] | None = None
    ack_policy: str = "ack-after-run-created"
    result_mode: str = "accepted-then-query"
    reply_timeout_seconds: int | None = None
    debounce_window_ms: int | None = None
    idempotency_key_path: str | None = None
    metadata: dict[str, object] | None = None


class WorkflowTriggerSourceService:
    """封装 WorkflowTriggerSource 的创建、查询和启停控制。"""

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        trigger_source_supervisor: "TriggerSourceSupervisor | None" = None,
    ) -> None:
        """初始化 WorkflowTriggerSourceService。

        参数：
        - session_factory：数据库 SessionFactory。
        - trigger_source_supervisor：可选的 TriggerSource 运行期 supervisor。
        """

        self.session_factory = session_factory
        self.trigger_source_supervisor = trigger_source_supervisor

    def create_trigger_source(
        self,
        request: WorkflowTriggerSourceCreateRequest,
        *,
        created_by: str | None,
    ) -> WorkflowTriggerSource:
        """创建一条 WorkflowTriggerSource。"""

        normalized_request = self._normalize_create_request(request)
        with self._open_unit_of_work() as unit_of_work:
            existing_trigger_source = (
                unit_of_work.workflow_trigger_sources.get_trigger_source(
                    normalized_request.trigger_source_id
                )
            )
            if existing_trigger_source is not None:
                raise InvalidRequestError(
                    "trigger_source_id 已存在",
                    details={"trigger_source_id": normalized_request.trigger_source_id},
                )
            workflow_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                normalized_request.workflow_runtime_id
            )
            if workflow_runtime is None:
                raise ResourceNotFoundError(
                    "绑定的 WorkflowAppRuntime 不存在",
                    details={
                        "workflow_runtime_id": normalized_request.workflow_runtime_id
                    },
                )
            if workflow_runtime.project_id != normalized_request.project_id:
                raise InvalidRequestError(
                    "TriggerSource 与 WorkflowAppRuntime 不属于同一 Project",
                    details={
                        "project_id": normalized_request.project_id,
                        "workflow_runtime_project_id": workflow_runtime.project_id,
                    },
                )

            now = _now_isoformat()
            desired_state = "running" if normalized_request.enabled else "stopped"
            trigger_source = WorkflowTriggerSource(
                trigger_source_id=normalized_request.trigger_source_id,
                project_id=normalized_request.project_id,
                display_name=normalized_request.display_name,
                trigger_kind=normalized_request.trigger_kind,
                workflow_runtime_id=normalized_request.workflow_runtime_id,
                submit_mode=normalized_request.submit_mode,
                enabled=normalized_request.enabled,
                desired_state=desired_state,
                observed_state="stopped",
                transport_config=dict(normalized_request.transport_config or {}),
                match_rule=dict(normalized_request.match_rule or {}),
                input_binding_mapping=dict(
                    normalized_request.input_binding_mapping or {}
                ),
                result_mapping=dict(normalized_request.result_mapping or {}),
                default_execution_metadata=dict(
                    normalized_request.default_execution_metadata or {}
                ),
                ack_policy=normalized_request.ack_policy,
                result_mode=normalized_request.result_mode,
                reply_timeout_seconds=normalized_request.reply_timeout_seconds,
                debounce_window_ms=normalized_request.debounce_window_ms,
                idempotency_key_path=normalized_request.idempotency_key_path,
                health_summary=_build_adapter_pending_health_summary(),
                metadata=dict(normalized_request.metadata or {}),
                created_at=now,
                updated_at=now,
                created_by=_normalize_optional_str(created_by),
            )
            unit_of_work.workflow_trigger_sources.save_trigger_source(trigger_source)
            unit_of_work.commit()
        return trigger_source

    def list_trigger_sources(
        self, *, project_id: str
    ) -> tuple[WorkflowTriggerSource, ...]:
        """按 Project id 列出 WorkflowTriggerSource。"""

        normalized_project_id = _require_stripped_text(project_id, "project_id")
        with self._open_unit_of_work() as unit_of_work:
            return unit_of_work.workflow_trigger_sources.list_trigger_sources(
                normalized_project_id
            )

    def get_trigger_source(self, trigger_source_id: str) -> WorkflowTriggerSource:
        """按 id 读取一条 WorkflowTriggerSource。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._open_unit_of_work() as unit_of_work:
            trigger_source = unit_of_work.workflow_trigger_sources.get_trigger_source(
                normalized_trigger_source_id
            )
        if trigger_source is None:
            raise ResourceNotFoundError(
                "请求的 WorkflowTriggerSource 不存在",
                details={"trigger_source_id": normalized_trigger_source_id},
            )
        return trigger_source

    def enable_trigger_source(self, trigger_source_id: str) -> WorkflowTriggerSource:
        """启用一条 WorkflowTriggerSource。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._open_unit_of_work() as unit_of_work:
            trigger_source = unit_of_work.workflow_trigger_sources.get_trigger_source(
                normalized_trigger_source_id
            )
            if trigger_source is None:
                raise ResourceNotFoundError(
                    "请求的 WorkflowTriggerSource 不存在",
                    details={"trigger_source_id": normalized_trigger_source_id},
                )
            workflow_runtime = unit_of_work.workflow_runtime.get_workflow_app_runtime(
                trigger_source.workflow_runtime_id
            )
            if workflow_runtime is None:
                raise ResourceNotFoundError(
                    "绑定的 WorkflowAppRuntime 不存在",
                    details={"workflow_runtime_id": trigger_source.workflow_runtime_id},
                )
            if workflow_runtime.observed_state != "running":
                raise InvalidRequestError(
                    "启用 TriggerSource 前必须先启动绑定的 WorkflowAppRuntime",
                    details={
                        "trigger_source_id": normalized_trigger_source_id,
                        "workflow_runtime_id": workflow_runtime.workflow_runtime_id,
                        "observed_state": workflow_runtime.observed_state,
                    },
                )
            updated_source = replace(
                trigger_source,
                enabled=True,
                desired_state="running",
                observed_state="stopped",
                last_error=None,
                health_summary=_build_adapter_pending_health_summary(),
                updated_at=_now_isoformat(),
            )
            unit_of_work.workflow_trigger_sources.save_trigger_source(updated_source)
            unit_of_work.commit()
        return self._start_trigger_source_if_supported(
            updated_source,
            raise_on_error=True,
        )

    def disable_trigger_source(self, trigger_source_id: str) -> WorkflowTriggerSource:
        """停用一条 WorkflowTriggerSource。"""

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._open_unit_of_work() as unit_of_work:
            trigger_source = unit_of_work.workflow_trigger_sources.get_trigger_source(
                normalized_trigger_source_id
            )
            if trigger_source is None:
                raise ResourceNotFoundError(
                    "请求的 WorkflowTriggerSource 不存在",
                    details={"trigger_source_id": normalized_trigger_source_id},
                )
            updated_source = replace(
                trigger_source,
                enabled=False,
                desired_state="stopped",
                observed_state="stopped",
                health_summary=_build_adapter_pending_health_summary(),
                updated_at=_now_isoformat(),
            )
            unit_of_work.workflow_trigger_sources.save_trigger_source(updated_source)
            unit_of_work.commit()
        return self._stop_trigger_source_if_supported(updated_source)

    def delete_trigger_source(self, trigger_source_id: str) -> None:
        """删除一条 WorkflowTriggerSource。

        参数：
        - trigger_source_id：目标 TriggerSource id。
        """

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._open_unit_of_work() as unit_of_work:
            trigger_source = unit_of_work.workflow_trigger_sources.get_trigger_source(
                normalized_trigger_source_id
            )
            if trigger_source is None:
                raise ResourceNotFoundError(
                    "请求的 WorkflowTriggerSource 不存在",
                    details={"trigger_source_id": normalized_trigger_source_id},
                )
            self._stop_trigger_source_runtime_if_supported(trigger_source)
            deleted = unit_of_work.workflow_trigger_sources.delete_trigger_source(
                normalized_trigger_source_id
            )
            if not deleted:
                raise ResourceNotFoundError(
                    "请求的 WorkflowTriggerSource 不存在",
                    details={"trigger_source_id": normalized_trigger_source_id},
                )
            unit_of_work.commit()

    def get_trigger_source_health(self, trigger_source_id: str) -> dict[str, object]:
        """读取 TriggerSource 的健康摘要。"""

        trigger_source = self.get_trigger_source(trigger_source_id)
        live_health_summary = self._build_live_health_summary(trigger_source)
        health_summary = live_health_summary or dict(trigger_source.health_summary)
        observed_state = trigger_source.observed_state
        if (
            live_health_summary is not None
            and live_health_summary["adapter_running"] is True
        ):
            observed_state = "running"
        return {
            "trigger_source_id": trigger_source.trigger_source_id,
            "enabled": trigger_source.enabled,
            "desired_state": trigger_source.desired_state,
            "observed_state": observed_state,
            "last_triggered_at": trigger_source.last_triggered_at,
            "last_error": trigger_source.last_error,
            "health_summary": health_summary,
        }

    def start_enabled_trigger_sources(self) -> dict[str, object]:
        """启动当前数据库中 enabled 的 TriggerSource。

        返回：
        - dict[str, object]：启动恢复摘要。
        """

        with self._open_unit_of_work() as unit_of_work:
            trigger_sources = (
                unit_of_work.workflow_trigger_sources.list_enabled_trigger_sources()
            )
        started_count = 0
        skipped_count = 0
        failed_count = 0
        for trigger_source in trigger_sources:
            if not self._is_adapter_supported(trigger_source):
                skipped_count += 1
                continue
            updated_source = self._start_trigger_source_if_supported(
                trigger_source,
                raise_on_error=False,
            )
            if updated_source.observed_state == "running":
                started_count += 1
            elif updated_source.observed_state == "failed":
                failed_count += 1
        return {
            "supervisor_configured": self.trigger_source_supervisor is not None,
            "total_enabled": len(trigger_sources),
            "started_count": started_count,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
        }

    def _normalize_create_request(
        self,
        request: WorkflowTriggerSourceCreateRequest,
    ) -> WorkflowTriggerSourceCreateRequest:
        """规范化创建请求并校验基础字段。"""

        trigger_source_id = _require_stripped_text(
            request.trigger_source_id, "trigger_source_id"
        )
        project_id = _require_stripped_text(request.project_id, "project_id")
        display_name = _require_stripped_text(request.display_name, "display_name")
        trigger_kind = _require_choice(
            request.trigger_kind, "trigger_kind", _TRIGGER_KINDS
        )
        workflow_runtime_id = _require_stripped_text(
            request.workflow_runtime_id, "workflow_runtime_id"
        )
        submit_mode = _require_choice(request.submit_mode, "submit_mode", _SUBMIT_MODES)
        ack_policy = _require_choice(request.ack_policy, "ack_policy", _ACK_POLICIES)
        result_mode = _require_choice(request.result_mode, "result_mode", _RESULT_MODES)
        if (
            request.reply_timeout_seconds is not None
            and request.reply_timeout_seconds <= 0
        ):
            raise InvalidRequestError("reply_timeout_seconds 必须大于 0")
        if request.debounce_window_ms is not None and request.debounce_window_ms < 0:
            raise InvalidRequestError("debounce_window_ms 不能小于 0")
        idempotency_key_path = _normalize_optional_str(request.idempotency_key_path)
        if not isinstance(request.transport_config or {}, dict):
            raise InvalidRequestError("transport_config 必须是对象")
        if not isinstance(request.match_rule or {}, dict):
            raise InvalidRequestError("match_rule 必须是对象")
        if not isinstance(request.input_binding_mapping or {}, dict):
            raise InvalidRequestError("input_binding_mapping 必须是对象")
        if not isinstance(request.result_mapping or {}, dict):
            raise InvalidRequestError("result_mapping 必须是对象")
        if not isinstance(request.default_execution_metadata or {}, dict):
            raise InvalidRequestError("default_execution_metadata 必须是对象")
        if not isinstance(request.metadata or {}, dict):
            raise InvalidRequestError("metadata 必须是对象")
        return WorkflowTriggerSourceCreateRequest(
            trigger_source_id=trigger_source_id,
            project_id=project_id,
            display_name=display_name,
            trigger_kind=trigger_kind,
            workflow_runtime_id=workflow_runtime_id,
            submit_mode=submit_mode,
            enabled=bool(request.enabled),
            transport_config=dict(request.transport_config or {}),
            match_rule=dict(request.match_rule or {}),
            input_binding_mapping=dict(request.input_binding_mapping or {}),
            result_mapping=dict(request.result_mapping or {}),
            default_execution_metadata=dict(request.default_execution_metadata or {}),
            ack_policy=ack_policy,
            result_mode=result_mode,
            reply_timeout_seconds=request.reply_timeout_seconds,
            debounce_window_ms=request.debounce_window_ms,
            idempotency_key_path=idempotency_key_path,
            metadata=dict(request.metadata or {}),
        )

    def _start_trigger_source_if_supported(
        self,
        trigger_source: WorkflowTriggerSource,
        *,
        raise_on_error: bool,
    ) -> WorkflowTriggerSource:
        """在已配置 adapter 时启动 TriggerSource。"""

        supervisor = self.trigger_source_supervisor
        if supervisor is None or not supervisor.supports_trigger_source(trigger_source):
            return trigger_source
        try:
            if not supervisor.is_trigger_source_managed(
                trigger_source.trigger_source_id
            ):
                supervisor.start_trigger_source(trigger_source)
            health_summary = _build_supervisor_health_summary(
                supervisor_health=supervisor.get_health(
                    trigger_source.trigger_source_id
                ),
                adapter_configured=True,
            )
            updated_source = replace(
                trigger_source,
                observed_state="running",
                last_error=None,
                health_summary=health_summary,
                updated_at=_now_isoformat(),
            )
            self._save_trigger_source(updated_source)
            return updated_source
        except ServiceError as error:
            failed_source = self._mark_trigger_source_failed(
                trigger_source,
                error_message=error.message,
                error_details={"error_code": error.code, **dict(error.details)},
            )
            if raise_on_error:
                raise
            return failed_source
        except Exception as error:
            failed_source = self._mark_trigger_source_failed(
                trigger_source,
                error_message=error.__class__.__name__,
                error_details={"error_type": error.__class__.__name__},
            )
            if raise_on_error:
                raise ServiceConfigurationError(
                    "启动 TriggerSource adapter 失败",
                    details={
                        "trigger_source_id": trigger_source.trigger_source_id,
                        "error_type": error.__class__.__name__,
                    },
                ) from error
            return failed_source

    def _stop_trigger_source_if_supported(
        self,
        trigger_source: WorkflowTriggerSource,
    ) -> WorkflowTriggerSource:
        """在已配置 adapter 时停止 TriggerSource。"""

        supervisor = self.trigger_source_supervisor
        if supervisor is None or not supervisor.supports_trigger_source(trigger_source):
            return trigger_source
        supervisor.stop_trigger_source(trigger_source.trigger_source_id)
        health_summary = _build_supervisor_health_summary(
            supervisor_health=supervisor.get_health(trigger_source.trigger_source_id),
            adapter_configured=True,
        )
        updated_source = replace(
            trigger_source,
            observed_state="stopped",
            health_summary=health_summary,
            updated_at=_now_isoformat(),
        )
        self._save_trigger_source(updated_source)
        return updated_source

    def _stop_trigger_source_runtime_if_supported(
        self,
        trigger_source: WorkflowTriggerSource,
    ) -> None:
        """在删除前停止已配置 adapter 的内存监听。

        参数：
        - trigger_source：准备删除的 TriggerSource 配置快照。
        """

        supervisor = self.trigger_source_supervisor
        if supervisor is None or not supervisor.supports_trigger_source(trigger_source):
            return
        supervisor.stop_trigger_source(trigger_source.trigger_source_id)

    def _build_live_health_summary(
        self,
        trigger_source: WorkflowTriggerSource,
    ) -> dict[str, object] | None:
        """读取 supervisor 中的 TriggerSource live health。"""

        supervisor = self.trigger_source_supervisor
        if supervisor is None or not supervisor.supports_trigger_source(trigger_source):
            return None
        return _build_supervisor_health_summary(
            supervisor_health=supervisor.get_health(trigger_source.trigger_source_id),
            adapter_configured=True,
        )

    def _is_adapter_supported(self, trigger_source: WorkflowTriggerSource) -> bool:
        """判断当前进程是否支持指定 TriggerSource 的 adapter。"""

        supervisor = self.trigger_source_supervisor
        return supervisor is not None and supervisor.supports_trigger_source(
            trigger_source
        )

    def _mark_trigger_source_failed(
        self,
        trigger_source: WorkflowTriggerSource,
        *,
        error_message: str,
        error_details: dict[str, object],
    ) -> WorkflowTriggerSource:
        """把 TriggerSource 标记为 adapter 启动失败。"""

        updated_source = replace(
            trigger_source,
            observed_state="failed",
            last_error=error_message,
            health_summary=_build_adapter_failed_health_summary(error_details),
            updated_at=_now_isoformat(),
        )
        self._save_trigger_source(updated_source)
        return updated_source

    def _save_trigger_source(self, trigger_source: WorkflowTriggerSource) -> None:
        """保存一条 TriggerSource 最新状态。"""

        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.workflow_trigger_sources.save_trigger_source(trigger_source)
            unit_of_work.commit()

    @contextmanager
    def _open_unit_of_work(self) -> Iterator[SqlAlchemyUnitOfWork]:
        """创建当前服务使用的 UnitOfWork。"""

        unit_of_work = SqlAlchemyUnitOfWork(self.session_factory.create_session())
        try:
            yield unit_of_work
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.close()


def _build_adapter_pending_health_summary() -> dict[str, object]:
    """构造 adapter 尚未接入时的健康摘要。"""

    return {
        "adapter_configured": False,
        "adapter_running": False,
        "request_count": 0,
        "request_count_rollover_count": 0,
        "success_count": 0,
        "success_count_rollover_count": 0,
        "error_count": 0,
        "error_count_rollover_count": 0,
        "timeout_count": 0,
        "timeout_count_rollover_count": 0,
        "recent_error": None,
    }


def _build_supervisor_health_summary(
    *,
    supervisor_health: dict[str, object],
    adapter_configured: bool,
) -> dict[str, object]:
    """把 supervisor live health 转换为持久化 health_summary。"""

    adapter_health = supervisor_health.get("adapter_health")
    if not isinstance(adapter_health, dict):
        adapter_health = {}
    return {
        "adapter_configured": adapter_configured,
        "adapter_running": bool(adapter_health.get("running")),
        "request_count": _as_int(supervisor_health.get("request_count")),
        "request_count_rollover_count": _as_int(
            supervisor_health.get("request_count_rollover_count")
        ),
        "success_count": _as_int(supervisor_health.get("success_count")),
        "success_count_rollover_count": _as_int(
            supervisor_health.get("success_count_rollover_count")
        ),
        "error_count": _as_int(supervisor_health.get("error_count")),
        "error_count_rollover_count": _as_int(
            supervisor_health.get("error_count_rollover_count")
        ),
        "timeout_count": _as_int(supervisor_health.get("timeout_count")),
        "timeout_count_rollover_count": _as_int(
            supervisor_health.get("timeout_count_rollover_count")
        ),
        "recent_error": supervisor_health.get("last_error")
        or adapter_health.get("last_error"),
        "supervisor": dict(supervisor_health),
    }


def _build_adapter_failed_health_summary(
    error_details: dict[str, object],
) -> dict[str, object]:
    """构造 adapter 启动失败时的 health_summary。"""

    return {
        "adapter_configured": True,
        "adapter_running": False,
        "request_count": 0,
        "request_count_rollover_count": 0,
        "success_count": 0,
        "success_count_rollover_count": 0,
        "error_count": 1,
        "error_count_rollover_count": 0,
        "timeout_count": 0,
        "timeout_count_rollover_count": 0,
        "recent_error": dict(error_details),
    }


def _as_int(value: object) -> int:
    """把 health 中的计数值转换为非负整数。"""

    try:
        normalized_value = int(value) if value is not None else 0
    except (TypeError, ValueError):
        return 0
    return max(0, normalized_value)


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value


def _require_choice(value: str, field_name: str, allowed_values: set[str]) -> str:
    """校验字符串字段属于允许集合。"""

    normalized_value = _require_stripped_text(value, field_name)
    if normalized_value not in allowed_values:
        raise InvalidRequestError(
            f"{field_name} 不支持当前取值",
            details={
                field_name: normalized_value,
                "allowed_values": sorted(allowed_values),
            },
        )
    return normalized_value


def _normalize_optional_str(value: str | None) -> str | None:
    """规范化可选字符串。"""

    if value is None:
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
