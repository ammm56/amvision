"""DatasetExport 对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.contracts.datasets.exports.dataset_formats import DatasetExportFormatId
from backend.service.domain.datasets.dataset_version import DatasetTaskType


# 数据集导出记录的最小状态集合。
DatasetExportStatus = Literal["queued", "running", "completed", "failed"]


@dataclass(frozen=True)
class DatasetExport:
    """描述一次 DatasetExport 资源记录。

    字段：
    - dataset_export_id：导出记录 id。
    - dataset_id：所属 Dataset id。
    - project_id：所属 Project id。
    - dataset_version_id：导出来源的 DatasetVersion id。
    - format_id：目标导出格式 id。
    - task_type：导出对应的任务类型。
    - status：当前导出状态。
    - created_at：创建时间。
    - task_id：关联的 TaskRecord id。
    - include_test_split：是否包含 test split。
    - export_path：导出根目录 object key。
    - manifest_object_key：导出 manifest 的 object key。
    - split_names：导出产生的 split 列表。
    - sample_count：导出样本总数。
    - category_names：导出类别名列表。
    - error_message：失败时的错误消息。
    - metadata：附加元数据。
    """

    dataset_export_id: str
    dataset_id: str
    project_id: str
    dataset_version_id: str
    format_id: DatasetExportFormatId
    task_type: DatasetTaskType = "detection"
    status: DatasetExportStatus = "queued"
    created_at: str = ""
    task_id: str | None = None
    include_test_split: bool = True
    export_path: str | None = None
    manifest_object_key: str | None = None
    split_names: tuple[str, ...] = ()
    sample_count: int = 0
    category_names: tuple[str, ...] = ()
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)