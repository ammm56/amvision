"""workflow trigger source 资源规则。"""

from __future__ import annotations

from datetime import datetime
import math
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.contracts.workflows.runtime import (
    WorkflowApplicationReferenceSummaryContract,
    WorkflowRuntimeReferenceSummaryContract,
)
from backend.contracts.workflows.resource_semantics import (
    WorkflowTriggerAckPolicy,
    WorkflowTriggerKind,
    WorkflowTriggerResultMode,
    WorkflowTriggerResultState,
    WorkflowTriggerRuntimeState,
    WorkflowTriggerSubmitMode,
)


WORKFLOW_TRIGGER_SOURCE_FORMAT = "amvision.workflow-trigger-source.v1"
WORKFLOW_TRIGGER_EVENT_FORMAT = "amvision.workflow-trigger-event.v1"
WORKFLOW_TRIGGER_RESULT_FORMAT = "amvision.workflow-trigger-result.v1"
DIRECTORY_CHANGE_EVENT_FORMAT = "amvision.directory-change-event.v1"
DIRECTORY_CHANGE_EVENT_TYPES = ("created", "modified", "deleted")

# 高性能 Trigger 只传递结构化小参数和 LocalBuffer 图片引用。文件、文件列表与
# Base64 图片由 HTTP Runtime 负责，避免在常驻 Trigger 数据面引入隐式暂存和复制。
HIGH_PERFORMANCE_TRIGGER_KINDS = frozenset(
    {"zeromq-topic", "local-shared-memory"}
)
HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS = frozenset(
    {"image-ref.v1", "value.v1", "text.v1"}
)


def workflow_trigger_supports_input_payload_type(
    trigger_kind: str,
    payload_type_id: str,
) -> bool:
    """判断 Trigger 类型是否支持公开输入 payload 类型。

    非高性能 Trigger 保持既有协议适配能力；ZeroMQ 和本机共享内存只接受
    image-ref/value/text 三类稳定输入。
    """

    return (
        trigger_kind not in HIGH_PERFORMANCE_TRIGGER_KINDS
        or payload_type_id in HIGH_PERFORMANCE_TRIGGER_INPUT_PAYLOAD_TYPE_IDS
    )


def _require_stripped_text(value: str, field_name: str) -> str:
    """校验字符串字段非空。

    参数：
    - value：待校验的字符串值。
    - field_name：字段名称。

    返回：
    - str：去除两端空白后的结果。
    """

    normalized_value = value.strip()
    if not normalized_value:
        raise ValueError(f"{field_name} 不能为空")
    return normalized_value


class DirectoryWatchTransportConfigContract(BaseModel):
    """描述 directory-watch TriggerSource 的公开 transport 配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    directory_path: str
    recursive: bool = False
    include_hidden: bool = False
    glob_pattern: str = "*"
    extensions: tuple[str, ...] = ()
    event_types: tuple[Literal["created", "modified", "deleted"], ...] = (
        "created",
        "modified",
        "deleted",
    )
    min_trigger_interval_seconds: float = Field(default=3.0, ge=1.0, le=3600.0)
    event_sample_limit: int = Field(default=10, ge=0, le=100)
    force_polling: bool | None = None
    poll_delay_ms: int = Field(default=300, ge=50, le=60000)
    ignore_permission_denied: bool = False

    @field_validator("directory_path", mode="before")
    @classmethod
    def normalize_directory_path(cls, value: object) -> object:
        """规范化并校验 backend-service 本机绝对目录路径。"""

        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized or len(normalized) > 4096 or "\x00" in normalized:
            raise ValueError("directory_path 必须是长度 1 至 4096 的非空路径")
        if normalized.startswith("~") or not Path(normalized).is_absolute():
            raise ValueError("directory_path 必须是 backend-service 本机绝对路径")
        return str(Path(normalized).absolute())

    @field_validator("glob_pattern", mode="before")
    @classmethod
    def normalize_glob_pattern(cls, value: object) -> object:
        """规范化相对 Glob 表达式。"""

        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized or len(normalized) > 256 or "\x00" in normalized:
            raise ValueError("glob_pattern 必须是长度 1 至 256 的非空字符串")
        slash_value = normalized.replace("\\", "/")
        if (
            Path(normalized).is_absolute()
            or slash_value.startswith("/")
            or any(part == ".." for part in slash_value.split("/"))
        ):
            raise ValueError("glob_pattern 必须是监控根目录内的相对模式")
        return slash_value

    @field_validator("extensions", mode="before")
    @classmethod
    def normalize_extensions(cls, value: object) -> object:
        """规范化扩展名过滤列表。"""

        if value is None:
            return ()
        if not isinstance(value, list | tuple):
            return value
        if len(value) > 32:
            raise ValueError("extensions 最多允许 32 项")
        normalized_values: set[str] = set()
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("extensions 必须全部是非空字符串")
            normalized = item.strip().lower()
            if not normalized.startswith("."):
                normalized = f".{normalized}"
            if (
                not 2 <= len(normalized) <= 32
                or normalized.count(".") != 1
                or any(
                    character in normalized
                    for character in ("/", "\\", "\x00", "*", "?")
                )
            ):
                raise ValueError("extension 必须是长度 2 至 32 且只有一个前导点的文件扩展名")
            normalized_values.add(normalized)
        return tuple(sorted(normalized_values))

    @field_validator("event_types", mode="before")
    @classmethod
    def normalize_event_types(cls, value: object) -> object:
        """按固定顺序规范化目录变化类型。"""

        if not isinstance(value, list | tuple | set | frozenset):
            return value
        raw_values = list(value)
        if not raw_values:
            raise ValueError("event_types 至少选择一项")
        if any(not isinstance(item, str) for item in raw_values):
            return value
        unknown_values = set(raw_values) - set(DIRECTORY_CHANGE_EVENT_TYPES)
        if unknown_values:
            raise ValueError("event_types 只支持 created、modified、deleted")
        return tuple(
            item for item in DIRECTORY_CHANGE_EVENT_TYPES if item in raw_values
        )

    @field_validator("min_trigger_interval_seconds")
    @classmethod
    def validate_finite_interval(cls, value: float) -> float:
        """拒绝 NaN 和 Infinity。"""

        if not math.isfinite(value):
            raise ValueError("min_trigger_interval_seconds 必须是有限数值")
        return value

    @field_validator("min_trigger_interval_seconds", mode="before")
    @classmethod
    def reject_non_numeric_interval(cls, value: object) -> object:
        """拒绝 bool、字符串和其他隐式数值转换。"""

        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError("min_trigger_interval_seconds 必须是数值")
        return value

    @field_validator("event_sample_limit", "poll_delay_ms", mode="before")
    @classmethod
    def reject_non_integer_fields(cls, value: object) -> object:
        """拒绝 bool、字符串和浮点数隐式转换为整数。"""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("event_sample_limit 和 poll_delay_ms 必须是整数")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> DirectoryWatchTransportConfigContract:
        """校验跨字段目录监听规则。"""

        if not self.recursive and "**" in self.glob_pattern:
            raise ValueError("recursive=false 时 glob_pattern 不能包含 **")
        return self


class DirectoryChangeSampleContract(BaseModel):
    """描述目录变化事件中的一条有界诊断样本。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_change_types: tuple[Literal["created", "modified", "deleted"], ...]
    path: str
    relative_path: str
    observed_at: str
    observed_sequence: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_contract(self) -> DirectoryChangeSampleContract:
        """校验样本路径、时间和变化类型。"""

        _require_stripped_text(self.path, "path")
        _require_stripped_text(self.relative_path, "relative_path")
        _require_timezone_timestamp(self.observed_at, "observed_at")
        if not self.observed_change_types:
            raise ValueError("observed_change_types 不能为空")
        expected = tuple(
            item for item in DIRECTORY_CHANGE_EVENT_TYPES if item in self.observed_change_types
        )
        if expected != self.observed_change_types or len(expected) != len(set(expected)):
            raise ValueError("observed_change_types 必须去重并按固定顺序排列")
        return self


class DirectoryChangeCountsContract(BaseModel):
    """描述目录变化事件的观察计数。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    created: int = Field(ge=0)
    modified: int = Field(ge=0)
    deleted: int = Field(ge=0)
    total: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_contract(self) -> DirectoryChangeCountsContract:
        """确保总数等于三类变化计数之和。"""

        if self.total != self.created + self.modified + self.deleted:
            raise ValueError("change_counts.total 必须等于三类变化计数之和")
        return self


class DirectoryChangeSourceContract(BaseModel):
    """描述产生目录变化事件的监控范围。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    recursive: bool
    glob_pattern: str
    extensions: tuple[str, ...] = ()


class DirectoryChangeEventContract(BaseModel):
    """描述目录变化 Trigger 提交给 Workflow App 的稳定 value。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[DIRECTORY_CHANGE_EVENT_FORMAT] = DIRECTORY_CHANGE_EVENT_FORMAT
    event_id: str
    trigger_source_id: str
    workflow_runtime_id: str
    window_started_at: str
    window_finished_at: str
    min_trigger_interval_seconds: float = Field(ge=1.0, le=3600.0)
    directory: DirectoryChangeSourceContract
    change_counts: DirectoryChangeCountsContract
    samples: tuple[DirectoryChangeSampleContract, ...] = ()
    sample_limit: int = Field(ge=0, le=100)
    sample_count: int = Field(ge=0, le=100)
    samples_truncated: bool

    @model_validator(mode="after")
    def validate_contract(self) -> DirectoryChangeEventContract:
        """校验事件标识、时间和样本集合一致性。"""

        _require_stripped_text(self.event_id, "event_id")
        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_timezone_timestamp(self.window_started_at, "window_started_at")
        _require_timezone_timestamp(self.window_finished_at, "window_finished_at")
        if self.sample_count != len(self.samples) or self.sample_count > self.sample_limit:
            raise ValueError("sample_count 必须等于 samples 数量且不能超过 sample_limit")
        normalized_paths = [os.path.normcase(item.path) for item in self.samples]
        if len(normalized_paths) != len(set(normalized_paths)):
            raise ValueError("samples 不能包含重复路径")
        sequences = [item.observed_sequence for item in self.samples]
        if sequences != sorted(sequences, reverse=True):
            raise ValueError("samples 必须按 observed_sequence 倒序排列")
        return self


def _require_timezone_timestamp(value: str, field_name: str) -> None:
    """校验 ISO 8601 时间包含时区。"""

    normalized = _require_stripped_text(value, field_name).replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} 必须包含时区")


class InputBindingMappingItemContract(BaseModel):
    """描述单个外部事件字段到 application input binding 的映射规则。

    字段：
    - source：事件 payload 中的来源路径，例如 payload.image 或 payload.value。
    - value：静态绑定值；用于固定配置或默认输入。
    - required：映射来源缺失时是否视为请求错误。
    - payload_type_id：目标 payload 类型提示。
    - metadata：附加映射元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str | None = None
    value: object | None = None
    required: bool = True
    payload_type_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> InputBindingMappingItemContract:
        """校验 input binding 映射规则。"""

        if self.source is not None:
            _require_stripped_text(self.source, "source")
        if self.payload_type_id is not None:
            _require_stripped_text(self.payload_type_id, "payload_type_id")
        value_is_present = "value" in self.model_fields_set
        if self.source is None and not value_is_present:
            raise ValueError("input binding 映射必须提供 source 或 value")
        if self.source is not None and value_is_present and self.value is not None:
            raise ValueError("input binding 映射不能同时提供 source 和静态 value")
        return self


class ResultMappingContract(BaseModel):
    """描述 workflow 输出到协议回执的映射规则。

    字段：
    - result_bindings：按顺序选择的 FlowApplication 输出 binding。

    ``result_mode``、``reply_timeout_seconds`` 和 ``ack_policy`` 只由
    ``WorkflowTriggerSourceContract`` 顶层字段定义，避免嵌套配置与顶层配置
    产生两个事实源。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    result_bindings: tuple[str, ...] = ()

    @field_validator("result_bindings", mode="before")
    @classmethod
    def normalize_result_bindings(cls, value: object) -> object:
        """在冻结模型构造前去除 binding 两端空白。"""

        if not isinstance(value, list | tuple):
            return value
        return tuple(
            item.strip() if isinstance(item, str) else item for item in value
        )

    @model_validator(mode="after")
    def validate_contract(self) -> ResultMappingContract:
        """校验 result mapping 规则。"""

        normalized = tuple(
            _require_stripped_text(binding_id, "result_bindings")
            for binding_id in self.result_bindings
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("result_bindings 不能包含重复 binding")
        return self


class WorkflowTriggerSourceContract(BaseModel):
    """描述 WorkflowTriggerSource 的稳定 JSON 规则。

    字段：
    - format_id：当前资源格式版本。
    - trigger_source_id：触发源 id。
    - project_id：所属 Project id。
    - display_name：展示名称。
    - trigger_kind：触发类型。
    - workflow_runtime_id：绑定的 WorkflowAppRuntime id。
    - submit_mode：提交模式，sync 或 async。
    - enabled：是否启用接收新触发。
    - desired_state：期望运行状态。
    - observed_state：实际观测状态。
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
    - last_triggered_at：最近一次触发时间。
    - last_error：最近错误消息。
    - health_summary：运行健康摘要。
    - metadata：附加元数据。
    - created_at：创建时间。
    - updated_at：更新时间。
    - created_by：创建主体 id。
    - updated_by：最近修改主体 id。
    - runtime_summary：绑定 runtime 的一跳摘要。
    - application_summary：绑定 application 的一跳摘要。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_SOURCE_FORMAT] = WORKFLOW_TRIGGER_SOURCE_FORMAT
    trigger_source_id: str
    project_id: str
    display_name: str
    trigger_kind: WorkflowTriggerKind
    workflow_runtime_id: str
    submit_mode: WorkflowTriggerSubmitMode = "sync"
    enabled: bool = False
    desired_state: WorkflowTriggerRuntimeState = "stopped"
    observed_state: WorkflowTriggerRuntimeState = "stopped"
    transport_config: dict[str, object] = Field(default_factory=dict)
    match_rule: dict[str, object] = Field(default_factory=dict)
    input_binding_mapping: dict[str, InputBindingMappingItemContract] = Field(
        default_factory=dict
    )
    result_mapping: ResultMappingContract = Field(default_factory=ResultMappingContract)
    default_execution_metadata: dict[str, object] = Field(default_factory=dict)
    ack_policy: WorkflowTriggerAckPolicy = "ack-after-run-finished"
    result_mode: WorkflowTriggerResultMode = "sync-reply"
    reply_timeout_seconds: int | None = None
    debounce_window_ms: int | None = None
    idempotency_key_path: str | None = None
    last_triggered_at: str | None = None
    last_error: str | None = None
    health_summary: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    created_at: str
    updated_at: str
    created_by: str | None = None
    updated_by: str | None = None
    runtime_summary: WorkflowRuntimeReferenceSummaryContract | None = None
    application_summary: WorkflowApplicationReferenceSummaryContract | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> WorkflowTriggerSourceContract:
        """校验 WorkflowTriggerSource 规则的关键字段。"""

        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.project_id, "project_id")
        _require_stripped_text(self.display_name, "display_name")
        _require_stripped_text(self.workflow_runtime_id, "workflow_runtime_id")
        _require_stripped_text(self.created_at, "created_at")
        _require_stripped_text(self.updated_at, "updated_at")
        if self.reply_timeout_seconds is not None and self.reply_timeout_seconds <= 0:
            raise ValueError("reply_timeout_seconds 必须大于 0")
        if self.debounce_window_ms is not None and self.debounce_window_ms < 0:
            raise ValueError("debounce_window_ms 不能小于 0")
        if self.idempotency_key_path is not None:
            _require_stripped_text(self.idempotency_key_path, "idempotency_key_path")
        return self


class TriggerEventContract(BaseModel):
    """描述外部协议事件进入平台后的统一事件规则。

    字段：
    - format_id：当前事件格式版本。
    - trigger_source_id：触发源 id。
    - trigger_kind：触发类型。
    - event_id：外部或平台生成的事件 id。
    - trace_id：链路追踪 id。
    - occurred_at：事件发生时间。
    - idempotency_key：可选幂等键。
    - payload：结构化事件内容。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_EVENT_FORMAT] = WORKFLOW_TRIGGER_EVENT_FORMAT
    trigger_source_id: str
    trigger_kind: WorkflowTriggerKind
    event_id: str
    trace_id: str | None = None
    occurred_at: str
    idempotency_key: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> TriggerEventContract:
        """校验 TriggerEvent 规则的关键字段。"""

        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.event_id, "event_id")
        _require_stripped_text(self.occurred_at, "occurred_at")
        return self


class TriggerResultContract(BaseModel):
    """描述触发调用层返回给协议 adapter 的统一结果。

    字段：
    - format_id：当前结果格式版本。
    - trigger_source_id：触发源 id。
    - event_id：对应事件 id。
    - state：触发提交或执行结果状态。
    - workflow_run_id：创建出的 WorkflowRun id。
    - response_payload：协议中立响应内容。
    - error_message：错误消息。
    - metadata：附加元数据。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_RESULT_FORMAT] = WORKFLOW_TRIGGER_RESULT_FORMAT
    trigger_source_id: str
    event_id: str
    state: WorkflowTriggerResultState
    workflow_run_id: str | None = None
    response_payload: dict[str, object] = Field(default_factory=dict)
    error_message: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_contract(self) -> TriggerResultContract:
        """校验 TriggerResult 规则的关键字段。"""

        _require_stripped_text(self.trigger_source_id, "trigger_source_id")
        _require_stripped_text(self.event_id, "event_id")
        if self.error_message is not None:
            _require_stripped_text(self.error_message, "error_message")
        return self
