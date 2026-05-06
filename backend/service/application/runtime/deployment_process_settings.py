"""deployment 进程监督器共享配置。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeploymentProcessSupervisorConfig(BaseModel):
    """描述 deployment 进程监督器配置。

    字段：
    - auto_restart：deployment 进程异常退出后是否自动拉起。
    - monitor_interval_seconds：监督线程巡检 deployment 进程状态的间隔秒数。
    - request_timeout_seconds：父进程等待子进程返回控制面或推理结果的最长秒数。
    - shutdown_timeout_seconds：停止 deployment 进程时等待优雅退出的最长秒数。
    - operator_thread_count：deployment 子进程内部推理库允许使用的算子线程数。
    - warmup_dummy_inference_count：显式 warmup 时追加执行的 dummy infer 次数。
    - warmup_dummy_image_size：dummy infer 使用的最小图片尺寸，格式为 width、height 二元组。
    - keep_warm_enabled：是否默认启用 keep-warm 后台线程。
    - keep_warm_interval_seconds：keep-warm 连续 dummy infer 的最小间隔秒数。
    - keep_warm_yield_timeout_seconds：真实请求等待 keep-warm 当前一轮 dummy infer 让出的最长秒数。
    - tensorrt_pinned_output_buffer_enabled：TensorRT 输出 host buffer 是否默认启用 pinned memory。
    - tensorrt_pinned_output_buffer_max_bytes：允许使用 pinned output host buffer 的最大字节数；超过后自动回退 pageable memory。
    """

    auto_restart: bool = True
    monitor_interval_seconds: float = 0.5
    request_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 5.0
    operator_thread_count: int = 1
    warmup_dummy_inference_count: int = Field(default=6, ge=0)
    warmup_dummy_image_size: tuple[int, int] = (64, 64)
    keep_warm_enabled: bool = False
    keep_warm_interval_seconds: float = Field(default=0.1, gt=0.0)
    keep_warm_yield_timeout_seconds: float = Field(default=1.0, gt=0.0)
    tensorrt_pinned_output_buffer_enabled: bool = True
    tensorrt_pinned_output_buffer_max_bytes: int = Field(default=8 * 1024 * 1024, ge=0)