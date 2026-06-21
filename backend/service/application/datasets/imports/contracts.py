"""数据集导入解析结果对象。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from backend.service.domain.datasets.dataset_import import (
    DatasetFormatType,
    DatasetImport,
    DatasetImportRequestedSplitStrategy,
    DatasetImportTaskType,
)
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DatasetVersion,
)


@dataclass(frozen=True)
class DatasetImportRequest:
    """描述一次数据集 zip 导入请求。

    字段：
    - project_id：所属 Project id。
    - dataset_id：所属 Dataset id。
    - package_file_name：上传 zip 文件名。
    - package_bytes：上传 zip 文件内容；直接走 service 调用时可传入。
    - format_type：显式指定的数据集格式；为空时自动识别。
    - task_type：任务类型。
    - split_strategy：显式指定的 split 策略。
    - class_map：显式指定的类别映射。
    - metadata：附加元数据。
    """

    project_id: str
    dataset_id: str
    package_file_name: str
    task_type: DatasetImportTaskType
    package_bytes: bytes | None = None
    format_type: DatasetFormatType | None = None
    split_strategy: DatasetImportRequestedSplitStrategy | None = None
    class_map: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DatasetImportResult:
    """描述一次数据集导入的结果。

    字段：
    - dataset_import：最终保存的 DatasetImport 记录。
    - dataset_version：导入生成的 DatasetVersion。
    - sample_count：样本总数。
    - category_count：类别总数。
    - split_names：导入后包含的 split 列表。
    """

    dataset_import: DatasetImport
    dataset_version: DatasetVersion
    sample_count: int
    category_count: int
    split_names: tuple[str, ...]


@dataclass(frozen=True)
class ParsedDatasetSample:
    """描述已解析但尚未写入版本目录的样本内容。

    字段：
    - sample：平台内部 DatasetSample 对象。
    - source_image_path：原始导入内容中的图片路径。
    - source_image_ref：相对数据集根目录的图片路径。
    """

    sample: DatasetSample
    source_image_path: Path
    source_image_ref: str


@dataclass(frozen=True)
class ParsedDatasetContent:
    """描述一次导入解析后的统一结果。

    字段：
    - format_type：识别后的数据集格式。
    - task_type：识别后的任务类型。
    - image_root：识别出的图片根路径。
    - annotation_root：识别出的标注根路径。
    - manifest_file：识别出的 manifest 文件路径。
    - split_strategy：当前导入使用的 split 策略。
    - class_map：归一化后的类别映射。
    - categories：归一化后的类别列表。
    - samples：归一化后的样本列表。
    - detected_profile：格式识别结果和目录签名。
    - validation_report：结构化校验结果。
    """

    format_type: DatasetFormatType
    task_type: DatasetImportTaskType
    image_root: str
    annotation_root: str
    manifest_file: str | None
    split_strategy: str
    class_map: dict[str, str]
    categories: tuple[DatasetCategory, ...]
    samples: tuple[ParsedDatasetSample, ...]
    detected_profile: dict[str, object]
    validation_report: dict[str, object]
