"""LocalBufferBroker 运行配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LocalBufferBrokerPoolSettings(BaseModel):
    """描述一个 mmap buffer pool 的固定配置。

    字段：
    - pool_name：pool 稳定名称。
    - file_name：pool 对应的 mmap 文件名。
    - file_size_bytes：单个 pool 文件总容量。
    - slot_size_bytes：单个固定槽位容量。
    """

    pool_name: str = "image-small"
    file_name: str = "pool-001.dat"
    file_size_bytes: int = 64 * 1024 * 1024
    slot_size_bytes: int = 4 * 1024 * 1024


class LocalBufferBrokerSettings(BaseModel):
    """描述 LocalBufferBroker companion process 配置。

    字段：
    - enabled：是否随 backend-service 启动 broker 进程。
    - root_dir：broker 管理的 mmap 文件根目录。
    - startup_timeout_seconds：等待 broker 启动完成的最长秒数。
    - request_timeout_seconds：单次控制请求等待响应的最长秒数。
    - shutdown_timeout_seconds：等待 broker 优雅退出的最长秒数。
    - expire_interval_seconds：周期性触发过期 lease 回收的间隔秒数；小于等于 0 表示关闭循环。
    - default_pool_name：未显式指定时使用的默认 pool。
    - pools：broker 启动时创建的 mmap pool 列表。
    """

    enabled: bool = True
    root_dir: str = "./data/buffers"
    startup_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    expire_interval_seconds: float = 5.0
    default_pool_name: str = "image-small"
    pools: tuple[LocalBufferBrokerPoolSettings, ...] = Field(
        default_factory=lambda: (LocalBufferBrokerPoolSettings(),)
    )