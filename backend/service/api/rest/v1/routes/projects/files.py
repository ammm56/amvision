"""Project 公开文件读取规则。"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request

from backend.service.api.deps.auth import AuthenticatedPrincipal
from backend.service.application.errors import InvalidRequestError, ResourceNotFoundError
from backend.service.infrastructure.object_store.object_key_layout import (
    build_public_project_object_namespace_patterns,
    is_public_project_object_key,
)
from backend.service.api.rest.v1.routes.projects.services import (
    ensure_project_known_and_visible,
    require_dataset_storage,
)


def resolve_project_object_path(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    project_id: str,
    object_key: str | None,
    storage_uri: str | None,
) -> tuple[str, Path]:
    """解析并校验一个 Project 内对象文件路径。"""

    ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    resolved_object_key = resolve_requested_object_key(
        object_key=object_key,
        storage_uri=storage_uri,
    )
    if not is_public_project_object_key(
        project_id=project_id, object_key=resolved_object_key
    ):
        raise InvalidRequestError(
            "当前接口只允许读取 Project 公开文件命名空间中的对象文件",
            details={
                "project_id": project_id,
                "object_key": resolved_object_key,
                "allowed_namespaces": build_public_project_object_namespace_patterns(
                    project_id=project_id
                ),
            },
        )
    file_path = require_dataset_storage(request).resolve(resolved_object_key)
    if not file_path.is_file():
        raise ResourceNotFoundError(
            "请求的对象文件不存在",
            details={"project_id": project_id, "object_key": resolved_object_key},
        )
    return resolved_object_key, file_path


def list_project_public_object_entries(
    *,
    request: Request,
    principal: AuthenticatedPrincipal,
    project_id: str,
    object_prefix: str | None,
    storage_prefix: str | None,
) -> list[tuple[str, Path]]:
    """列出一个 Project 公开命名空间中的文件路径。"""

    ensure_project_known_and_visible(
        request=request,
        principal=principal,
        project_id=project_id,
    )
    dataset_storage = require_dataset_storage(request)
    resolved_object_prefix = resolve_requested_object_prefix(
        object_prefix=object_prefix,
        storage_prefix=storage_prefix,
    )

    if resolved_object_prefix is None:
        scan_root = dataset_storage.resolve(f"projects/{project_id}")
        if not scan_root.exists():
            return []
        candidate_paths = [
            file_path for file_path in sorted(scan_root.rglob("*")) if file_path.is_file()
        ]
    else:
        if not is_public_project_object_key(
            project_id=project_id, object_key=resolved_object_prefix
        ):
            raise InvalidRequestError(
                "当前接口只允许列出 Project 公开文件命名空间中的对象文件",
                details={
                    "project_id": project_id,
                    "object_prefix": resolved_object_prefix,
                    "allowed_namespaces": build_public_project_object_namespace_patterns(
                        project_id=project_id
                    ),
                },
            )
        scan_root = dataset_storage.resolve(resolved_object_prefix)
        if scan_root.is_file():
            return [(resolved_object_prefix, scan_root)]
        if not scan_root.exists():
            return []
        candidate_paths = [
            file_path for file_path in sorted(scan_root.rglob("*")) if file_path.is_file()
        ]

    entries: list[tuple[str, Path]] = []
    for file_path in candidate_paths:
        object_key = file_path.relative_to(dataset_storage.root_dir).as_posix()
        if is_public_project_object_key(project_id=project_id, object_key=object_key):
            entries.append((object_key, file_path))
    return entries


def resolve_requested_object_key(
    *,
    object_key: str | None,
    storage_uri: str | None,
) -> str:
    """统一解析 object_key 和兼容 storage_uri 参数。"""

    candidates = [
        candidate.strip()
        for candidate in (object_key, storage_uri)
        if candidate is not None and candidate.strip()
    ]
    if not candidates:
        raise InvalidRequestError("object_key 或 storage_uri 至少需要提供一个")
    if len(set(candidates)) > 1:
        raise InvalidRequestError(
            "object_key 和 storage_uri 不能同时提供不同的值",
            details={"object_key": object_key, "storage_uri": storage_uri},
        )
    return candidates[0]


def resolve_requested_object_prefix(
    *,
    object_prefix: str | None,
    storage_prefix: str | None,
) -> str | None:
    """统一解析 object_prefix 和兼容 storage_prefix 参数。"""

    candidates = [
        candidate.strip()
        for candidate in (object_prefix, storage_prefix)
        if candidate is not None and candidate.strip()
    ]
    if not candidates:
        return None
    if len(set(candidates)) > 1:
        raise InvalidRequestError(
            "object_prefix 和 storage_prefix 不能同时提供不同的值",
            details={"object_prefix": object_prefix, "storage_prefix": storage_prefix},
        )
    return candidates[0]

