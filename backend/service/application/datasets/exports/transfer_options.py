"""向导中的导出划分、类别顺序和下载文件名。"""

import re
from dataclasses import replace

from backend.service.application.errors import InvalidRequestError


def validate_options(request, version):
    """校验追加的可选导出参数，保留省略参数时既有的公开契约。"""
    splits = request.included_splits
    if splits is not None and (
        not splits
        or len(set(splits)) != len(splits)
        or not set(splits) <= {"train", "val", "test"}
        or ("test" in splits and not request.include_test_split)
    ):
        raise InvalidRequestError("导出划分无效")
    ids = request.source_category_ids
    if ids is not None:
        known = {c.category_id for c in version.categories}
        if not ids or len(ids) != len(set(ids)) or not set(ids) <= known:
            raise InvalidRequestError("所选导出类别无效")
        if request.annotation_handoff or (
            version.task_type not in {"detection", "segmentation", "pose", "obb"}
            and set(ids) != known
        ):
            raise InvalidRequestError("当前任务不支持筛选或重排对象类别")
        if request.category_names and (
            len(request.category_names) != len(ids)
            or any(not n.strip() for n in request.category_names)
            or len({n.strip() for n in request.category_names}) != len(ids)
        ):
            raise InvalidRequestError("目标类别名称数量不匹配")
    name = request.package_name
    if name and (
        len(name) > 180
        or not name.lower().endswith(".zip")
        or not name[:-4].strip()
        or re.search(r'[<>:"/\\|?*\x00-\x1f]', name)
        or name.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }
    ):
        raise InvalidRequestError("下载文件名必须是有效的 ZIP 文件名")


def apply_category_order(version, ids, names):
    """显式筛选对象标注并按目标顺序重新编号，图像及原版本保持独立。"""
    if ids is None:
        return version
    categories = {c.category_id: c for c in version.categories}
    mapping = {source: target for target, source in enumerate(ids)}
    return replace(
        version,
        categories=tuple(
            replace(
                categories[src],
                category_id=target,
                name=names[target].strip() if names else categories[src].name,
            )
            for src, target in mapping.items()
        ),
        samples=tuple(
            replace(
                s,
                annotations=tuple(
                    replace(a, category_id=mapping[a.category_id])
                    for a in s.annotations
                    if a.category_id in mapping
                ),
            )
            for s in version.samples
        ),
    )
