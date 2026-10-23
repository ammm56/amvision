"""旧三维资产仅保留管理元数据，不提供旧算法或旧内容执行入口。"""

from typing import Annotated, Literal
from pydantic import Field
from backend.contracts.workflows.metrology import Contract, ResourceReference


class RetiredCloudResource(Contract):
    """列表中的明确重建状态；不将旧内容伪装成当前资源文档。"""

    state: Literal["rebuild-required"] = "rebuild-required"
    reason: Literal["unsupported_point_cloud_format"] = "unsupported_point_cloud_format"
    reference: ResourceReference
    name: Annotated[str, Field(min_length=1, max_length=128)]
    created_at: str
    content: None = None
    stored_format_id: str
    parent_assets: tuple[ResourceReference, ...]
