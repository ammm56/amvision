"""点云 I/O 显式预算；未提供策略不启用，测试值不成为生产默认。"""

from typing import Annotated

from pydantic import Field, model_validator

from backend.contracts.workflows.metrology import Contract


BytesLimit = Annotated[int, Field(strict=True, gt=0, le=2**53 - 1)]


class PointCloudIoPolicy(Contract):
    """解码、临时工作区和分块上限；不冒充整个进程 RSS 硬限制。"""

    max_header_bytes: BytesLimit
    max_decoded_bytes: BytesLimit
    max_working_bytes: BytesLimit
    chunk_rows: BytesLimit
    chunk_bytes: BytesLimit
    max_live_array_bytes: BytesLimit

    @model_validator(mode="after")
    def check_capacity(self):
        """单次允许的解码数组必须能被运行内活跃数组预算容纳。"""
        if self.max_decoded_bytes > self.max_live_array_bytes:
            raise ValueError("max_decoded_bytes 不得超过 max_live_array_bytes")
        if self.chunk_bytes > self.max_working_bytes:
            raise ValueError("chunk_bytes 不得超过 max_working_bytes")
        return self
