"""本地数据集文件存储依赖定义。"""

from __future__ import annotations

from fastapi import Request

from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


def get_dataset_storage(request: Request) -> LocalDatasetStorage:
    """从 FastAPI 应用状态中读取 LocalDatasetStorage。

    参数：
    - request：当前 HTTP 请求。

    返回：
    - 当前应用使用的数据集本地文件存储服务。

    异常：
    - 当应用未完成本地文件存储装配时抛出服务配置错误。
    """

    dataset_storage = getattr(request.app.state, "dataset_storage", None)
    if not isinstance(dataset_storage, LocalDatasetStorage):
        raise ServiceConfigurationError(
            "当前服务尚未完成数据集文件存储装配",
            details={"state_field": "dataset_storage"},
        )

    return dataset_storage