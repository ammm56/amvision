"""本机共享内存 Workflow Trigger 的公开 JSON 握手契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


WORKFLOW_TRIGGER_PREPARE_FORMAT = "amvision.workflow-trigger-prepare.v1"
WORKFLOW_TRIGGER_ALLOCATION_FORMAT = "amvision.workflow-trigger-allocation.v1"
WORKFLOW_TRIGGER_REQUEST_FORMAT = "amvision.workflow-trigger-request.v1"
WORKFLOW_TRIGGER_EVENT_REQUEST_FORMAT = "amvision.workflow-trigger-event-request.v1"


class WorkflowTriggerInputImageSpec(BaseModel):
    """描述 SDK 准备写入 LocalBuffer 的单张图片。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    content_length: int = Field(gt=0)
    media_type: str
    event_payload_key: str = "request_image_ref"
    shape: tuple[int, ...] = ()
    dtype: str | None = None
    layout: str | None = None
    pixel_format: str | None = None

    @model_validator(mode="after")
    def validate_image(self) -> WorkflowTriggerInputImageSpec:
        """校验图片表示元数据。"""

        _require_text(self.media_type, "media_type")
        _require_text(self.event_payload_key, "event_payload_key")
        if any(value <= 0 for value in self.shape):
            raise ValueError("shape 中的维度必须大于 0")
        return self


class WorkflowTriggerPrepareV1(BaseModel):
    """SDK 在 descriptor PREPARE 阶段提交的固定握手。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_PREPARE_FORMAT] = (
        WORKFLOW_TRIGGER_PREPARE_FORMAT
    )
    trigger_source_id: str
    event_id: str
    image: WorkflowTriggerInputImageSpec

    @model_validator(mode="after")
    def validate_prepare(self) -> WorkflowTriggerPrepareV1:
        """校验 source/event identity。"""

        _require_text(self.trigger_source_id, "trigger_source_id")
        _require_text(self.event_id, "event_id")
        return self


class WorkflowTriggerAllocationV1(BaseModel):
    """backend 返回给可信本机 SDK 的精确写入 locator。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_ALLOCATION_FORMAT] = (
        WORKFLOW_TRIGGER_ALLOCATION_FORMAT
    )
    arena_id: str
    lease_id: str
    buffer_id: str
    descriptor_index: int = Field(ge=0)
    descriptor_generation: int = Field(ge=1)
    broker_epoch: str
    layout_fingerprint: str = Field(min_length=64, max_length=64)
    offset: int = Field(ge=0)
    content_length: int = Field(gt=0)
    allocation_capacity_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_allocation(self) -> WorkflowTriggerAllocationV1:
        """拒绝空 locator identity。"""

        for field_name in (
            "arena_id",
            "lease_id",
            "buffer_id",
            "broker_epoch",
            "layout_fingerprint",
        ):
            _require_text(getattr(self, field_name), field_name)
        try:
            bytes.fromhex(self.layout_fingerprint)
        except ValueError as error:
            raise ValueError("layout_fingerprint 必须为 SHA-256 hex") from error
        if self.content_length > self.allocation_capacity_bytes:
            raise ValueError("allocation_capacity_bytes 不能小于 content_length")
        return self


class WorkflowTriggerRequestV1(BaseModel):
    """SDK 释放 writer guard 后发布的业务请求。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_REQUEST_FORMAT] = (
        WORKFLOW_TRIGGER_REQUEST_FORMAT
    )
    trigger_source_id: str
    event_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    trace_id: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def validate_request(self) -> WorkflowTriggerRequestV1:
        """校验 request identity 与可选追踪字段。"""

        _require_text(self.trigger_source_id, "trigger_source_id")
        _require_text(self.event_id, "event_id")
        if self.trace_id is not None:
            _require_text(self.trace_id, "trace_id")
        if self.idempotency_key is not None:
            _require_text(self.idempotency_key, "idempotency_key")
        return self


class WorkflowTriggerEventRequestV1(BaseModel):
    """不携带图片、直接发布到 mailbox REQUEST 阶段的结构化事件。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_id: Literal[WORKFLOW_TRIGGER_EVENT_REQUEST_FORMAT] = (
        WORKFLOW_TRIGGER_EVENT_REQUEST_FORMAT
    )
    trigger_source_id: str
    event_id: str
    payload: dict[str, object] = Field(default_factory=dict)
    metadata: dict[str, object] = Field(default_factory=dict)
    trace_id: str | None = None
    idempotency_key: str | None = None

    @model_validator(mode="after")
    def validate_event_request(self) -> WorkflowTriggerEventRequestV1:
        """校验无图片事件请求的稳定 identity 与追踪字段。"""

        _require_text(self.trigger_source_id, "trigger_source_id")
        _require_text(self.event_id, "event_id")
        if self.trace_id is not None:
            _require_text(self.trace_id, "trace_id")
        if self.idempotency_key is not None:
            _require_text(self.idempotency_key, "idempotency_key")
        return self


def _require_text(value: str, field_name: str) -> str:
    """校验字符串非空。"""

    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized:
        raise ValueError(f"{field_name} 不能为空")
    return normalized
