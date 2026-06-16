"""YOLOX core 使用的 COCO detection 数据集。"""

from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import dataclass
import io
import json
from pathlib import Path, PurePosixPath
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class ResolvedCocoSplit:
    """描述一个已经解析到本地文件系统的 COCO split。"""

    name: str
    image_root: Path
    annotation_file: Path
    sample_count: int


@dataclass(frozen=True)
class ResolvedCocoSample:
    """描述一个 COCO detection 训练样本。"""

    image_path: Path
    width: int
    height: int
    image_id: int
    boxes_xyxy_with_class: list[tuple[float, float, float, float, float]]


class CocoDetectionExportDataset:
    """从 `coco-detection-v1` DatasetExport 读取 YOLOX 训练样本。"""

    def __init__(
        self,
        *,
        annotation_file: Path,
        image_root: Path,
        input_size: tuple[int, int],
        imports: Any,
        flip_prob: float,
        hsv_prob: float,
        max_labels: int,
    ) -> None:
        """初始化 DatasetExport COCO 数据集。"""

        self.annotation_file = annotation_file
        self.image_root = image_root
        self.input_size = input_size
        self._input_dim = tuple(input_size)
        self.imports = imports
        self.preproc = imports.TrainTransform(
            max_labels=max_labels,
            flip_prob=flip_prob,
            hsv_prob=hsv_prob,
        )

        payload = json.loads(annotation_file.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise InvalidRequestError(
                "COCO annotation 文件内容不合法",
                details={"annotation_file": annotation_file.as_posix()},
            )

        categories_payload = payload.get("categories", [])
        images_payload = payload.get("images", [])
        annotations_payload = payload.get("annotations", [])
        if not isinstance(categories_payload, list):
            raise InvalidRequestError("COCO categories 必须是数组")
        if not isinstance(images_payload, list):
            raise InvalidRequestError("COCO images 必须是数组")
        if not isinstance(annotations_payload, list):
            raise InvalidRequestError("COCO annotations 必须是数组")

        self.category_names = tuple(
            str(category_item.get("name", "")).strip()
            for category_item in categories_payload
            if isinstance(category_item, dict) and str(category_item.get("name", "")).strip()
        )
        self.category_ids = tuple(
            int(category_item.get("id"))
            for category_item in categories_payload
            if isinstance(category_item, dict) and isinstance(category_item.get("id"), int)
        )
        category_id_to_index = self._build_category_id_to_index(categories_payload)
        annotations_by_image_id = self._build_annotations_by_image_id(
            annotations_payload,
            category_id_to_index,
        )
        self.samples = self._build_samples(images_payload, annotations_by_image_id)

    def __len__(self) -> int:
        """返回样本数量。"""

        return len(self.samples)

    @property
    def input_dim(self) -> tuple[int, int]:
        """返回当前输入尺寸。"""

        return tuple(self._input_dim)

    def set_input_dim(self, input_dim: tuple[int, int]) -> None:
        """更新后续样本预处理输入尺寸。"""

        self._input_dim = tuple(input_dim)

    def load_anno(self, index: int) -> object:
        """读取单个样本的 xyxy + class 标注。"""

        sample = self.samples[index]
        if not sample.boxes_xyxy_with_class:
            return self.imports.np.zeros((0, 5), dtype=self.imports.np.float32)
        return self.imports.np.array(sample.boxes_xyxy_with_class, dtype=self.imports.np.float32)

    def pull_item(self, index: int) -> tuple[object, object, tuple[int, int], int]:
        """读取未经 TrainTransform 处理的原始图片和标注。"""

        sample = self.samples[index]
        image = self.imports.cv2.imread(str(sample.image_path))
        if image is None:
            raise InvalidRequestError(
                "训练图片读取失败",
                details={"image_path": sample.image_path.as_posix()},
            )

        targets = self.load_anno(index)
        return image, targets, (sample.height, sample.width), sample.image_id

    def __getitem__(self, index: object) -> tuple[object, object, tuple[int, int], int]:
        """读取样本并执行 YOLOX TrainTransform。"""

        if not isinstance(index, int):
            if isinstance(index, list | tuple) and len(index) >= 2:
                if len(index) > 2 and index[2] is not None:
                    self.set_input_dim(tuple(index[2]))
                index = int(index[1])
            else:
                raise TypeError("训练样本索引必须是 int 或携带输入尺寸的采样器元组")

        image, targets, image_info, image_id = self.pull_item(index)
        transformed_image, transformed_targets = self.preproc(image, targets, self.input_dim)
        return transformed_image, transformed_targets, image_info, image_id

    def _build_category_id_to_index(self, categories_payload: list[object]) -> dict[int, int]:
        """构建 COCO category_id 到连续类别索引的映射。"""

        category_id_to_index: dict[int, int] = {}
        for category_index, category_item in enumerate(categories_payload):
            if not isinstance(category_item, dict):
                continue
            raw_category_id = category_item.get("id")
            if not isinstance(raw_category_id, int):
                raise InvalidRequestError("COCO category.id 必须是整数")
            category_id_to_index[raw_category_id] = category_index

        if not category_id_to_index:
            raise InvalidRequestError("训练输入缺少有效的 categories")
        return category_id_to_index

    def _build_annotations_by_image_id(
        self,
        annotations_payload: list[object],
        category_id_to_index: dict[int, int],
    ) -> dict[int, list[tuple[float, float, float, float, float]]]:
        """把 COCO annotations 按 image_id 分组。"""

        annotations_by_image_id: dict[int, list[tuple[float, float, float, float, float]]] = {}
        for annotation_item in annotations_payload:
            if not isinstance(annotation_item, dict):
                continue
            raw_image_id = annotation_item.get("image_id")
            raw_category_id = annotation_item.get("category_id")
            raw_bbox = annotation_item.get("bbox")
            if not isinstance(raw_image_id, int):
                raise InvalidRequestError("COCO annotation.image_id 必须是整数")
            if not isinstance(raw_category_id, int):
                raise InvalidRequestError("COCO annotation.category_id 必须是整数")
            if raw_category_id not in category_id_to_index:
                raise InvalidRequestError(
                    "COCO annotation 引用了未定义的 category_id",
                    details={"category_id": raw_category_id},
                )
            if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
                raise InvalidRequestError("COCO annotation.bbox 必须是长度为 4 的数组")

            x, y, width, height = (float(value) for value in raw_bbox)
            if width <= 0 or height <= 0:
                continue
            annotations_by_image_id.setdefault(raw_image_id, []).append(
                (
                    x,
                    y,
                    x + width,
                    y + height,
                    float(category_id_to_index[raw_category_id]),
                )
            )

        return annotations_by_image_id

    def _build_samples(
        self,
        images_payload: list[object],
        annotations_by_image_id: dict[int, list[tuple[float, float, float, float, float]]],
    ) -> tuple[ResolvedCocoSample, ...]:
        """把 COCO images 与 annotations 整理成训练样本。"""

        samples: list[ResolvedCocoSample] = []
        for image_item in images_payload:
            if not isinstance(image_item, dict):
                continue
            raw_image_id = image_item.get("id")
            raw_file_name = image_item.get("file_name")
            raw_width = image_item.get("width")
            raw_height = image_item.get("height")
            if not isinstance(raw_image_id, int):
                raise InvalidRequestError("COCO image.id 必须是整数")
            if not isinstance(raw_file_name, str) or not raw_file_name.strip():
                raise InvalidRequestError("COCO image.file_name 不能为空")
            if not isinstance(raw_width, int) or raw_width <= 0:
                raise InvalidRequestError("COCO image.width 必须是正整数")
            if not isinstance(raw_height, int) or raw_height <= 0:
                raise InvalidRequestError("COCO image.height 必须是正整数")

            image_path = self.image_root.joinpath(*PurePosixPath(raw_file_name).parts)
            if not image_path.is_file():
                raise InvalidRequestError(
                    "训练图片不存在",
                    details={"image_path": image_path.as_posix()},
                )

            samples.append(
                ResolvedCocoSample(
                    image_path=image_path,
                    width=raw_width,
                    height=raw_height,
                    image_id=raw_image_id,
                    boxes_xyxy_with_class=list(annotations_by_image_id.get(raw_image_id, [])),
                )
            )

        if not samples:
            raise InvalidRequestError("训练输入缺少有效图片样本")
        return tuple(samples)


def resolve_coco_splits(
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[ResolvedCocoSplit, ...]:
    """从 `coco-detection-v1` manifest 解析本地 split 路径。"""

    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("训练输入 manifest 缺少 splits 定义")

    resolved_splits: list[ResolvedCocoSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name", "")).strip()
        image_root = str(split_item.get("image_root", "")).strip()
        annotation_file = str(split_item.get("annotation_file", "")).strip()
        sample_count = split_item.get("sample_count", 0)
        if not split_name or not image_root or not annotation_file:
            continue
        resolved_splits.append(
            ResolvedCocoSplit(
                name=split_name,
                image_root=dataset_storage.resolve(image_root),
                annotation_file=dataset_storage.resolve(annotation_file),
                sample_count=sample_count if isinstance(sample_count, int) else 0,
            )
        )

    if not resolved_splits:
        raise InvalidRequestError("训练输入 manifest 中没有可用的 split")
    return tuple(resolved_splits)


def resolve_train_split(resolved_splits: tuple[ResolvedCocoSplit, ...]) -> ResolvedCocoSplit:
    """优先选择 train split，缺失时回退第一个 split。"""

    for split in resolved_splits:
        if split.name == "train":
            return split
    return resolved_splits[0]


def resolve_validation_split(
    resolved_splits: tuple[ResolvedCocoSplit, ...],
    *,
    train_split_name: str,
) -> ResolvedCocoSplit | None:
    """优先选择 val / valid / validation / test 作为验证 split。"""

    preferred_validation_names = ("val", "valid", "validation", "test")
    for preferred_name in preferred_validation_names:
        for split in resolved_splits:
            if split.name == preferred_name and split.name != train_split_name:
                return split

    for split in resolved_splits:
        if split.name != train_split_name:
            return split

    return None


def load_coco_ground_truth_silently(*, coco_class: Any, annotation_file: Path) -> Any:
    """静默加载 COCO ground truth，避免 pycocotools 默认打印索引日志。"""

    with redirect_stdout(io.StringIO()):
        return coco_class(str(annotation_file))
