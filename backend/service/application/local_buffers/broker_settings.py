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
    - slot_size_bytes：单个固定槽位容量。
    - slot_count：固定槽位数量。
    - flush_on_write：写入后是否强制 flush 到 mmap 文件；默认关闭以避免临时图片输入刷盘。
    - file_name：pool 对应的 mmap 文件名；为空时按 pool_name 自动生成。
    - file_size_bytes：单个 pool 文件总容量；为空时按 slot_size_bytes * slot_count 自动计算。
    """

    pool_name: str = "image-1080p"
    slot_size_bytes: int = _DEFAULT_1080P_SLOT_SIZE_BYTES
    slot_count: int = _DEFAULT_1080P_SLOT_COUNT
    flush_on_write: bool = False
    file_name: str = ""
    file_size_bytes: int = 0

    @model_validator(mode="after")
    def validate_pool_settings(self) -> LocalBufferBrokerPoolSettings:
        """校验并补齐 pool 派生字段。"""

        normalized_pool_name = self.pool_name.strip()
        if not normalized_pool_name:
            raise ValueError("LocalBufferBroker pool_name 不能为空")
        self.pool_name = normalized_pool_name
        self.file_name = self.file_name.strip() or f"{normalized_pool_name}-001.dat"
        if self.slot_size_bytes <= 0:
            raise ValueError("LocalBufferBroker slot_size_bytes 必须大于 0")
        if self.slot_count <= 0:
            raise ValueError("LocalBufferBroker slot_count 必须大于 0")

        if self.file_size_bytes <= 0:
            self.file_size_bytes = self.slot_size_bytes * self.slot_count
            return self

        if self.file_size_bytes % self.slot_size_bytes != 0:
            raise ValueError("LocalBufferBroker file_size_bytes 必须是 slot_size_bytes 的整数倍")
        file_size_slot_count = self.file_size_bytes // self.slot_size_bytes
        if "slot_count" in self.model_fields_set and self.slot_count != file_size_slot_count:
            raise ValueError("LocalBufferBroker slot_count 与 file_size_bytes 不一致")
        self.slot_count = file_size_slot_count
        return self


class LocalBufferBrokerSettings(BaseModel):
    """描述 LocalBufferBroker companion process 配置。

    字段：
    - enabled：是否随 backend-service 启动 broker 进程。
    - root_dir：broker 管理的 mmap 文件根目录。
    - startup_timeout_seconds：等待 broker 启动完成的最长秒数。
    - request_timeout_seconds：单次控制请求等待响应的最长秒数。
    - shutdown_timeout_seconds：等待 broker 优雅退出的最长秒数。
    - expire_interval_seconds：周期性触发过期 lease 回收的间隔秒数；小于等于 0 表示关闭循环。
    - default_pool：常用单 pool 配置；正式部署通常只需要改这个对象。
    - default_pool_name：未显式指定 pool_name 时使用的默认 pool。
    - pools：高级多 pool 配置；需要多个 pool 时使用，并配套 default_pool_name。
    """

    enabled: bool = True
    root_dir: str = "./data/buffers"
    startup_timeout_seconds: float = 5.0
    request_timeout_seconds: float = 5.0
    shutdown_timeout_seconds: float = 5.0
    expire_interval_seconds: float = 5.0
    default_pool: LocalBufferBrokerPoolSettings | None = None
    default_pool_name: str = "image-1080p"
    pools: tuple[LocalBufferBrokerPoolSettings, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def validate_settings(self) -> LocalBufferBrokerSettings:
        """校验并补齐 LocalBufferBroker pool 配置。

        返回：
        - LocalBufferBrokerSettings：已补齐内置 pool preset 的配置。
        """

        if self.default_pool is not None:
            if self.pools:
                raise ValueError("LocalBufferBroker default_pool 和 pools 不能同时配置")
            self.default_pool_name = self.default_pool.pool_name
            self.pools = (self.default_pool,)

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
            slot_size_bytes=_DEFAULT_SMALL_SLOT_SIZE_BYTES,
            slot_count=_DEFAULT_SMALL_SLOT_COUNT,
        )
    if pool_name == "image-1080p":
        return LocalBufferBrokerPoolSettings()
    if pool_name == "image-4k":
        return LocalBufferBrokerPoolSettings(
            pool_name="image-4k",
            slot_size_bytes=_DEFAULT_4K_SLOT_SIZE_BYTES,
            slot_count=_DEFAULT_4K_SLOT_COUNT,
        )
    raise ValueError("LocalBufferBroker default_pool_name 只支持 image-small、image-1080p 或 image-4k")
