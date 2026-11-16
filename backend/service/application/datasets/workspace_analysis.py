"""后台数据集质量检查、版本衍生计划与稳定身份比较。"""

from collections import Counter, defaultdict
from dataclasses import replace
from hashlib import sha256
import json
import math
from pathlib import PurePosixPath

from PIL import Image
from backend.service.application.datasets.content import content_key

from backend.contracts.datasets.workspace_jobs import DatasetDerivation
from backend.contracts.datasets.sample_media import ENTRY_TYPES, SOURCE_ASSETS
from backend.service.application.errors import InvalidRequestError
from backend.service.domain.datasets.dataset_version import (
    DatasetCategory,
    DatasetVersion,
    serialize_dataset_annotation,
)


def image_path(storage, version, sample):
    """只读取版本登记的受管文件，禁止路径逃逸及符号链接越界。"""
    root = storage.resolve(
        content_key(version.project_id, version.dataset_id, version.dataset_version_id, version.metadata)
    ).resolve()
    key = str(
        sample.metadata.get("image_object_key")
        or f"images/{sample.split}/{sample.sample_id}/{sample.file_name}"
    ).replace("\\", "/")
    part = PurePosixPath(key)
    path = root.joinpath(*part.parts).resolve()
    if (
        part.is_absolute()
        or ".." in part.parts
        or ":" in key
        or not path.is_relative_to(root)
    ):
        raise InvalidRequestError("样本图片路径越界")
    return path


def file_digest(path, tick):
    """分块计算内容摘要，并允许 worker 续租和取消检查。"""
    result = sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            result.update(block)
            tick()
    return result.hexdigest()


def quality_report(storage, version, tick):
    """机器检查不替代人工语义判断；只保留有界问题详情。"""
    counts = Counter()
    issues = []
    digests = {}
    category_ids = {c.category_id for c in version.categories}

    def issue(kind, sample, message):
        counts[kind] += 1
        if len(issues) < 200:
            issues.append(
                {
                    "sample_id": sample.sample_id,
                    "file_name": sample.file_name,
                    "kind": kind,
                    "message": message,
                }
            )

    for index, sample in enumerate(version.samples):
        tick(index, len(version.samples))
        try:
            path = image_path(storage, version, sample)
            with Image.open(path) as image:
                if image.size != (sample.width, sample.height):
                    issue("image_size", sample, "图片尺寸与登记尺寸不一致")
                image.verify()
            media = sample.metadata.get("sample_media", {})
            if media:
                from .imports.formats.sample_media import asset_path
                for kind in media["assets"]:
                    if not asset_path(path, kind).is_file():
                        issue("missing_asset", sample, f"缺少样本附件 {kind}")
            digest = file_digest(path, tick)
            if media.get("kind") == "point-cloud":
                digest = file_digest(asset_path(path, "cloud"), tick)
            elif media.get("kind") == "rgbd":
                digest += file_digest(asset_path(path, "depth"), tick)
            if digest in digests:
                issue(
                    "duplicate_image",
                    sample,
                    f"图片内容与 {digests[digest]} 相同，需人工确认",
                )
            else:
                digests[digest] = sample.sample_id
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            issue("unreadable_image", sample, f"图片无法读取：{type(error).__name__}")
        if not sample.annotations and not sample.metadata.get("sample_media"):
            issue("empty_annotation", sample, "未提供标注，需确认是否为正常负样本")
        for annotation in sample.annotations:
            if annotation.category_id not in category_ids:
                issue("unknown_category", sample, "标注引用了不存在的类别")
            bbox = getattr(annotation, "bbox_xywh", None)
            if bbox is not None:
                if (
                    len(bbox) != 4
                    or not all(math.isfinite(n) for n in bbox)
                    or bbox[2] <= 0
                    or bbox[3] <= 0
                    or bbox[0] < 0
                    or bbox[1] < 0
                    or bbox[0] + bbox[2] > sample.width + 0.001
                    or bbox[1] + bbox[3] > sample.height + 0.001
                ):
                    issue("invalid_geometry", sample, "标注框尺寸无效或超出图片边界")
            points = getattr(annotation, "polygon_xy", None)
            if points and (
                len(points) % 2
                or not all(math.isfinite(n) for n in points)
                or any(
                    x < 0 or x > sample.width or y < 0 or y > sample.height
                    for x, y in zip(points[::2], points[1::2])
                )
            ):
                issue("invalid_geometry", sample, "旋转框顶点无效或越界")
    return {
        "sample_count": len(version.samples),
        "counts": dict(counts),
        "issues": issues,
        "issue_count": sum(counts.values()),
        "truncated": sum(counts.values()) > len(issues),
        "checked": [
            "image_readability",
            "image_size",
            "exact_duplicates",
            "category_reference",
            "bounding_geometry",
            "empty_annotations",
        ],
        "unchecked": ["标注完整性与类别语义", "近似重复", "掩膜轮廓与关键点的人工复核"],
    }


def derivation_plan(
    version: DatasetVersion, config: DatasetDerivation, selected_ids: set[str] | None
):
    """按显式类别映射和样本范围生成计划；同名不隐式合并。"""
    samples = tuple(
        s
        for s in version.samples
        if selected_ids is None or s.sample_id in selected_ids
    )
    if not samples:
        raise InvalidRequestError("当前选择没有样本")
    unknown = set(config.category_names) - {c.category_id for c in version.categories}
    if unknown:
        raise InvalidRequestError("类别映射包含不存在的类别")
    categories = tuple(
        DatasetCategory(
            c.category_id, config.category_names.get(c.category_id, c.name).strip()
        )
        for c in version.categories
    )
    if len({c.name.casefold() for c in categories}) != len(categories):
        raise InvalidRequestError("类别名称重复；请使用不同名称，不能隐式合并类别")
    category_ids = {c.category_id for c in categories}
    mapping = {key: config.category_mapping.get(key, key) for key in category_ids}
    if any(key != target for key, target in mapping.items()) and version.task_type not in {
        "detection", "classification", "segmentation", "obb"
    }:
        raise InvalidRequestError("此任务类型暂不支持类别合并或排除，仅支持类别改名")
    if set(config.category_mapping) - category_ids or any(
        target is not None and target not in category_ids for target in mapping.values()
    ):
        raise InvalidRequestError("类别映射包含不存在的类别")
    # 目标必须是保留类别，避免链式映射、循环或映射到被排除的类别。
    if any(target is not None and mapping[target] != target for target in mapping.values()):
        raise InvalidRequestError("目标类别必须保持自身映射，不能映射到已合并或排除的类别")
    categories = tuple(c for c in categories if mapping[c.category_id] == c.category_id)
    if category_ids and not categories:
        raise InvalidRequestError("至少保留一个目标类别")
    if any(a.category_id not in category_ids for s in samples for a in s.annotations):
        raise InvalidRequestError("样本标注引用了不存在的类别，请先修正来源版本")
    groups = defaultdict(list)
    for sample in samples:
        group = (
            sample.metadata.get(config.group_key)
            if config.group_key
            else sample.sample_id
        )
        if group is None or not isinstance(group, (str, int)) or str(group) == "":
            raise InvalidRequestError("部分样本缺少有效分组值，请修改分组键")
        groups[str(group)].append(sample)
    assignments = {}
    if config.split_ratios is not None:
        order = sorted(
            groups, key=lambda key: sha256(f"{config.seed}:{key}".encode()).hexdigest()
        )
        targets = [len(samples) * value / 100 for value in config.split_ratios]
        used = [0, 0, 0]
        for key in order:
            candidate = max(
                (i for i in range(3) if config.split_ratios[i] > 0),
                key=lambda i: targets[i] - used[i],
            )
            for sample in groups[key]:
                assignments[sample.sample_id] = ("train", "val", "test")[candidate]
            used[candidate] += len(groups[key])
    planned = tuple(
        replace(
            s,
            split=assignments.get(s.sample_id, s.split),
            annotations=tuple(
                replace(a, category_id=mapping[a.category_id])
                for a in s.annotations if mapping.get(a.category_id) is not None
            ),
        ) for s in samples
    )
    summary = {
        "source_count": len(version.samples),
        "sample_count": len(samples),
        "object_count": sum(len(s.annotations) for s in planned),
        "source_object_count": sum(len(s.annotations) for s in version.samples),
        "source_category_count": len(version.categories),
        "category_count": len(categories),
        "excluded_count": len(version.samples) - len(samples),
        "source_split_counts": dict(Counter(s.split for s in version.samples)),
        "split_counts": dict(Counter(s.split for s in planned)),
        "source_split_object_counts": {
            split: sum(len(s.annotations) for s in version.samples if s.split == split)
            for split in {s.split for s in version.samples}
        },
        "split_object_counts": {
            split: sum(len(s.annotations) for s in planned if s.split == split)
            for split in {s.split for s in planned}
        },
        "category_changes": [
            {"category_id": before.category_id, "before": before.name,
             "after": next((c.name for c in categories if c.category_id == mapping[before.category_id]), None)}
            for before in version.categories
            if mapping[before.category_id] != before.category_id
            or config.category_names.get(before.category_id, before.name).strip() != before.name
        ],
        "description": config.description.strip(),
        "group_count": len(groups),
        "group_key": config.group_key,
        "group_integrity": "passed" if config.group_key else "not_configured",
        "categories": [
            {"category_id": c.category_id, "name": c.name} for c in categories
        ],
        "split_changed": sum(a.split != b.split for a, b in zip(samples, planned)),
    }
    return replace(version, categories=categories, samples=planned), summary


def derivation_checks(storage, version, tick):
    """按原始文件摘要统计跨划分重复样本；读取失败不能冒称检查通过。"""
    digests = defaultdict(list)
    unreadable = 0
    for index, sample in enumerate(version.samples):
        tick(index, len(version.samples))
        try:
            path = image_path(storage, version, sample)
            media = sample.metadata.get("sample_media", {})
            if media.get("kind") in {"point-cloud", "rgbd"}:
                from .imports.formats.sample_media import asset_path
                kind = "cloud" if media["kind"] == "point-cloud" else "depth"
                digest = file_digest(asset_path(path, kind), tick)
                if kind == "depth":
                    digest += file_digest(path, tick)
            else:
                digest = file_digest(path, tick)
            digests[digest].append(sample.split)
        except (OSError, ValueError):
            unreadable += 1
    candidates = sum(len(splits) for splits in digests.values() if len(set(splits)) > 1)
    return {
        "cross_split_duplicate_count": candidates,
        "duplicate_check": "incomplete" if unreadable else "passed",
        "unreadable_count": unreadable,
        "can_create": unreadable == 0,
    }


def stable_sample_id(sample):
    """只有显式来源链可匹配，不猜测相同文件名代表同一样本。"""
    return str(sample.metadata.get("origin_sample_id") or sample.sample_id)


def _media_comparison(storage, version, sample, tick):
    """读取原始附件摘要及公开语义字段；不比较派生预览或包内文件名。"""
    media = sample.metadata.get("sample_media", {})
    if not media and version.task_type not in ENTRY_TYPES:
        return {}, {}
    kind = media.get("kind")
    if kind != version.task_type or kind not in ENTRY_TYPES:
        raise InvalidRequestError("样本媒体类型与数据集不一致，不能可靠比较")
    from .imports.formats.sample_media import asset_path

    declared = set(media.get("assets", ()))
    required = {"point-cloud": {"cloud"}, "rgbd": {"depth"}}.get(kind, set())
    if not required.issubset(declared):
        raise InvalidRequestError("样本缺少必需的原始附件声明，不能可靠比较")
    path = image_path(storage, version, sample)
    digests = {
        name: file_digest(asset_path(path, name), tick)
        for name in SOURCE_ASSETS if name in declared
    }
    fields = ENTRY_TYPES[kind].model_fields.keys() - {
        "id", "origin_id", "split", "image", *SOURCE_ASSETS,
    }
    semantic = {name: media.get(name) for name in fields}
    semantic["kind"] = kind
    return digests, semantic


def compare_versions(storage, before, after, tick):
    """比较原始图片/附件、物理语义、标注、类别和划分，不用预览代替原件。"""
    left = {stable_sample_id(s): s for s in before.samples}
    right = {stable_sample_id(s): s for s in after.samples}
    if len(left) != len(before.samples) or len(right) != len(after.samples):
        raise InvalidRequestError("稳定样本身份重复，无法可靠比较")
    counts = Counter()
    changes = []
    names_before = {c.category_id: c.name for c in before.categories}
    names_after = {c.category_id: c.name for c in after.categories}

    def annotations(sample):
        values = []
        for annotation in sample.annotations:
            value = serialize_dataset_annotation(annotation)
            value.pop("annotation_id", None)
            value.pop("metadata", None)
            values.append(value)
        return sorted(json.dumps(value, sort_keys=True) for value in values)

    for index, identity in enumerate(sorted(left.keys() | right.keys())):
        tick(index, max(len(left), len(right)))
        a, b = left.get(identity), right.get(identity)
        kinds = []
        if a is None:
            kinds.append("added")
        elif b is None:
            kinds.append("removed")
        else:
            if a.split != b.split:
                kinds.append("split")
            if annotations(a) != annotations(b):
                kinds.append("annotations")
            if any(
                names_before.get(ann.category_id) != names_after.get(ann.category_id)
                for ann in (*a.annotations, *b.annotations)
            ):
                kinds.append("categories")
            left_assets, left_fields = _media_comparison(storage, before, a, tick)
            right_assets, right_fields = _media_comparison(storage, after, b, tick)
            for name in SOURCE_ASSETS:
                if left_assets.get(name) != right_assets.get(name):
                    kinds.append(name)
            if left_fields != right_fields:
                kinds.append("media_metadata")
            if before.task_type != "point-cloud" and after.task_type != "point-cloud" and file_digest(
                image_path(storage, before, a), tick
            ) != file_digest(image_path(storage, after, b), tick):
                kinds.append("image")
        if kinds:
            counts.update(kinds)
            counts["changed_samples"] += 1
            if len(changes) < 200:
                changes.append(
                    {
                        "sample_id": (b or a).sample_id,
                        "source_sample_id": a.sample_id if a else None,
                        "file_name": (b or a).file_name,
                        "kinds": kinds,
                    }
                )
    return {
        "counts": dict(counts),
        "changes": changes,
        "truncated": counts["changed_samples"] > len(changes),
        "source_count": len(left),
        "target_count": len(right),
    }
