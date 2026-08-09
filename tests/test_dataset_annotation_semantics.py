"""统一数据集类别语义审计回归测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.service.application.datasets.imports.annotation_semantics import (
    attach_annotation_semantics_audit,
)
from backend.service.application.datasets.imports.contracts import (
    ParsedDatasetContent,
    ParsedDatasetSample,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetSample,
    DetectionAnnotation,
)


def _build_content(
    *,
    annotations: tuple[DetectionAnnotation, ...],
    categories: tuple[DatasetCategory, ...] | None = None,
) -> ParsedDatasetContent:
    """构造带 PPE 类别的统一 detection 数据。"""

    categories = categories or (
        DatasetCategory(category_id=0, name="goggles"),
        DatasetCategory(category_id=1, name="no_goggle"),
        DatasetCategory(category_id=2, name="none"),
        DatasetCategory(category_id=3, name="Person"),
    )
    sample = DatasetSample(
        sample_id="sample-1",
        image_id=1,
        file_name="image.jpg",
        width=100,
        height=100,
        split="train",
        annotations=annotations,
    )
    return ParsedDatasetContent(
        format_type="coco",
        task_type="detection",
        image_root="images",
        annotation_root="annotations",
        manifest_file="annotations/instances_train.json",
        split_strategy="manifest-name",
        class_map={str(category.category_id): category.name for category in categories},
        categories=categories,
        samples=(
            ParsedDatasetSample(
                sample=sample,
                source_image_path=Path("image.jpg"),
                source_image_ref="image.jpg",
            ),
        ),
        detected_profile={},
        validation_report={"status": "ok", "warnings": [], "errors": []},
    )


def test_annotation_semantics_reports_ambiguous_names_and_polarity_pairs() -> None:
    """模糊类别和正负类别关系必须进入结构化 validation report。"""

    content = _build_content(
        annotations=(
            DetectionAnnotation("positive", 0, (5.0, 5.0, 10.0, 5.0)),
            DetectionAnnotation("negative", 1, (50.0, 5.0, 10.0, 5.0)),
            DetectionAnnotation("ambiguous", 2, (20.0, 20.0, 40.0, 50.0)),
        )
    )

    audited = attach_annotation_semantics_audit(content)

    assert audited.validation_report["status"] == "warning"
    warning_codes = {
        warning["code"] for warning in audited.validation_report["warnings"]
    }
    assert warning_codes == {
        "DATASET_AMBIGUOUS_CATEGORY_NAME",
        "DATASET_CATEGORY_NAME_STYLE_INCONSISTENT",
    }
    semantics = audited.validation_report["annotation_semantics"]
    assert semantics["opposite_box_conflict_count"] == 0
    assert semantics["polarity_pairs"] == [
        {
            "positive_category_id": 0,
            "positive_category": "goggles",
            "negative_category_id": 1,
            "negative_category": "no_goggle",
            "cooccurring_sample_count": 1,
        }
    ]


def test_annotation_semantics_rejects_opposite_labels_on_same_box() -> None:
    """正负类别落在同一区域时导入必须给出可定位错误。"""

    content = _build_content(
        annotations=(
            DetectionAnnotation("positive", 0, (5.0, 5.0, 10.0, 5.0)),
            DetectionAnnotation("negative", 1, (5.0, 5.0, 10.0, 5.0)),
        )
    )

    with pytest.raises(InvalidRequestError) as error_info:
        attach_annotation_semantics_audit(content)

    details = error_info.value.details
    assert details["code"] == "DATASET_OPPOSITE_CATEGORY_BOX_CONFLICT"
    assert details["conflict_count"] == 1
    assert details["examples"][0]["file_name"] == "image.jpg"


def test_annotation_semantics_rejects_normalized_category_name_collision() -> None:
    """大小写和分隔符差异不能形成下游无法区分的重复类别。"""

    content = _build_content(
        categories=(
            DatasetCategory(category_id=0, name="No Helmet"),
            DatasetCategory(category_id=1, name="no_helmet"),
        ),
        annotations=(),
    )

    with pytest.raises(InvalidRequestError) as error_info:
        attach_annotation_semantics_audit(content)

    assert (
        error_info.value.details["code"]
        == "DATASET_NORMALIZED_CATEGORY_NAME_COLLISION"
    )
