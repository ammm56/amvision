"""数据集导入格式识别逻辑。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.errors import (
    InvalidRequestError,
    UnsupportedDatasetFormatError,
)
from backend.service.domain.datasets.dataset_import import (
    DatasetFormatType,
    DatasetImportTaskType,
    IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE,
)


class DatasetImportFormatDetectorMixin:
    """按格式拆分的数据集导入解析逻辑。"""

    def _detect_format(
        self,
        *,
        dataset_root: Path,
        requested_format_type: DatasetFormatType | None,
        task_type: DatasetImportTaskType,
    ) -> DatasetFormatType:
        """根据目录签名识别导入内容格式。

        参数：
        - dataset_root：解压后的数据集根目录。
        - requested_format_type：显式指定的格式类型。
        - task_type：当前导入请求的任务类型。

        返回：
        - 识别出的格式类型。
        """

        candidates: list[DatasetFormatType] = []
        if self._collect_coco_manifest_paths(dataset_root):
            candidates.append("coco")

        if self._looks_like_voc_dataset(dataset_root):
            candidates.append("voc")
        if self._looks_like_yolo_dataset(dataset_root):
            candidates.append("yolo")
        if self._looks_like_imagenet_dataset(dataset_root):
            candidates.append("imagenet")
        if self._looks_like_dota_dataset(dataset_root):
            candidates.append("dota")

        supported_format_types = IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE[task_type]
        supported_candidates = [
            candidate for candidate in candidates if candidate in supported_format_types
        ]
        task_exclusive_mismatches: list[DatasetFormatType] = []
        if "imagenet" in candidates and task_type != "classification":
            task_exclusive_mismatches.append("imagenet")
        if "dota" in candidates and task_type != "obb":
            task_exclusive_mismatches.append("dota")

        if requested_format_type is not None:
            if requested_format_type not in candidates:
                raise InvalidRequestError(
                    "导入包结构与 format_type 不匹配",
                    details={
                        "format_type": requested_format_type,
                        "detected_candidates": candidates,
                    },
                )
            return requested_format_type

        if task_exclusive_mismatches:
            raise InvalidRequestError(
                "导入包识别结果与 task_type 不匹配",
                details={
                    "task_type": task_type,
                    "detected_candidates": task_exclusive_mismatches,
                    "supported_format_types": list(supported_format_types),
                },
            )
        if len(supported_candidates) == 1:
            return supported_candidates[0]
        if len(supported_candidates) > 1:
            raise InvalidRequestError(
                "导入包命中了多个候选格式，需要显式指定 format_type",
                details={
                    "task_type": task_type,
                    "detected_candidates": supported_candidates,
                    "supported_format_types": list(supported_format_types),
                },
            )
        if not candidates:
            raise UnsupportedDatasetFormatError(
                "当前只支持 COCO、Pascal VOC、YOLO、ImageNet classification 和 DOTA OBB",
                details={"dataset_root": str(dataset_root)},
            )

        raise InvalidRequestError(
            "导入包识别结果与 task_type 不匹配",
            details={
                "task_type": task_type,
                "detected_candidates": candidates,
                "supported_format_types": list(supported_format_types),
            },
        )
