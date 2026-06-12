"""转换结果文件读取快照。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConversionResultSnapshot:
    """描述转换结果文件的公开读取快照。

    字段：
    - file_status：结果文件状态。
    - task_state：任务当前状态。
    - object_key：结果文件 object key。
    - payload：结果 JSON 内容。
    """

    file_status: str
    task_state: str
    object_key: str | None
    payload: dict[str, object] = field(default_factory=dict)
