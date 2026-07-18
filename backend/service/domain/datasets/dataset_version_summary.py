"""DatasetVersion 列表使用的轻量只读摘要。"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DatasetVersionSummary:
    """描述不加载 samples 和 annotations 的 DatasetVersion 摘要。"""

    dataset_version_id: str
    dataset_id: str
    project_id: str
    task_type: str
    sample_count: int
    category_count: int
    split_names: tuple[str, ...]
    metadata: dict[str, object] = field(default_factory=dict)


__all__ = ["DatasetVersionSummary"]
