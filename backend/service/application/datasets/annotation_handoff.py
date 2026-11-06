"""外部标注交接：标准 COCO 与显式样本身份，不以文件名猜测对应关系。"""

from dataclasses import replace
from collections import Counter

from backend.contracts.datasets.exports.coco_detection_export import (
    COCO_DETECTION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.coco_instance_segmentation_export import (
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
)
from backend.contracts.datasets.exports.coco_keypoints_export import (
    COCO_KEYPOINTS_DATASET_FORMAT,
)
from backend.service.application.datasets.workspace_analysis import (
    file_digest,
    image_path,
)
from backend.service.application.errors import InvalidRequestError

HANDOFF_FORMATS = {
    COCO_DETECTION_DATASET_FORMAT,
    COCO_INSTANCE_SEGMENTATION_DATASET_FORMAT,
    COCO_KEYPOINTS_DATASET_FORMAT,
}


def write_handoff(storage, version, export_result, split_samples):
    """为每个 COCO image 写交接身份；清单留在受管导出目录以供回传校验。"""
    export_id = export_result.dataset_export_id
    entries = []
    for split, samples in split_samples:
        by_id = {sample.image_id: sample for sample in samples}
        annotation_key = next(
            s.annotation_file
            for s in export_result.format_manifest.splits
            if s.name == split
        )
        payload = storage.read_json(annotation_key)
        for image in payload["images"]:
            sample = by_id[image["id"]]
            image["amvision_sample_id"] = sample.sample_id
            image["amvision_handoff_id"] = export_id
            entries.append(
                {
                    "sample_id": sample.sample_id,
                    "split": sample.split,
                    "image_sha256": file_digest(
                        image_path(storage, version, sample), lambda: None
                    ),
                }
            )
        storage.write_json(annotation_key, payload)
    storage.write_json(
        f"{export_result.export_path}/annotation-handoff.json",
        {
            "format_id": "amvision.annotation-handoff.v1",
            "dataset_export_id": export_id,
            "dataset_version_id": version.dataset_version_id,
            "samples": entries,
        },
    )


def check_return(storage, source, returned, export, config, tick):
    """未知、重复身份阻止；缺失和图像变化由显式选项决定。"""
    if source.task_type != returned.task_type:
        raise InvalidRequestError("回传任务类型与来源不一致")
    manifest = storage.read_json(f"{export.export_path}/annotation-handoff.json")
    if (
        manifest.get("dataset_version_id") != source.dataset_version_id
        or manifest.get("dataset_export_id") != export.dataset_export_id
    ):
        raise InvalidRequestError("交接清单与来源版本不一致")
    expected = {entry["sample_id"]: entry for entry in manifest["samples"]}
    source_by_id = {sample.sample_id: sample for sample in source.samples}
    if not expected.keys() <= source_by_id.keys():
        raise InvalidRequestError("交接清单包含不属于来源版本的样本")
    mapping = {}
    counts = Counter()
    problems = []
    category_map = {}
    source_categories = {
        category.name: category.category_id for category in source.categories
    }
    for category in returned.categories:
        if category.name not in source_categories:
            counts["category_conflicts"] += 1
        else:
            category_map[category.category_id] = source_categories[category.name]
    for index, sample in enumerate(returned.samples):
        tick(index, len(returned.samples))
        identity = sample.metadata.get("external_sample_id")
        if (
            sample.metadata.get("external_handoff_id") != export.dataset_export_id
            or identity not in expected
        ):
            counts["unknown"] += 1
            if len(problems) < 200:
                problems.append(
                    {
                        "sample_id": sample.sample_id,
                        "file_name": sample.file_name,
                        "message": "缺少交接身份或不属于本次交接",
                    }
                )
            continue
        if identity in mapping:
            counts["duplicate"] += 1
            continue
        if any(a.category_id not in category_map for a in sample.annotations):
            continue
        mapping[identity] = sample
        digest = file_digest(image_path(storage, returned, sample), tick)
        if digest != expected[identity]["image_sha256"]:
            counts["image_changed"] += 1
        counts["matched"] += 1
    counts["missing"] = len(expected.keys() - mapping.keys())
    blocked = bool(
        counts["unknown"]
        or counts["duplicate"]
        or counts["category_conflicts"]
        or (counts["missing"] and not config.keep_missing)
        or (counts["image_changed"] and not config.accept_image_changes)
    )
    result = {
        "counts": dict(counts),
        "issues": problems,
        "can_create": not blocked,
        "sample_count": len(source.samples),
        "returned_count": len(returned.samples),
        "missing_policy": "keep" if config.keep_missing else "block",
    }
    planned = []
    image_sources = {}
    for original in source.samples:
        replacement = mapping.get(original.sample_id)
        if replacement is None:
            planned.append(original)
        else:
            planned.append(
                replace(
                    original,
                    width=replacement.width,
                    height=replacement.height,
                    annotations=tuple(
                        replace(a, category_id=category_map[a.category_id])
                        for a in replacement.annotations
                    ),
                )
            )
            image_sources[original.sample_id] = image_path(
                storage, returned, replacement
            )
    return replace(source, samples=tuple(planned)), result, image_sources
