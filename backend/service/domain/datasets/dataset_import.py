"""DatasetImport 对象定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from backend.service.domain.datasets.dataset_version import DatasetTaskType


# 当前支持的数据集导入格式类型。
DatasetFormatType = Literal["coco", "voc"]


# 数据集导入记录的最小状态集合。
DatasetImportStatus = Literal["received", "extracted", "validated", "completed", "failed"]


@dataclass(frozen=True)
class DatasetImport:
    """描述一次数据集 zip 导入记录。

    字段：
    - dataset_import_id：导入记录 id。
    - dataset_id：所属 Dataset id。
    - project_id：所属 Project id。
    - format_type：导入格式类型；未确认前可以为空。
    - task_type：任务类型。
    - status：当前导入状态。
    - created_at：导入记录创建时间。
    - dataset_version_id：导入成功后生成的 DatasetVersion id。
    - package_path：原始 zip 包保存路径。
    - staging_path：解压后的 staging 目录路径。
    - version_path：生成版本后的目录路径。
    - image_root：识别出的图片根目录。
    - annotation_root：识别出的标注根目录。
    - manifest_file：识别出的 manifest 文件路径。
    - split_strategy：当前导入使用的 split 策略。
    - class_map：当前导入记录使用的类别映射。
    - detected_profile：格式识别结果和目录签名。
    - validation_report：结构化校验结果。
    - error_message：导入失败时的错误消息。
    - metadata：附加元数据。
    """

    dataset_import_id: str
    dataset_id: str
    project_id: str
    format_type: DatasetFormatType | None = None
    task_type: DatasetTaskType = "detection"
    status: DatasetImportStatus = "received"
    created_at: str = ""
    dataset_version_id: str | None = None
    package_path: str = ""
    staging_path: str = ""
    version_path: str | None = None
    image_root: str | None = None
    annotation_root: str | None = None
    manifest_file: str | None = None
    split_strategy: str | None = None
    class_map: dict[str, str] = field(default_factory=dict)
    detected_profile: dict[str, object] = field(default_factory=dict)
    validation_report: dict[str, object] = field(default_factory=dict)
    error_message: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)