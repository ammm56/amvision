"""数据集导入服务的通用支撑函数。"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from xml.etree import ElementTree

from PIL import Image

from backend.service.application.datasets.imports.contracts import ParsedDatasetContent
from backend.service.application.datasets.imports.contracts import ParsedDatasetSample
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_import import (
    DatasetImportRequestedSplitStrategy,
)
from backend.service.domain.datasets.dataset_version import DatasetSplitName


class DatasetImportSupportMixin:
    """提供格式 parser 共用的路径、图片和字段读取能力。"""

    def _resolve_requested_split(
        self,
        split_strategy: DatasetImportRequestedSplitStrategy | None,
    ) -> DatasetSplitName | None:
        """把请求中的 split_strategy 转换为强制 split。"""

        if split_strategy in (None, "auto"):
            return None
        return split_strategy

    def _resolve_effective_split_strategy(
        self,
        forced_split: DatasetSplitName | None,
        *,
        auto_strategy: str,
    ) -> str:
        """计算最终写回 DatasetImport 的 split 策略标记。"""

        if forced_split is None:
            return auto_strategy
        return f"forced-{forced_split}"

    def _unwrap_single_directory(self, extracted_root: Path) -> Path:
        """连续消除 zip 中的单目录包裹层级。"""

        current_root = extracted_root
        while True:
            children = list(current_root.iterdir())
            if len(children) != 1 or not children[0].is_dir():
                return current_root
            current_root = children[0]

    def _normalize_split_name(
        self,
        raw_split_name: str | None,
        *,
        default: DatasetSplitName,
    ) -> DatasetSplitName:
        """把输入的 split 名称归一化为 train、val、test。"""

        if raw_split_name is None or not raw_split_name.strip():
            return default
        normalized_name = raw_split_name.strip().lower()
        if "train" in normalized_name:
            return "train"
        if "val" in normalized_name or "valid" in normalized_name:
            return "val"
        if "test" in normalized_name:
            return "test"
        return default

    def _normalize_relative_file_name(self, file_name: str) -> str:
        """校验并归一化相对文件名。"""

        normalized_path = PurePosixPath(file_name.replace("\\", "/"))
        if (
            normalized_path.is_absolute()
            or ".." in normalized_path.parts
            or not normalized_path.name
        ):
            raise InvalidRequestError(
                "数据集中存在非法文件路径",
                details={"file_name": file_name},
            )
        return str(normalized_path)

    def _relative_path(self, base_path: Path, target_path: Path) -> str:
        """把目标路径转换为相对基准目录的 POSIX 路径。"""

        return target_path.relative_to(base_path).as_posix()

    def _relative_path_from_any(
        self,
        target_path: Path,
        *base_paths: Path,
    ) -> str:
        """按顺序尝试多个基准目录，返回第一个可用的相对路径。"""

        for base_path in base_paths:
            try:
                return self._relative_path(base_path, target_path)
            except ValueError:
                continue
        return target_path.as_posix()

    def _collect_split_counts(
        self,
        parsed_samples: tuple[ParsedDatasetSample, ...] | list[ParsedDatasetSample],
    ) -> dict[str, int]:
        """统计每个 split 的样本数量。"""

        split_counts: dict[str, int] = {"train": 0, "val": 0, "test": 0}
        for parsed_sample in parsed_samples:
            split_counts[parsed_sample.sample.split] += 1
        return {
            split_name: count
            for split_name, count in split_counts.items()
            if count > 0
        }

    def _collect_split_names(
        self,
        parsed_samples: tuple[ParsedDatasetSample, ...] | list[ParsedDatasetSample],
    ) -> tuple[str, ...]:
        """按固定顺序收集样本中出现的 split 名称。"""

        present_splits = {parsed_sample.sample.split for parsed_sample in parsed_samples}
        return tuple(
            split_name
            for split_name in ("train", "val", "test")
            if split_name in present_splits
        )

    def _is_image_file(self, file_path: Path) -> bool:
        """判断文件是否是常见图片格式。"""

        return file_path.is_file() and file_path.suffix.lower() in {
            ".jpg",
            ".jpeg",
            ".png",
            ".bmp",
            ".webp",
            ".tif",
            ".tiff",
        }

    def _read_image_size(self, image_path: Path) -> tuple[int, int]:
        """读取图片宽高。"""

        with Image.open(image_path) as image:
            width, height = image.size
        return int(width), int(height)

    def _common_path_prefix(self, relative_paths: list[str]) -> str:
        """计算一组相对路径的公共目录前缀。"""

        if not relative_paths:
            return "."
        common_parts = list(PurePosixPath(relative_paths[0]).parts[:-1])
        for relative_path in relative_paths[1:]:
            path_parts = list(PurePosixPath(relative_path).parts[:-1])
            new_common_parts: list[str] = []
            for left_part, right_part in zip(common_parts, path_parts):
                if left_part != right_part:
                    break
                new_common_parts.append(left_part)
            common_parts = new_common_parts
            if not common_parts:
                return "."
        if not common_parts:
            return "."
        return str(PurePosixPath(*common_parts))

    def _read_bbox_xywh(self, bbox_payload: object) -> tuple[float, float, float, float]:
        """读取 COCO bbox 并校验其格式。"""

        if not isinstance(bbox_payload, list) or len(bbox_payload) != 4:
            raise InvalidRequestError("COCO bbox 必须是长度为 4 的数组")
        bbox_xywh = tuple(float(value) for value in bbox_payload)
        if bbox_xywh[2] <= 0 or bbox_xywh[3] <= 0:
            raise InvalidRequestError("COCO bbox 必须是正面积框")
        return bbox_xywh

    def _read_int(
        self,
        payload: dict[str, object],
        key: str,
        error_message: str,
    ) -> int:
        """从字典对象中读取整数值。"""

        raw_value = payload.get(key)
        if raw_value is None:
            raise InvalidRequestError(error_message)
        return int(raw_value)

    def _read_xml_int(
        self,
        xml_node: ElementTree.Element,
        key: str,
        error_message: str,
    ) -> int:
        """从 XML 节点中读取整数值。"""

        raw_text = (xml_node.findtext(key) or "").strip()
        if not raw_text:
            raise InvalidRequestError(error_message)
        return int(raw_text)

    def _read_voc_optional_flag(
        self,
        xml_node: ElementTree.Element,
        key: str,
    ) -> int:
        """读取 Pascal VOC 可选整数标记，非整数值按 0 处理。"""

        raw_text = (xml_node.findtext(key) or "").strip()
        if not raw_text:
            return 0
        try:
            return int(raw_text)
        except ValueError:
            return 0

    def _category_sort_key(self, category_id: str) -> tuple[int, object]:
        """为类别 id 提供稳定排序键。"""

        return (0, int(category_id)) if category_id.isdigit() else (1, category_id)

    def _build_import_log(
        self,
        *,
        dataset_import_id: str,
        dataset_version_id: str,
        parsed_content: ParsedDatasetContent,
    ) -> str:
        """构建导入日志文本。"""

        split_counts = self._collect_split_counts(parsed_content.samples)
        return (
            f"dataset_import_id={dataset_import_id}\n"
            f"dataset_version_id={dataset_version_id}\n"
            f"status=completed\n"
            f"format_type={parsed_content.format_type}\n"
            f"task_type={parsed_content.task_type}\n"
            f"sample_count={len(parsed_content.samples)}\n"
            f"category_count={len(parsed_content.categories)}\n"
            f"split_counts={json.dumps(split_counts, ensure_ascii=False)}\n"
        )
