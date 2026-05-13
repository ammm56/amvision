"""TriggerSource 协议 adapter 生命周期监督器。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock

from backend.contracts.workflows import TriggerResultContract
from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.runtime.safe_counter import (
    SafeCounterState,
    increment_safe_counter,
    snapshot_safe_counter,
)
from backend.service.application.workflows.trigger_sources.protocol_adapter import (
    WorkflowTriggerEventHandler,
    WorkflowTriggerProtocolAdapter,
)
from backend.service.application.workflows.trigger_sources.trigger_event_normalizer import (
    RawTriggerEvent,
    TriggerEventNormalizer,
)
from backend.service.application.workflows.trigger_sources.workflow_submitter import (
    WorkflowSubmitter,
    WorkflowTriggerSubmitRequest,
)
from backend.service.domain.workflows.workflow_trigger_source_records import (
    WorkflowTriggerSource,
)


@dataclass
class _ManagedTriggerSourceState:
    """描述一个已交给 supervisor 管理的 TriggerSource 运行状态。

    字段：
    - trigger_source：当前管理的 TriggerSource 配置快照。
    - adapter_kind：承载该触发源的 adapter 类型。
    - adapter：承载该触发源的 adapter 实例。
    - request_count：已处理事件数量。
    - success_count：返回 accepted 或 succeeded 的事件数量。
    - error_count：失败事件数量。
    - timeout_count：超时事件数量。
    - last_triggered_at：最近一次事件发生时间。
    - last_error：最近错误消息。
    """

    trigger_source: WorkflowTriggerSource
    adapter_kind: str
    adapter: WorkflowTriggerProtocolAdapter
    request_count: SafeCounterState = field(default_factory=SafeCounterState)
    success_count: SafeCounterState = field(default_factory=SafeCounterState)
    error_count: SafeCounterState = field(default_factory=SafeCounterState)
    timeout_count: SafeCounterState = field(default_factory=SafeCounterState)
    last_triggered_at: str | None = None
    last_error: str | None = None


class TriggerSourceSupervisor(WorkflowTriggerEventHandler):
    """管理 TriggerSource adapter 生命周期和事件提交流程。"""

    def __init__(
        self,
        *,
        adapters: dict[str, WorkflowTriggerProtocolAdapter],
        workflow_submitter: WorkflowSubmitter,
        event_normalizer: TriggerEventNormalizer | None = None,
    ) -> None:
        """初始化 TriggerSourceSupervisor。

        参数：
        - adapters：按 trigger_kind 或 adapter_kind 索引的 adapter 映射。
        - workflow_submitter：协议中立 workflow 提交器。
        - event_normalizer：可选的 TriggerEvent 标准化器。
        """

        self.adapters = dict(adapters)
        self.workflow_submitter = workflow_submitter
        self.event_normalizer = event_normalizer or TriggerEventNormalizer()
        self._states: dict[str, _ManagedTriggerSourceState] = {}
        self._lock = RLock()

    def start_trigger_source(self, trigger_source: WorkflowTriggerSource) -> None:
        """启动一条 TriggerSource 对应的 adapter 监听。

        参数：
        - trigger_source：要启动的 TriggerSource 配置快照。
        """

        adapter = self._resolve_adapter(trigger_source)
        with self._lock:
            if trigger_source.trigger_source_id in self._states:
                raise InvalidRequestError(
                    "TriggerSource 已由 supervisor 管理",
                    details={"trigger_source_id": trigger_source.trigger_source_id},
                )
            self._states[trigger_source.trigger_source_id] = _ManagedTriggerSourceState(
                trigger_source=trigger_source,
                adapter_kind=adapter.adapter_kind,
                adapter=adapter,
            )
        try:
            adapter.start(trigger_source=trigger_source, event_handler=self)
        except Exception:
            with self._lock:
                self._states.pop(trigger_source.trigger_source_id, None)
            raise

    def stop_trigger_source(self, trigger_source_id: str) -> None:
        """停止一条 TriggerSource 对应的 adapter 监听。

        参数：
        - trigger_source_id：要停止的 TriggerSource id。
        """

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.pop(normalized_trigger_source_id, None)
        if state is None:
            return
        state.adapter.stop(trigger_source_id=normalized_trigger_source_id)

    def stop_all(self) -> None:
        """停止当前 supervisor 管理的全部 TriggerSource。"""

        with self._lock:
            trigger_source_ids = tuple(self._states.keys())
        for trigger_source_id in trigger_source_ids:
            self.stop_trigger_source(trigger_source_id)

    def supports_trigger_source(self, trigger_source: WorkflowTriggerSource) -> bool:
        """判断当前 supervisor 是否支持指定 TriggerSource 类型。

        参数：
        - trigger_source：待判断的 TriggerSource 配置快照。

        返回：
        - bool：已注册对应 adapter 时返回 True。
        """

        return trigger_source.trigger_kind in self.adapters

    def is_trigger_source_managed(self, trigger_source_id: str) -> bool:
        """判断指定 TriggerSource 是否已由 supervisor 管理。

        参数：
        - trigger_source_id：目标 TriggerSource id。

        返回：
        - bool：当前内存运行态存在时返回 True。
        """

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            return normalized_trigger_source_id in self._states

    def handle_trigger_event(
        self,
        *,
        trigger_source: WorkflowTriggerSource,
        raw_event: RawTriggerEvent,
    ) -> TriggerResultContract:
        """处理协议 adapter 送入的原始事件。

        参数：
        - trigger_source：事件所属 TriggerSource。
        - raw_event：协议 adapter 传入的原始事件。

        返回：
        - TriggerResultContract：协议中立的处理结果。
        """

        trigger_event = self.event_normalizer.normalize(trigger_source, raw_event)
        state = self._get_or_create_state(trigger_source)
        increment_safe_counter(state.request_count)
        state.last_triggered_at = trigger_event.occurred_at
        try:
            trigger_result = self.workflow_submitter.submit_event(
                WorkflowTriggerSubmitRequest(
                    trigger_source=trigger_source,
                    trigger_event=trigger_event,
                    created_by=trigger_source.created_by,
                )
            )
        except ServiceError as error:
            increment_safe_counter(state.error_count)
            state.last_error = error.message
            raise

        self._record_result(state, trigger_result)
        return trigger_result

    def get_health(self, trigger_source_id: str) -> dict[str, object]:
        """读取一条 TriggerSource 的 supervisor 运行状态。

        参数：
        - trigger_source_id：目标 TriggerSource id。

        返回：
        - dict[str, object]：运行状态和 adapter health 摘要。
        """

        normalized_trigger_source_id = _require_stripped_text(
            trigger_source_id, "trigger_source_id"
        )
        with self._lock:
            state = self._states.get(normalized_trigger_source_id)
        if state is None:
            return {
                "managed": False,
                "trigger_source_id": normalized_trigger_source_id,
            }
        adapter_health = state.adapter.get_health(
            trigger_source_id=normalized_trigger_source_id
        )
        return {
            "managed": True,
            "trigger_source_id": normalized_trigger_source_id,
            "adapter_kind": state.adapter_kind,
            "last_triggered_at": state.last_triggered_at,
            "last_error": state.last_error,
            "adapter_health": adapter_health,
            **_counter_fields("request_count", state.request_count),
            **_counter_fields("success_count", state.success_count),
            **_counter_fields("error_count", state.error_count),
            **_counter_fields("timeout_count", state.timeout_count),
        }

    def _resolve_adapter(
        self, trigger_source: WorkflowTriggerSource
    ) -> WorkflowTriggerProtocolAdapter:
        """按 TriggerSource 类型选择 adapter。"""

        adapter = self.adapters.get(trigger_source.trigger_kind)
        if adapter is None:
            raise InvalidRequestError(
                "当前 TriggerSource 类型没有可用 adapter",
                details={"trigger_kind": trigger_source.trigger_kind},
            )
        return adapter

    def _get_or_create_state(
        self, trigger_source: WorkflowTriggerSource
    ) -> _ManagedTriggerSourceState:
        """读取或创建内存运行状态。"""

        with self._lock:
            state = self._states.get(trigger_source.trigger_source_id)
            if state is None:
                adapter = self._resolve_adapter(trigger_source)
                state = _ManagedTriggerSourceState(
                    trigger_source=trigger_source,
                    adapter_kind=adapter.adapter_kind,
                    adapter=adapter,
                )
                self._states[trigger_source.trigger_source_id] = state
            return state

    def _record_result(
        self, state: _ManagedTriggerSourceState, trigger_result: TriggerResultContract
    ) -> None:
        """把 TriggerResult 状态记入计数器。"""

        if trigger_result.state == "timed_out":
            increment_safe_counter(state.timeout_count)
            state.last_error = trigger_result.error_message
            return
        if trigger_result.state == "failed":
            increment_safe_counter(state.error_count)
            state.last_error = trigger_result.error_message
            return
        increment_safe_counter(state.success_count)
        state.last_error = None


def _counter_fields(prefix: str, counter: SafeCounterState) -> dict[str, int]:
    """把 SafeCounterState 转换为统一 health 字段。"""

    snapshot = snapshot_safe_counter(counter)
    return {
        prefix: snapshot["value"],
        f"{prefix}_rollover_count": snapshot["rollover_count"],
    }


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。"""

    normalized_value = value.strip() if isinstance(value, str) else ""
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    return normalized_value
