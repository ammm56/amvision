"""资源列表的拒绝状态，不提供其他格式的内容读取入口。"""

from typing import Annotated, Literal
from pydantic import Field
from backend.contracts.workflows.metrology import Contract, ResourceReference


class UnavailableCloudResource(Contract):
    """不可用资源只保留身份与依赖，避免误用或误删其来源。"""

    state: Literal["rebuild-required"] = "rebuild-required"
    reason: Literal["unsupported_point_cloud_format"] = "unsupported_point_cloud_format"
    reference: ResourceReference
    name: Annotated[str, Field(min_length=1, max_length=128)]
    created_at: str
    content: None = None
    stored_format_id: str
    parent_assets: tuple[ResourceReference, ...]
