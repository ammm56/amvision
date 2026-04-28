"""数据集导出格式定义。"""

from __future__ import annotations

from typing import Final, Literal


# 当前规划支持的数据集导出格式 id。
DatasetExportFormatId = Literal[
    "yolo-detection-v1",
    "yolo-instance-seg-v1",
    "yolo-pose-v1",
    "coco-detection-v1",
    "coco-instance-seg-v1",
    "coco-keypoints-v1",
    "semantic-mask-dir-v1",
    "sam-promptable-seg-v1",
]


# 当前规划支持的全部数据集导出格式。
SUPPORTED_DATASET_EXPORT_FORMATS: Final[tuple[DatasetExportFormatId, ...]] = (
    "yolo-detection-v1",
    "yolo-instance-seg-v1",
    "yolo-pose-v1",
    "coco-detection-v1",
    "coco-instance-seg-v1",
    "coco-keypoints-v1",
    "semantic-mask-dir-v1",
    "sam-promptable-seg-v1",
)