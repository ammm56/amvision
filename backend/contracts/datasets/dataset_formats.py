"""平台数据集格式注册表。

本模块是数据集导入、导出、训练输入和 API 能力目录的单一事实来源。
格式 id 描述具体任务和序列化规则，不使用只有 ``coco`` / ``yolo`` 这类
无法区分任务的模糊名称。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal, Mapping


DatasetFormatFamily = Literal["coco", "voc", "yolo", "imagenet", "dota"]
DatasetFormatTaskType = Literal[
    "detection",
    "segmentation",
    "pose",
    "classification",
    "obb",
]
DatasetExportFormatId = Literal[
    "coco-detection-v1",
    "voc-detection-v1",
    "voc-instance-seg-v1",
    "yolo-detection-v1",
    "coco-instance-seg-v1",
    "yolo-instance-seg-v1",
    "coco-keypoints-v1",
    "yolo-pose-v1",
    "imagenet-classification-v1",
    "dota-obb-v1",
    "yolo-obb-v1",
]


COCO_DETECTION_DATASET_FORMAT: Final[DatasetExportFormatId] = "coco-detection-v1"
VOC_DETECTION_DATASET_FORMAT: Final[DatasetExportFormatId] = "voc-detection-v1"
VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "voc-instance-seg-v1"
)
YOLO_DETECTION_DATASET_FORMAT: Final[DatasetExportFormatId] = "yolo-detection-v1"
COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "coco-instance-seg-v1"
)
YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "yolo-instance-seg-v1"
)
COCO_KEYPOINTS_DATASET_FORMAT: Final[DatasetExportFormatId] = "coco-keypoints-v1"
YOLO_POSE_DATASET_FORMAT: Final[DatasetExportFormatId] = "yolo-pose-v1"
IMAGENET_CLASSIFICATION_DATASET_FORMAT: Final[DatasetExportFormatId] = (
    "imagenet-classification-v1"
)
DOTA_OBB_DATASET_FORMAT: Final[DatasetExportFormatId] = "dota-obb-v1"
YOLO_OBB_DATASET_FORMAT: Final[DatasetExportFormatId] = "yolo-obb-v1"


@dataclass(frozen=True, slots=True)
class DatasetFormatSpecification:
    """描述一个已经实现且可执行的数据集格式。

    字段：
    - format_id：版本化的公开格式 id。
    - family：外部格式家族，用于导入自动识别。
    - task_type：格式能够表达的唯一平台任务类型。
    - annotation_kind：标注文件中的记录形态。
    - coordinate_convention：外部坐标约定；内部统一为 0-based pixel、右下边界 exclusive。
    - class_index_base：外部类别索引起点；按名称组织时为空。
    - split_convention：split 的目录或 manifest 规则摘要。
    - import_enabled：是否具备完整导入实现。
    - export_enabled：是否具备完整导出实现。
    """

    format_id: DatasetExportFormatId
    family: DatasetFormatFamily
    task_type: DatasetFormatTaskType
    annotation_kind: str
    coordinate_convention: str
    class_index_base: int | None
    split_convention: str
    import_enabled: bool = True
    export_enabled: bool = True


DATASET_FORMAT_SPECIFICATIONS: Final[tuple[DatasetFormatSpecification, ...]] = (
    DatasetFormatSpecification(
        format_id=COCO_DETECTION_DATASET_FORMAT,
        family="coco",
        task_type="detection",
        annotation_kind="bbox-xywh",
        coordinate_convention="zero-based-pixel-xywh",
        class_index_base=None,
        split_convention="manifest-per-split",
    ),
    DatasetFormatSpecification(
        format_id=VOC_DETECTION_DATASET_FORMAT,
        family="voc",
        task_type="detection",
        annotation_kind="bbox-xyxy",
        coordinate_convention="zero-based-exclusive-default;official-one-based-inclusive-explicit",
        class_index_base=None,
        split_convention="ImageSets/Main",
    ),
    DatasetFormatSpecification(
        format_id=VOC_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        family="voc",
        task_type="segmentation",
        annotation_kind="indexed-instance-mask-and-class-mask",
        coordinate_convention="zero-based-pixel-mask",
        class_index_base=None,
        split_convention="ImageSets/Segmentation",
    ),
    DatasetFormatSpecification(
        format_id=YOLO_DETECTION_DATASET_FORMAT,
        family="yolo",
        task_type="detection",
        annotation_kind="class-cxcywh",
        coordinate_convention="zero-based-normalized-center-xywh",
        class_index_base=0,
        split_convention="manifest-or-images-labels-directories",
    ),
    DatasetFormatSpecification(
        format_id=COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        family="coco",
        task_type="segmentation",
        annotation_kind="polygon-or-rle",
        coordinate_convention="zero-based-pixel",
        class_index_base=None,
        split_convention="manifest-per-split",
    ),
    DatasetFormatSpecification(
        format_id=YOLO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
        family="yolo",
        task_type="segmentation",
        annotation_kind="class-polygon",
        coordinate_convention="zero-based-normalized-polygon",
        class_index_base=0,
        split_convention="manifest-or-images-labels-directories",
    ),
    DatasetFormatSpecification(
        format_id=COCO_KEYPOINTS_DATASET_FORMAT,
        family="coco",
        task_type="pose",
        annotation_kind="bbox-keypoints",
        coordinate_convention="zero-based-pixel",
        class_index_base=None,
        split_convention="manifest-per-split",
    ),
    DatasetFormatSpecification(
        format_id=YOLO_POSE_DATASET_FORMAT,
        family="yolo",
        task_type="pose",
        annotation_kind="class-cxcywh-keypoints",
        coordinate_convention="zero-based-normalized",
        class_index_base=0,
        split_convention="manifest-or-images-labels-directories",
    ),
    DatasetFormatSpecification(
        format_id=IMAGENET_CLASSIFICATION_DATASET_FORMAT,
        family="imagenet",
        task_type="classification",
        annotation_kind="class-directory",
        coordinate_convention="not-applicable",
        class_index_base=None,
        split_convention="split/class-directories",
    ),
    DatasetFormatSpecification(
        format_id=DOTA_OBB_DATASET_FORMAT,
        family="dota",
        task_type="obb",
        annotation_kind="polygon-class-difficult",
        coordinate_convention="zero-based-pixel-four-point",
        class_index_base=None,
        split_convention="images-and-labels-per-split",
    ),
    DatasetFormatSpecification(
        format_id=YOLO_OBB_DATASET_FORMAT,
        family="yolo",
        task_type="obb",
        annotation_kind="class-four-point-polygon",
        coordinate_convention="zero-based-normalized-four-point",
        class_index_base=0,
        split_convention="manifest-or-images-labels-directories",
    ),
)


def _build_registry() -> Mapping[DatasetExportFormatId, DatasetFormatSpecification]:
    """构造不可变注册表，并在 import 时阻止重复格式 id。"""

    registry = {item.format_id: item for item in DATASET_FORMAT_SPECIFICATIONS}
    if len(registry) != len(DATASET_FORMAT_SPECIFICATIONS):
        raise RuntimeError("数据集格式注册表存在重复 format_id")
    return MappingProxyType(registry)


DATASET_FORMAT_REGISTRY: Final[
    Mapping[DatasetExportFormatId, DatasetFormatSpecification]
] = _build_registry()


IMPLEMENTED_DATASET_EXPORT_FORMATS: Final[tuple[DatasetExportFormatId, ...]] = tuple(
    item.format_id for item in DATASET_FORMAT_SPECIFICATIONS if item.export_enabled
)


IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE: Final[
    dict[DatasetFormatTaskType, tuple[DatasetExportFormatId, ...]]
] = {
    task_type: tuple(
        item.format_id
        for item in DATASET_FORMAT_SPECIFICATIONS
        if item.export_enabled and item.task_type == task_type
    )
    for task_type in ("detection", "segmentation", "pose", "classification", "obb")
}


IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE: Final[
    dict[DatasetFormatTaskType, tuple[DatasetFormatFamily, ...]]
] = {
    task_type: tuple(
        dict.fromkeys(
            item.family
            for item in DATASET_FORMAT_SPECIFICATIONS
            if item.import_enabled and item.task_type == task_type
        )
    )
    for task_type in ("detection", "segmentation", "pose", "classification", "obb")
}


def get_dataset_format_specification(
    format_id: str,
) -> DatasetFormatSpecification | None:
    """按 format_id 读取格式规范。"""

    return DATASET_FORMAT_REGISTRY.get(format_id)  # type: ignore[arg-type]


def resolve_dataset_format_id(
    *,
    family: str,
    task_type: str,
    require_import: bool = False,
    require_export: bool = False,
) -> DatasetExportFormatId | None:
    """按外部格式家族和任务类型解析唯一的版本化格式 id。"""

    matches = tuple(
        item
        for item in DATASET_FORMAT_SPECIFICATIONS
        if item.family == family
        and item.task_type == task_type
        and (item.import_enabled or not require_import)
        and (item.export_enabled or not require_export)
    )
    if len(matches) > 1:
        raise RuntimeError(
            f"数据集格式注册表存在歧义: family={family}, task_type={task_type}"
        )
    return matches[0].format_id if matches else None
