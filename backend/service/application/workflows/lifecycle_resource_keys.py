"""Workflow 持久化 lifecycle 的保留资源 key。"""

from __future__ import annotations

import hashlib
import re


WORKFLOW_LIFECYCLE_RESERVED_PREFIX = "__amvision_workflow_lifecycle__"
"""真实 Workflow Application id 不得使用的 lifecycle 保留前缀。"""

# application_id 数据库列上限为 128；prefix 31 + kind 31 + "__" 2 + sha256 64。
_RESOURCE_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,30}$")


def build_workflow_lifecycle_resource_key(
    resource_kind: str,
    *identity_parts: str,
) -> str:
    """用资源类型和稳定身份字段构建不可碰撞的持久化 lifecycle key。"""

    normalized_kind = resource_kind.strip().lower()
    if not _RESOURCE_KIND_PATTERN.fullmatch(normalized_kind):
        raise ValueError("resource_kind 必须是最多 31 位的小写字母、数字或连字符")
    normalized_parts = tuple(str(part).strip() for part in identity_parts)
    if not normalized_parts or any(not part for part in normalized_parts):
        raise ValueError("lifecycle 资源身份字段不能为空")
    canonical_identity = "\x00".join((normalized_kind, *normalized_parts))
    digest = hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()
    resource_key = f"{WORKFLOW_LIFECYCLE_RESERVED_PREFIX}{normalized_kind}__{digest}"
    if len(resource_key) > 128:
        raise ValueError("lifecycle resource key 超过 application_id 长度上限")
    return resource_key


def build_workflow_template_lifecycle_resource_key(
    *,
    template_id: str,
    template_version: str,
) -> str:
    """构建单个可变 Template 版本使用的 lifecycle key。"""

    return build_workflow_lifecycle_resource_key(
        "template",
        template_id,
        template_version,
    )


def build_workflow_project_lifecycle_resource_key(*, project_id: str) -> str:
    """构建 Project mutation fence 使用的持久化 sentinel key。"""

    return build_workflow_lifecycle_resource_key("project", project_id)


def build_project_mutation_lifecycle_resource_key(
    *,
    mutation_kind: str,
    resource_id: str,
) -> str:
    """构建非 Workflow Project 资源写操作使用的 lifecycle key。"""

    return build_workflow_lifecycle_resource_key(
        "mutation",
        mutation_kind,
        resource_id,
    )


def is_workflow_project_lifecycle_resource_key(
    *, project_id: str, resource_key: str
) -> bool:
    """判断 lifecycle key 是否为指定 Project 的 mutation sentinel。"""

    return resource_key.strip() == build_workflow_project_lifecycle_resource_key(
        project_id=project_id
    )


def is_workflow_lifecycle_resource_key(value: str) -> bool:
    """判断字符串是否位于 workflow lifecycle 保留命名空间。"""

    return value.strip().startswith(WORKFLOW_LIFECYCLE_RESERVED_PREFIX)


def is_project_mutation_lifecycle_resource_key(value: str) -> bool:
    """判断 lifecycle key 是否属于一次性非 Workflow Project mutation。"""

    return value.strip().startswith(f"{WORKFLOW_LIFECYCLE_RESERVED_PREFIX}mutation__")


__all__ = [
    "WORKFLOW_LIFECYCLE_RESERVED_PREFIX",
    "build_project_mutation_lifecycle_resource_key",
    "build_workflow_lifecycle_resource_key",
    "build_workflow_project_lifecycle_resource_key",
    "build_workflow_template_lifecycle_resource_key",
    "is_workflow_project_lifecycle_resource_key",
    "is_workflow_lifecycle_resource_key",
    "is_project_mutation_lifecycle_resource_key",
]
