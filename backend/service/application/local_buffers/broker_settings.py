"""LocalBufferBroker 运行配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


_MIB = 1024 * 1024
_DEFAULT_4K_SLOT_SIZE_BYTES = 64 * _MIB
_DEFAULT_4K_SLOT_COUNT = 32
_DEFAULT_1080P_SLOT_SIZE_BYTES = 16 * _MIB
_DEFAULT_1080P_SLOT_COUNT = 32
_DEFAULT_SMALL_SLOT_SIZE_BYTES = 4 * _MIB
_DEFAULT_SMALL_SLOT_COUNT = 32


class LocalBufferBrokerPoolSettings(BaseModel):
    """描述一个 mmap buffer pool 的固定配置。

    字段：
    - pool_name：pool 稳定名称。
    - file_name：pool 对应的 mmap 文件名。
    - file_size_bytes：单个 pool 文件总容量。
    - slot_size_bytes：单个固定槽位容量。
    """

    pool_name: str = "image-1080p"
    file_name: str = "image-1080p-001.dat"
    file_size_bytes: int = _DEFAULT_1080P_SLOT_SIZE_BYTES * _DEFAULT_1080P_SLOT_COUNT
    slot_size_bytes: int = _DEFAULT_1080P_SLOT_SIZE_BYTES


class LocalBufferBrokerSettings(BaseModel):
    """描述 LocalBufferBroker companion process 配置。

    字段：
    - enabled：是否随 backend-service 启动 broker 进程。
    - root_dir：broker 管理的 mmap 文件根目录。
    - startup_timeout_seconds：等待 broker 启动完成的最长秒数。
    - request_timeout_seconds：单次控制请求等待响应的最长秒数。
    - shutdown_timeout_seconds：等待 broker 优雅退出的最长秒数。
    - expire_interval_seconds：周期性触发过期 lease 回收的间隔秒数；小于等于 0 表示关闭循环。
    - default_pool_name：未显式指定 pool_name 时使用的默认 pool，也用于选择内置 pool preset。
    - pools：broker 启动时创建的 mmap pool 列表；为空时按 default_pool_name 选择内置 preset。
    """

    enabled: bool = True
    root_dir: str = "./data/buffers"
    startup_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    expire_interval_seconds: float = 5.0
    default_pool_name: str = "image-1080p"
    pools: tuple[LocalBufferBrokerPoolSettings, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_settings(self) -> LocalBufferBrokerSettings:
        """校验并补齐 LocalBufferBroker pool 配置。

        返回：
        - LocalBufferBrokerSettings：已补齐内置 pool preset 的配置。
        """

        normalized_default_pool_name = self.default_pool_name.strip()
        if not normalized_default_pool_name:
            raise ValueError("LocalBufferBroker default_pool_name 不能为空")
        self.default_pool_name = normalized_default_pool_name
        if not self.pools:
            self.pools = (_build_default_buffer_pool(normalized_default_pool_name),)
        pool_names = {item.pool_name.strip() for item in self.pools}
        if normalized_default_pool_name not in pool_names:
            raise ValueError("LocalBufferBroker default_pool_name 未出现在 pools 中")
        if len(pool_names) != len(self.pools):
            raise ValueError("LocalBufferBroker pool_name 不能重复")
        return self


def _build_default_buffer_pool(pool_name: str) -> LocalBufferBrokerPoolSettings:
    """按名称构造内置 LocalBufferBroker pool preset。

    参数：
    - pool_name：内置 pool 名称，可选 image-small、image-1080p 或 image-4k。

    返回：
    - LocalBufferBrokerPoolSettings：对应的 pool 配置。
    """

    if pool_name == "image-small":
        return LocalBufferBrokerPoolSettings(
            pool_name="image-small",
            file_name="image-small-001.dat",
            file_size_bytes=_DEFAULT_SMALL_SLOT_SIZE_BYTES * _DEFAULT_SMALL_SLOT_COUNT,
            slot_size_bytes=_DEFAULT_SMALL_SLOT_SIZE_BYTES,
        )
    if pool_name == "image-1080p":
        return LocalBufferBrokerPoolSettings()
    if pool_name == "image-4k":
        return LocalBufferBrokerPoolSettings(
            pool_name="image-4k",
            file_name="image-4k-001.dat",
            file_size_bytes=_DEFAULT_4K_SLOT_SIZE_BYTES * _DEFAULT_4K_SLOT_COUNT,
            slot_size_bytes=_DEFAULT_4K_SLOT_SIZE_BYTES,
        )
    raise ValueError("LocalBufferBroker default_pool_name 只支持 image-small、image-1080p 或 image-4k")