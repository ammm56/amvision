"""独立评估 manifest split 选择规则测试。"""

from __future__ import annotations

import pytest

from backend.service.application.models.evaluation.manifest_splits import (
    select_independent_evaluation_split,
)
from backend.service.application.models.yolo11_core.evaluation.segmentation import (
    _parse_yolo11_segmentation_manifest,
)
from backend.service.application.models.yolo26_core.evaluation.segmentation import (
    _parse_yolo26_segmentation_manifest,
)
from backend.service.application.models.yolov8_core.evaluation.segmentation import (
    _parse_yolov8_segmentation_manifest,
)


def test_independent_evaluation_prefers_test_regardless_of_manifest_order() -> None:
    """test 必须优先于 validation，不能受 manifest 数组顺序影响。"""

    selected = select_independent_evaluation_split(
        [
            {"name": "train"},
            {"name": "val"},
            {"name": "test"},
        ]
    )

    assert selected == {"name": "test"}


def test_independent_evaluation_uses_validation_without_test() -> None:
    """没有独立 test 时才允许回退到 validation。"""

    selected = select_independent_evaluation_split(
        [{"name": "train"}, {"name": "validation"}]
    )

    assert selected == {"name": "validation"}


def test_independent_evaluation_rejects_non_list_payload() -> None:
    """非数组 splits 不得被误当作可用数据划分。"""

    assert select_independent_evaluation_split({"name": "test"}) is None


@pytest.mark.parametrize(
    "parser",
    (
        _parse_yolov8_segmentation_manifest,
        _parse_yolo11_segmentation_manifest,
        _parse_yolo26_segmentation_manifest,
    ),
)
def test_yolo_segmentation_independent_evaluation_prefers_test(parser) -> None:
    """三代 YOLO segmentation evaluator 都必须实际采用共享 test-first 规则。"""

    def split(name: str, image_id: int) -> dict[str, object]:
        return {
            "name": name,
            "image_root": f"images/{name}",
            "images": [
                {
                    "id": image_id,
                    "file_name": f"{name}.jpg",
                    "width": 8,
                    "height": 8,
                }
            ],
            "annotations": [],
        }

    split_name, samples, labels = parser(
        {
            "splits": [split("train", 1), split("val", 2), split("test", 3)],
            "categories": [{"id": 0, "name": "object"}],
        },
        object(),
    )

    assert split_name == "test"
    assert [sample["image_path"] for sample in samples] == ["images/test/test.jpg"]
    assert labels == ("object",)
