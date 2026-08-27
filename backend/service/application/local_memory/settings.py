"""LocalBuffer 与 LocalMessage 平行消费的中立共享根配置。"""

from __future__ import annotations

from pydantic import BaseModel, model_validator


class LocalMemorySettings(BaseModel):
    """只定义受信 buffers root，不拥有 enable、进程或 Channel 生命周期。"""

    root_dir: str = "./data/buffers"

    @model_validator(mode="after")
    def validate_root_dir(self) -> LocalMemorySettings:
        """规范化并拒绝空 root。"""

        self.root_dir = self.root_dir.strip()
        if not self.root_dir:
            raise ValueError("local_memory.root_dir 不能为空")
        return self
