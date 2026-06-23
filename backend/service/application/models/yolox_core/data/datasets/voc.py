"""YOLOX core 使用的 VOC annotation 解析工具。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET
from typing import Any

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


@dataclass(frozen=True)
class ParsedVocAnnotation:
    """描述一个 VOC annotation 文件的检测标注。"""

    width: int
    height: int
    file_name: str | None
    boxes_xyxy_with_class: tuple[tuple[float, float, float, float, float], ...]


@dataclass(frozen=True)
class ParsedVocObject:
    """描述一个 VOC object 标注。"""

    name: str
    difficult: bool
    bbox_xyxy: tuple[float, float, float, float]


@dataclass(frozen=True)
class ResolvedVocSplit:
    """描述一个已经解析到本地文件系统的 VOC split。"""

    name: str
    image_root: Path
    annotation_root: Path
    image_set_file: Path
    sample_count: int
    category_names: tuple[str, ...]


@dataclass(frozen=True)
class ResolvedVocSample:
    """描述一个 VOC detection 训练样本。"""

    image_path: Path
    annotation_file: Path
    width: int
    height: int
    image_id: int
    sample_id: str
    boxes_xyxy_with_class: list[tuple[float, float, float, float, float]]


class VocDetectionExportDataset:
    """从 `voc-detection-v1` DatasetExport 读取 YOLOX 训练样本。"""

    def __init__(
        self,
        *,
        split: ResolvedVocSplit,
        input_size: tuple[int, int],
        imports: Any,
        flip_prob: float,
        hsv_prob: float,
        max_labels: int,
    ) -> None:
        """初始化 DatasetExport VOC 数据集。"""

        self.split = split
        self.input_size = input_size
        self._input_dim = tuple(input_size)
        self.imports = imports
        self.preproc = imports.TrainTransform(
            max_labels=max_labels,
            flip_prob=flip_prob,
            hsv_prob=hsv_prob,
        )
        self.category_names = tuple(split.category_names)
        self.category_ids = tuple(range(len(self.category_names)))
        self.samples = self._build_samples()

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

    def read_voc_objects(self, annotation_file: Path) -> tuple[ParsedVocObject, ...]:
        """读取原生 VOC object 标注。"""

        return read_voc_annotation_objects(annotation_file=annotation_file)

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

    def _build_samples(self) -> tuple[ResolvedVocSample, ...]:
        """根据 ImageSets/Main 中的样本 id 构建 VOC 样本。"""

        sample_ids = _read_voc_image_set_file(self.split.image_set_file)
        class_to_index = {class_name: index for index, class_name in enumerate(self.category_names)}
        samples: list[ResolvedVocSample] = []
        for image_id, sample_id in enumerate(sample_ids, start=1):
            annotation_file = self.split.annotation_root / f"{sample_id}.xml"
            annotation = parse_voc_annotation_file(
                annotation_file=annotation_file,
                class_to_index=class_to_index,
            )
            image_path = _resolve_voc_image_path(
                image_root=self.split.image_root,
                sample_id=sample_id,
                file_name=annotation.file_name,
            )
            samples.append(
                ResolvedVocSample(
                    image_path=image_path,
                    annotation_file=annotation_file,
                    width=annotation.width,
                    height=annotation.height,
                    image_id=image_id,
                    sample_id=sample_id,
                    boxes_xyxy_with_class=list(annotation.boxes_xyxy_with_class),
                )
            )

        if not samples:
            raise InvalidRequestError("训练输入缺少有效 VOC 图片样本")
        return tuple(samples)


def resolve_voc_splits(
    dataset_storage: LocalDatasetStorage,
    manifest_payload: dict[str, object],
) -> tuple[ResolvedVocSplit, ...]:
    """从 `voc-detection-v1` manifest 解析本地 split 路径。"""

    category_names = _read_voc_category_names(manifest_payload)
    splits_payload = manifest_payload.get("splits")
    if not isinstance(splits_payload, list):
        raise InvalidRequestError("训练输入 manifest 缺少 splits 定义")

    resolved_splits: list[ResolvedVocSplit] = []
    for split_item in splits_payload:
        if not isinstance(split_item, dict):
            continue
        split_name = str(split_item.get("name", "")).strip()
        image_root = str(split_item.get("image_root", "")).strip()
        annotation_root = str(split_item.get("annotation_root", "")).strip()
        image_set_file = str(split_item.get("image_set_file", "")).strip()
        sample_count = split_item.get("sample_count", 0)
        if not split_name or not image_root or not annotation_root or not image_set_file:
            continue
        resolved_splits.append(
            ResolvedVocSplit(
                name=split_name,
                image_root=dataset_storage.resolve(image_root),
                annotation_root=dataset_storage.resolve(annotation_root),
                image_set_file=dataset_storage.resolve(image_set_file),
                sample_count=sample_count if isinstance(sample_count, int) else 0,
                category_names=category_names,
            )
        )

    if not resolved_splits:
        raise InvalidRequestError("训练输入 manifest 中没有可用的 VOC split")
    return tuple(resolved_splits)


def parse_voc_annotation_file(
    *,
    annotation_file: Path,
    class_to_index: dict[str, int],
    keep_difficult: bool = True,
) -> ParsedVocAnnotation:
    """解析 VOC XML annotation 文件。"""

    if not annotation_file.is_file():
        raise InvalidRequestError(
            "VOC annotation 文件不存在",
            details={"annotation_file": annotation_file.as_posix()},
        )

    root = ET.parse(annotation_file).getroot()
    file_name_node = root.find("filename")
    file_name = file_name_node.text.strip() if file_name_node is not None and file_name_node.text else None

    size = root.find("size")
    if size is None:
        raise InvalidRequestError("VOC annotation 缺少 size 节点")
    width = _read_required_int(size, "width")
    height = _read_required_int(size, "height")

    boxes: list[tuple[float, float, float, float, float]] = []
    for voc_object in _parse_voc_objects(root):
        difficult = voc_object.difficult
        if difficult and not keep_difficult:
            continue

        class_name = voc_object.name
        if class_name not in class_to_index:
            raise InvalidRequestError(
                "VOC annotation 包含未登记类别",
                details={"class_name": class_name},
            )

        xmin, ymin, xmax, ymax = voc_object.bbox_xyxy
        boxes.append((xmin, ymin, xmax, ymax, float(class_to_index[class_name])))

    return ParsedVocAnnotation(
        width=width,
        height=height,
        file_name=file_name,
        boxes_xyxy_with_class=tuple(boxes),
    )


def read_voc_annotation_objects(*, annotation_file: Path) -> tuple[ParsedVocObject, ...]:
    """读取 VOC annotation 中的原生 object 标注。"""

    if not annotation_file.is_file():
        raise InvalidRequestError(
            "VOC annotation 文件不存在",
            details={"annotation_file": annotation_file.as_posix()},
        )
    root = ET.parse(annotation_file).getroot()
    return _parse_voc_objects(root)


def _parse_voc_objects(root: ET.Element) -> tuple[ParsedVocObject, ...]:
    """从 VOC XML root 中解析 object 列表。"""

    objects: list[ParsedVocObject] = []
    for object_node in root.iter("object"):
        name_node = object_node.find("name")
        class_name = name_node.text.strip() if name_node is not None and name_node.text else ""
        difficult = _read_optional_int(object_node, "difficult", default=0) == 1
        bbox = object_node.find("bndbox")
        if bbox is None:
            raise InvalidRequestError("VOC object 缺少 bndbox 节点")
        xmin = float(_read_required_int(bbox, "xmin") - 1)
        ymin = float(_read_required_int(bbox, "ymin") - 1)
        xmax = float(_read_required_int(bbox, "xmax") - 1)
        ymax = float(_read_required_int(bbox, "ymax") - 1)
        objects.append(
            ParsedVocObject(
                name=class_name,
                difficult=difficult,
                bbox_xyxy=(xmin, ymin, xmax, ymax),
            )
        )
    return tuple(objects)


def _read_voc_category_names(manifest_payload: dict[str, object]) -> tuple[str, ...]:
    """从 VOC manifest 中读取类别名。"""

    category_names_payload = manifest_payload.get("category_names")
    if not isinstance(category_names_payload, list):
        raise InvalidRequestError("VOC manifest 缺少 category_names")
    category_names = tuple(
        str(item).strip()
        for item in category_names_payload
        if isinstance(item, str) and item.strip()
    )
    if not category_names:
        raise InvalidRequestError("VOC manifest 缺少有效类别名")
    return category_names


def _read_voc_image_set_file(image_set_file: Path) -> tuple[str, ...]:
    """读取 VOC ImageSets/Main/{split}.txt 中的样本 id。"""

    if not image_set_file.is_file():
        raise InvalidRequestError(
            "VOC image set 文件不存在",
            details={"image_set_file": image_set_file.as_posix()},
        )
    sample_ids = tuple(
        line.strip()
        for line in image_set_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not sample_ids:
        raise InvalidRequestError("VOC image set 文件中没有样本 id")
    return sample_ids


def _resolve_voc_image_path(
    *,
    image_root: Path,
    sample_id: str,
    file_name: str | None,
) -> Path:
    """根据 VOC XML 中的 filename 或 sample id 定位图片。"""

    if file_name:
        image_path = image_root.joinpath(*PurePosixPath(file_name).parts)
        if image_path.is_file():
            return image_path

    for suffix in (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"):
        image_path = image_root / f"{sample_id}{suffix}"
        if image_path.is_file():
            return image_path

    raise InvalidRequestError(
        "VOC 图片文件不存在",
        details={"image_root": image_root.as_posix(), "sample_id": sample_id, "file_name": file_name},
    )


def _read_required_int(node: ET.Element, child_name: str) -> int:
    """从 XML 节点读取必填整数。"""

    child = node.find(child_name)
    if child is None or child.text is None:
        raise InvalidRequestError(f"VOC annotation 缺少 {child_name}")
    return _coerce_voc_int(child.text, field_name=child_name)


def _read_optional_int(node: ET.Element, child_name: str, *, default: int) -> int:
    """从 XML 节点读取可选整数。"""

    child = node.find(child_name)
    if child is None or child.text is None:
        return default
    try:
        return _coerce_voc_int(child.text, field_name=child_name)
    except InvalidRequestError:
        return default


def _coerce_voc_int(value: str, *, field_name: str) -> int:
    """把 VOC 字段转换成整数，并兼容浮点字符串。"""

    text = str(value).strip()
    if not text or text.lower() == "unspecified":
        raise InvalidRequestError(f"VOC annotation 字段 {field_name} 不是有效整数")
    try:
        return int(float(text))
    except (TypeError, ValueError) as error:
        raise InvalidRequestError(f"VOC annotation 字段 {field_name} 不是有效整数") from error
