"""统一数据集标注的类别语义审计。"""

from __future__ import annotations

from dataclasses import replace
import re

from backend.service.application.datasets.imports.contracts import ParsedDatasetContent
from backend.service.application.errors import InvalidRequestError


_AMBIGUOUS_CATEGORY_NAMES = frozenset({"none", "other", "unknown", "undefined"})
_MAX_CONFLICT_EXAMPLES = 20
_OPPOSITE_BOX_IOU_THRESHOLD = 0.5


def attach_annotation_semantics_audit(
    parsed_content: ParsedDatasetContent,
) -> ParsedDatasetContent:
    """审计统一标注中的类别名称和正负类别空间矛盾。"""

    if parsed_content.task_type not in {"detection", "segmentation", "pose", "obb"}:
        return parsed_content

    category_name_by_id = {
        int(category.category_id): str(category.name).strip()
        for category in parsed_content.categories
    }
    normalized_category_id: dict[str, int] = {}
    normalized_name_collisions: list[dict[str, object]] = []
    for category_id, category_name in category_name_by_id.items():
        normalized_name = _normalize_category_name(category_name)
        existing_category_id = normalized_category_id.get(normalized_name)
        if existing_category_id is not None and existing_category_id != category_id:
            normalized_name_collisions.append(
                {
                    "normalized_name": normalized_name,
                    "first_category_id": existing_category_id,
                    "first_category": category_name_by_id[existing_category_id],
                    "second_category_id": category_id,
                    "second_category": category_name,
                }
            )
            continue
        normalized_category_id[normalized_name] = category_id
    if normalized_name_collisions:
        raise InvalidRequestError(
            "数据集包含规范化后重名的类别",
            details={
                "code": "DATASET_NORMALIZED_CATEGORY_NAME_COLLISION",
                "collisions": normalized_name_collisions,
                "suggestion": "通过 class_map 为每个类别指定唯一的小写 snake_case 名称",
            },
        )
    polarity_pairs = _resolve_polarity_pairs(normalized_category_id)
    category_annotation_counts = {category_id: 0 for category_id in category_name_by_id}
    pair_cooccurrence_counts = {pair: 0 for pair in polarity_pairs}
    conflict_count = 0
    conflict_examples: list[dict[str, object]] = []

    for parsed_sample in parsed_content.samples:
        sample = parsed_sample.sample
        annotations_by_category: dict[int, list[object]] = {}
        for annotation in sample.annotations:
            category_id = int(annotation.category_id)
            category_annotation_counts[category_id] = (
                category_annotation_counts.get(category_id, 0) + 1
            )
            annotations_by_category.setdefault(category_id, []).append(annotation)

        for positive_id, negative_id in polarity_pairs:
            positive_annotations = annotations_by_category.get(positive_id, ())
            negative_annotations = annotations_by_category.get(negative_id, ())
            if positive_annotations and negative_annotations:
                pair_cooccurrence_counts[(positive_id, negative_id)] += 1
            for positive in positive_annotations:
                for negative in negative_annotations:
                    overlap = _bbox_iou(
                        positive.bbox_xywh,
                        negative.bbox_xywh,
                    )
                    if overlap < _OPPOSITE_BOX_IOU_THRESHOLD:
                        continue
                    conflict_count += 1
                    if len(conflict_examples) >= _MAX_CONFLICT_EXAMPLES:
                        continue
                    conflict_examples.append(
                        {
                            "split": sample.split,
                            "file_name": sample.file_name,
                            "positive_category": category_name_by_id[positive_id],
                            "negative_category": category_name_by_id[negative_id],
                            "positive_annotation_id": positive.annotation_id,
                            "negative_annotation_id": negative.annotation_id,
                            "iou": round(overlap, 6),
                        }
                    )

    if conflict_count:
        raise InvalidRequestError(
            "数据集存在正向类别与 no_* 类别的同区域矛盾标注",
            details={
                "code": "DATASET_OPPOSITE_CATEGORY_BOX_CONFLICT",
                "conflict_count": conflict_count,
                "iou_threshold": _OPPOSITE_BOX_IOU_THRESHOLD,
                "examples": conflict_examples,
                "examples_truncated": conflict_count > len(conflict_examples),
                "suggestion": "修正冲突标注后重新导入，不能用 class map 合并相反语义",
            },
        )

    ambiguous_categories = [
        {
            "category_id": category_id,
            "name": category_name_by_id[category_id],
            "annotation_count": category_annotation_counts.get(category_id, 0),
        }
        for category_id, normalized_name in sorted(
            (
                (category_id, _normalize_category_name(name))
                for category_id, name in category_name_by_id.items()
            )
        )
        if normalized_name in _AMBIGUOUS_CATEGORY_NAMES
    ]
    warnings = list(parsed_content.validation_report.get("warnings") or [])
    if ambiguous_categories:
        warnings.append(
            {
                "code": "DATASET_AMBIGUOUS_CATEGORY_NAME",
                "severity": "warning",
                "message": "检测到无法确定业务语义的占位类别名",
                "details": {"categories": ambiguous_categories},
                "suggestion": "通过 class_map 映射为明确类别名；无法确认语义时应删除或重新标注",
            }
        )

    non_canonical_names = [
        {"category_id": category_id, "name": name}
        for category_id, name in category_name_by_id.items()
        if _normalize_category_name(name) != name
    ]
    if polarity_pairs and non_canonical_names:
        warnings.append(
            {
                "code": "DATASET_CATEGORY_NAME_STYLE_INCONSISTENT",
                "severity": "warning",
                "message": "正负类别数据集包含非小写 snake_case 类别名",
                "details": {"categories": non_canonical_names},
                "suggestion": "通过 class_map 统一为小写 snake_case，避免下游规则大小写不一致",
            }
        )

    audit_report = {
        "ambiguous_categories": ambiguous_categories,
        "polarity_pairs": [
            {
                "positive_category_id": positive_id,
                "positive_category": category_name_by_id[positive_id],
                "negative_category_id": negative_id,
                "negative_category": category_name_by_id[negative_id],
                "cooccurring_sample_count": pair_cooccurrence_counts[
                    (positive_id, negative_id)
                ],
            }
            for positive_id, negative_id in polarity_pairs
        ],
        "opposite_box_iou_threshold": _OPPOSITE_BOX_IOU_THRESHOLD,
        "opposite_box_conflict_count": 0,
    }
    validation_report = {
        **parsed_content.validation_report,
        "status": "warning" if warnings else parsed_content.validation_report.get("status", "ok"),
        "warnings": warnings,
        "annotation_semantics": audit_report,
    }
    return replace(parsed_content, validation_report=validation_report)


def _resolve_polarity_pairs(
    normalized_category_id: dict[str, int],
) -> tuple[tuple[int, int], ...]:
    """把 ``item`` / ``no_item`` 和单复数变体解析为正负类别对。"""

    pairs: list[tuple[int, int]] = []
    for negative_name, negative_id in normalized_category_id.items():
        if not negative_name.startswith("no_") or len(negative_name) <= 3:
            continue
        stem = negative_name[3:]
        candidate_names = (stem, f"{stem}s", stem[:-1] if stem.endswith("s") else "")
        positive_id = next(
            (
                normalized_category_id[candidate]
                for candidate in candidate_names
                if candidate and candidate in normalized_category_id
            ),
            None,
        )
        if positive_id is not None:
            pairs.append((positive_id, negative_id))
    return tuple(sorted(set(pairs)))


def _normalize_category_name(value: str) -> str:
    """把类别名归一为可比较的小写 snake_case。"""

    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.strip().lower())).strip(
        "_"
    )


def _bbox_iou(
    first: tuple[float, float, float, float],
    second: tuple[float, float, float, float],
) -> float:
    """计算两个 xywh 框的 IoU。"""

    first_x, first_y, first_width, first_height = first
    second_x, second_y, second_width, second_height = second
    intersection_width = max(
        0.0,
        min(first_x + first_width, second_x + second_width)
        - max(first_x, second_x),
    )
    intersection_height = max(
        0.0,
        min(first_y + first_height, second_y + second_height)
        - max(first_y, second_y),
    )
    intersection_area = intersection_width * intersection_height
    union_area = (
        first_width * first_height
        + second_width * second_height
        - intersection_area
    )
    return intersection_area / union_area if union_area > 0.0 else 0.0


__all__ = ["attach_annotation_semantics_audit"]
