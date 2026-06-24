"""MES HTTP 输出节点 runtime 类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["result", "workflow_result", "summary", "request", "literal"]
OnMissingPolicy = Literal["error", "skip", "null"]
AuthKind = Literal["none", "bearer_token", "header_static"]
BodyMode = Literal["json_object", "json_envelope"]
HttpMethod = Literal["POST", "PUT"]


@dataclass(frozen=True)
class FieldMappingConfig:
    """描述单个 body 字段映射。"""

    target_path: str
    source_kind: SourceKind
    source_path: str | None
    literal_value: object | None
    on_missing: OnMissingPolicy | None


@dataclass(frozen=True)
class QueryMappingConfig:
    """描述单个 query 字段映射。"""

    target_name: str
    source_kind: SourceKind
    source_path: str | None
    literal_value: object | None
    on_missing: OnMissingPolicy | None
