"""合并当前版本与新增样本，返回提交前的完整内容，不在此处改写磁盘。"""

from collections import Counter
from dataclasses import replace

from backend.service.application.datasets.workspace_analysis import (
    image_path,
    stable_sample_id,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import DatasetCategory
from .contracts import ParsedDatasetSample


def merge_import(storage, source, incoming, excluded_ids):
    """按类别名称合并；同名文件分别保存，路径由内容写入器重新分配。"""
    if source.task_type != incoming.task_type:
        raise InvalidRequestError("新增数据的任务类型与当前数据集不一致")
    categories = list(source.categories)
    names = {c.name: c.category_id for c in categories}
    if len(names) != len(categories):
        raise InvalidRequestError("来源版本存在重复类别名称，无法安全合并")
    mapping = {}
    schemas = dict(source.metadata.get("pose_category_schemas") or {})
    incoming_schemas = incoming.detected_profile.get("pose_category_schemas") or {}
    for category in incoming.categories:
        if category.name not in names:
            identity = max((c.category_id for c in categories), default=-1) + 1
            names[category.name] = identity
            categories.append(DatasetCategory(identity, category.name))
        identity = names[category.name]
        mapping[category.category_id] = identity
        schema = incoming_schemas.get(str(category.category_id))
        previous = schemas.get(str(identity))
        if source.task_type == "pose" and previous is not None and schema != previous:
            raise InvalidRequestError(f"类别 {category.name} 的关键点定义不一致")
        if schema is not None:
            schemas[str(identity)] = schema
    if source.task_type == "pose" and source.metadata.get(
        "keypoint_flip_indices"
    ) != incoming.detected_profile.get("keypoint_flip_indices"):
        raise InvalidRequestError("关键点翻转索引与来源版本不一致")
    kept = [s for s in source.samples if s.sample_id not in excluded_ids]
    retained = tuple(
        ParsedDatasetSample(
            sample=replace(
                s, metadata={**s.metadata, "origin_sample_id": stable_sample_id(s)}
            ),
            source_image_path=image_path(storage, source, s),
            source_image_ref=s.file_name,
        )
        for s in kept
    )
    added = tuple(
        replace(
            item,
            sample=replace(
                item.sample,
                annotations=tuple(
                    replace(a, category_id=mapping[a.category_id])
                    for a in item.sample.annotations
                ),
                # 输入包中的来源身份不能冒充当前版本里的旧样本。
                metadata={
                    k: v
                    for k, v in item.sample.metadata.items()
                    if k not in {"origin_sample_id", "source_sample_id"}
                },
            ),
        )
        for item in incoming.samples
    )
    # 不同包的 image_id 通常从 1 开始；合并版本必须唯一，避免导出标注指错图片。
    samples = tuple(
        replace(item, sample=replace(item.sample, image_id=index))
        for index, item in enumerate(retained + added, start=1)
    )
    return replace(
        incoming,
        categories=tuple(categories),
        samples=samples,
        class_map={str(c.category_id): c.name for c in categories},
        detected_profile={
            **incoming.detected_profile,
            "pose_category_schemas": schemas,
        },
        validation_report={
            **incoming.validation_report,
            "sample_count": len(samples),
            "annotation_count": sum(len(item.sample.annotations) for item in samples),
            "category_count": len(categories),
            "split_counts": dict(Counter(s.sample.split for s in samples)),
            "retained_count": len(kept),
            "removed_count": len(excluded_ids),
            "added_count": len(added),
        },
    )
