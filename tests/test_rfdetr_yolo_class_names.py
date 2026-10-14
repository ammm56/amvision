"""RF-DETR 内部 YOLO 数据读取的类别映射回归。"""

import pytest

from backend.service.application.models.rfdetr_core.datasets.yolo import (
    _extract_yolo_class_names,
)


@pytest.mark.parametrize("names", [
    "['part', 'defect']",
    "{1: defect, 0: part}",
    "{'1': defect, '0': part}",
    "{1: defect, '0': part}",
])
def test_class_names_follow_numeric_ids(tmp_path, names) -> None:
    """字符串和整数类别 ID 按 ID 排序，不按 YAML 插入顺序排序。"""
    data_file = tmp_path / "data.yaml"
    data_file.write_text(f"names: {names}\n", encoding="utf-8")
    assert _extract_yolo_class_names(str(data_file)) == ["part", "defect"]


@pytest.mark.parametrize("names", [
    "{0: part, '0': defect}",
    "{0: part, 2: defect}",
    "{part: part}",
    "{true: part}",
    "{}",
])
def test_invalid_class_ids_are_rejected(tmp_path, names) -> None:
    """重复、间断、非数字和空字典不能改变标注对应的类别。"""
    data_file = tmp_path / "data.yaml"
    data_file.write_text(f"names: {names}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        _extract_yolo_class_names(str(data_file))
