"""本地数据库输出节点 runtime 类型。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SourceKind = Literal["result", "workflow_result", "summary", "request", "literal"]
OnMissingPolicy = Literal["error", "skip", "null"]
DatabaseKind = Literal["sqlite", "postgresql", "mysql"]


@dataclass(frozen=True)
class ColumnMappingConfig:
    """描述单个数据库列映射。"""

    column_name: str
    source_kind: SourceKind
    source_path: str | None
    literal_value: object | None
    on_missing: OnMissingPolicy | None
