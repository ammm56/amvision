"""编辑态 Preview v1 内存会话合约；不复用持久化 Run。"""

from __future__ import annotations

import struct
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate

PREVIEW_SESSION_FORMAT = "amvision.workflow-preview-session.v1"
PREVIEW_CHUNK_SIZE = 256 * 1024
PREVIEW_FRAME_HEADER = struct.Struct(">4sBBH16sII")
PREVIEW_FRAME_MAGIC = b"AMVP"
PREVIEW_TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "timed_out"})
PreviewRunState = Literal["accepted", "running", "succeeded", "failed", "cancelled", "timed_out"]


class PreviewContract(BaseModel):
    """所有外部输入拒绝未声明字段，内部身份不接受客户端覆盖。"""

    model_config = ConfigDict(extra="forbid")


class PreviewSessionCreate(PreviewContract):
    """project/application/editor_session 决定会话范围，owner 来自认证。"""

    project_id: str = Field(min_length=1, max_length=128)
    application_id: str = Field(min_length=1, max_length=128)
    editor_session_id: str = Field(min_length=1, max_length=128)


class PreviewExecutionScope(PreviewContract):
    """显式指定整图或目标节点，避免把界面选择误作执行范围。"""

    kind: Literal["application", "node"] = "application"
    target_node_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_target(self):
        """节点范围必须有目标，整图范围不得夹带目标。"""
        if self.kind == "node" and not (self.target_node_id or "").strip():
            raise ValueError("node scope requires target_node_id")
        if self.kind == "application" and self.target_node_id is not None:
            raise ValueError("application scope cannot have target_node_id")
        return self


class PreviewSessionRunCreate(PreviewContract):
    """受理后固定快照；二进制输入通过会话 input_id 交接。"""

    request_id: UUID
    document_revision: str = Field(min_length=1, max_length=128)
    application: FlowApplication
    template: WorkflowGraphTemplate
    input_bindings: dict[str, Any] = Field(default_factory=dict)
    input_ids: dict[str, UUID | list[UUID]] = Field(default_factory=dict)
    execution_scope: PreviewExecutionScope = Field(default_factory=PreviewExecutionScope)
    timeout_seconds: int | None = Field(default=None, ge=1, le=86400)


class PreviewInputBegin(PreviewContract):
    """上传前声明完整长度和摘要，分配前检查限额。"""

    type: Literal["input.begin"] = "input.begin"
    transfer_id: UUID
    byte_length: int = Field(gt=0, le=64 * 1024 * 1024)
    media_type: str = Field(min_length=1, max_length=128)
    file_name: str = Field(default="input", min_length=1, max_length=255)
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class PreviewEvent(PreviewContract):
    """seq 是会话归并顺序；节点调用身份放入 payload，不假设串行执行。"""

    format_id: Literal["amvision.workflow-preview-session.v1"] = PREVIEW_SESSION_FORMAT
    session_id: str
    epoch: str
    run_id: str | None = None
    seq: int = Field(ge=0)
    type: str
    document_revision: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


def encode_preview_frame(transfer_id: UUID, index: int, content: bytes, *, kind: int) -> bytes:
    """编码固定头；kind=1 上传、kind=2 显示，单块限制与方向不由客户端协商。"""
    if kind not in (1, 2) or not 0 <= index <= 0xFFFFFFFF:
        raise ValueError("preview_frame_identity_invalid")
    if not 0 < len(content) <= PREVIEW_CHUNK_SIZE:
        raise ValueError("preview_frame_size_invalid")
    return PREVIEW_FRAME_HEADER.pack(
        PREVIEW_FRAME_MAGIC, 1, kind, 0, transfer_id.bytes, index, len(content)
    ) + content


def decode_preview_frame(frame: bytes, *, expected_kind: int) -> tuple[UUID, int, memoryview]:
    """校验完整 WS 消息的版本、方向、长度，拒绝额外尾部与半包。"""
    if len(frame) < PREVIEW_FRAME_HEADER.size:
        raise ValueError("preview_frame_header_incomplete")
    magic, version, kind, flags, identity, index, length = PREVIEW_FRAME_HEADER.unpack_from(frame)
    if magic != PREVIEW_FRAME_MAGIC or version != 1 or kind != expected_kind or flags:
        raise ValueError("preview_frame_protocol_invalid")
    if not 0 < length <= PREVIEW_CHUNK_SIZE or len(frame) != PREVIEW_FRAME_HEADER.size + length:
        raise ValueError("preview_frame_size_invalid")
    return UUID(bytes=identity), index, memoryview(frame)[PREVIEW_FRAME_HEADER.size:]
