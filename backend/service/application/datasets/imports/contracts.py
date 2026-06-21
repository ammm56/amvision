"""数据集导入解析结果对象。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from backend.service.domain.datasets.dataset_import import DatasetFormatType, DatasetImportTaskType
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
)


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
