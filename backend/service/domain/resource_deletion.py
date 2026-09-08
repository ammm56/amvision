"""资源删除清单及持久恢复状态。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceRef(BaseModel):
    """描述单个资源的类型和稳定 id。"""

    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: str
    resource_id: str


class StorageDeletionTarget(BaseModel):
    """描述经过归属校验的原路径及删除暂存路径。"""

    source: str
    staged: str


class ResourceDeletionPlan(BaseModel):
    """保存可跨进程恢复的完整删除清单，不依赖已删除业务记录。"""

    model_config = ConfigDict(extra="forbid")
    format_id: Literal["amvision.resource-deletion.v1"] = (
        "amvision.resource-deletion.v1"
    )
    operation_id: str
    project_id: str
    target: ResourceRef
    records: list[ResourceRef] = Field(default_factory=list)
    paths: list[StorageDeletionTarget] = Field(default_factory=list)
    queue_references: list[tuple[str, str]] = Field(default_factory=list)
    claim: dict[str, object] = Field(default_factory=dict)
    asynchronous: bool = False


class ResourceDeletionOperation(BaseModel):
    """描述数据库权威删除阶段；清理完成后不永久保留日志。"""

    plan: ResourceDeletionPlan
    state: Literal["prepared", "committed", "completed", "rolled_back"]
    error: str | None = None
