"""节点注册表依赖定义。"""

from __future__ import annotations

from fastapi import Request

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import ServiceConfigurationError


def get_node_catalog_registry(request: Request) -> NodeCatalogRegistry:
    """从 FastAPI 应用状态中读取 NodeCatalogRegistry。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前应用使用的统一节点目录注册表。

    异常：
    - 当应用未完成 NodeCatalogRegistry 装配时抛出服务配置错误。
    """

    node_catalog_registry = getattr(request.app.state, "node_catalog_registry", None)
    if not isinstance(node_catalog_registry, NodeCatalogRegistry):
        raise ServiceConfigurationError(
            "当前服务尚未完成 NodeCatalogRegistry 装配",
            details={"state_field": "node_catalog_registry"},
        )
    return node_catalog_registry
