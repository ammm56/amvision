"""统一数据集格式注册表回归测试。"""

from __future__ import annotations

from backend.contracts.datasets.dataset_formats import (
    DATASET_FORMAT_REGISTRY,
    DATASET_FORMAT_SPECIFICATIONS,
    IMPLEMENTED_DATASET_EXPORT_FORMATS,
    IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE,
    IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE,
    VOC_DETECTION_DATASET_FORMAT,
    YOLO_OBB_DATASET_FORMAT,
    get_dataset_format_specification,
    resolve_dataset_format_id,
)
from backend.service.domain.datasets.dataset_import import (
    IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE as DOMAIN_IMPORT_FORMATS,
)


def test_registry_has_one_complete_entry_per_public_format() -> None:
    """验证公开格式没有重复项、占位项或未实现项。"""

    format_ids = tuple(item.format_id for item in DATASET_FORMAT_SPECIFICATIONS)
    assert len(format_ids) == len(set(format_ids))
    assert set(DATASET_FORMAT_REGISTRY) == set(format_ids)
    assert IMPLEMENTED_DATASET_EXPORT_FORMATS == format_ids
    assert all(item.import_enabled and item.export_enabled for item in DATASET_FORMAT_SPECIFICATIONS)
    assert "semantic-mask-dir-v1" not in format_ids
    assert "sam-promptable-seg-v1" not in format_ids


def test_registry_drives_import_and_export_task_maps() -> None:
    """验证导入、导出能力矩阵都由同一注册表生成。"""

    assert DOMAIN_IMPORT_FORMATS == IMPLEMENTED_DATASET_IMPORT_FORMAT_TYPES_BY_TASK_TYPE
    assert IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE["obb"] == (
        "dota-obb-v1",
        YOLO_OBB_DATASET_FORMAT,
    )
    for task_type, format_ids in IMPLEMENTED_DATASET_EXPORT_FORMAT_TYPES_BY_TASK_TYPE.items():
        assert format_ids
        assert all(DATASET_FORMAT_REGISTRY[item].task_type == task_type for item in format_ids)


def test_registry_resolves_family_and_task_to_versioned_format() -> None:
    """验证导入完成后能够确定唯一格式 id 和坐标约定。"""

    assert resolve_dataset_format_id(
        family="yolo",
        task_type="obb",
        require_import=True,
    ) == YOLO_OBB_DATASET_FORMAT
    voc = get_dataset_format_specification(VOC_DETECTION_DATASET_FORMAT)
    assert voc is not None
    assert voc.coordinate_convention.startswith("zero-based-exclusive-default")
