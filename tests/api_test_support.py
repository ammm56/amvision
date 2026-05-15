"""通用 API 测试辅助模块。"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path

from fastapi.testclient import TestClient

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.auth.default_local_auth_seeder import (
    DEFAULT_LOCAL_AUTH_TOKEN,
    DEFAULT_LOCAL_AUTH_USERNAME,
)
from backend.service.application.auth.local_auth_service import LocalAuthService, LocalAuthUserCreateRequest
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig


_VALID_TEST_IMAGE_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVQIHWNk+M8ABIwM/xmAAAAREgIB9FemLQAAAABJRU5ErkJggg=="
)
_DEFAULT_TEST_AUTH_TOKEN = DEFAULT_LOCAL_AUTH_TOKEN
_DEFAULT_TEST_AUTH_USERNAME = DEFAULT_LOCAL_AUTH_USERNAME


@dataclass(frozen=True)
class ApiTestContext:
    """描述一个通用 API 测试上下文。

    字段：
    - client：FastAPI TestClient。
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储。
    - queue_backend：本地任务队列后端。
    """

    client: TestClient
    session_factory: SessionFactory
    dataset_storage: LocalDatasetStorage
    queue_backend: LocalFileQueueBackend


def create_test_runtime(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建通用 API 快测试使用的数据库、文件存储和队列。

    参数：
    - tmp_path：pytest 提供的临时目录。
    - database_name：SQLite 数据库文件名。

    返回：
    - tuple[SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]：测试基础运行时。
    """

    database_path = tmp_path / database_name
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))
    queue_backend = LocalFileQueueBackend(LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files")))
    return session_factory, dataset_storage, queue_backend


def create_api_test_context(
    tmp_path: Path,
    *,
    database_name: str,
    enable_task_manager: bool = False,
    max_concurrent_tasks: int = 2,
    poll_interval_seconds: float = 0.05,
) -> ApiTestContext:
    """创建绑定测试数据库、本地文件存储和队列的通用 API 测试上下文。

    参数：
    - tmp_path：pytest 提供的临时目录。
    - database_name：SQLite 数据库文件名。
    - enable_task_manager：是否启用 task manager。
    - max_concurrent_tasks：task manager 最大并发数。
    - poll_interval_seconds：task manager 轮询间隔。

    返回：
    - ApiTestContext：构建完成的 API 测试上下文。
    """

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(
            enabled=enable_task_manager,
            max_concurrent_tasks=max_concurrent_tasks,
            poll_interval_seconds=poll_interval_seconds,
        )
    )
    application = create_app(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    return ApiTestContext(
        client=TestClient(application),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )


def build_test_headers(*, scopes: str) -> dict[str, str]:
    """构建默认本地测试用户的 Bearer 请求头。

    参数：
    - scopes：保留给调用点表达预期权限范围；当前默认本地测试用户始终持有全部 scopes。

    返回：
    - dict[str, str]：统一格式的 Bearer 鉴权请求头。
    """

    _ = scopes
    return build_bearer_headers(_DEFAULT_TEST_AUTH_TOKEN)


def build_bearer_headers(token: str) -> dict[str, str]:
    """按显式 Bearer token 构建测试请求头。

    参数：
    - token：要发送的 Bearer token 明文。

    返回：
    - dict[str, str]：带 Authorization 头的请求头字典。
    """

    return {"Authorization": f"Bearer {token}"}


def get_default_test_principal_id(session_factory: SessionFactory) -> str:
    """解析默认本地测试用户当前实际 principal_id。

    参数：
    - session_factory：测试数据库会话工厂。

    返回：
    - str：默认本地测试用户当前解析得到的 user_id。
    """

    service = LocalAuthService(settings=BackendServiceSettings(), session_factory=session_factory)
    resolved_credential = service.resolve_bearer_token(_DEFAULT_TEST_AUTH_TOKEN)
    if resolved_credential is None:
        raise AssertionError("默认本地测试用户尚未初始化")
    if resolved_credential.user.username != _DEFAULT_TEST_AUTH_USERNAME:
        raise AssertionError("默认本地测试用户与预期用户名不一致")
    return resolved_credential.user.user_id


def issue_test_user_token(
    session_factory: SessionFactory,
    *,
    username: str,
    scopes: tuple[str, ...],
    project_ids: tuple[str, ...] = (),
    password: str = "123456",
    display_name: str | None = None,
    principal_type: str = "user",
) -> str:
    """为测试数据库签发一个受限本地 user token。

    参数：
    - session_factory：测试数据库会话工厂。
    - username：要创建的本地用户名。
    - scopes：要授予该测试用户的 scopes。
    - project_ids：要授予该测试用户的 Project 可见范围。
    - password：测试用户密码。
    - display_name：可选展示名称。
    - principal_type：主体类型。

    返回：
    - str：新签发的长期调用 user token 明文。
    """

    service = LocalAuthService(settings=BackendServiceSettings(), session_factory=session_factory)
    result = service.create_user(
        LocalAuthUserCreateRequest(
            username=username,
            password=password,
            display_name=display_name,
            principal_type=principal_type,
            project_ids=project_ids,
            scopes=scopes,
        )
    )
    if result.initial_user_token is None:
        raise AssertionError("测试用户未返回默认长期调用 token")
    return result.initial_user_token.token


def build_valid_test_png_bytes() -> bytes:
    """返回可被 OpenCV 正常读取的最小 PNG 图片字节。

    返回：
    - bytes：最小有效 PNG 图片字节。
    """

    return base64.b64decode(_VALID_TEST_IMAGE_BASE64)


def build_test_jpeg_bytes() -> bytes:
    """构建一个可被 OpenCV 正常读取的最小 JPEG 图片。

    返回：
    - bytes：最小 JPEG 图片字节。
    """

    import cv2
    import numpy as np

    image = np.full((64, 64, 3), 255, dtype=np.uint8)
    success, encoded = cv2.imencode(".jpg", image)
    assert success is True
    return encoded.tobytes()