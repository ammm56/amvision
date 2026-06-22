"""workflow 文档对象存储辅助函数。"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.documents.contracts import WorkflowStoredResourceSummary
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


_WORKFLOW_ROOT_DIR = "workflows/projects"


def build_resource_summary_for_save(
    *,
    dataset_storage: LocalDatasetStorage,
    object_key: str,
    actor_id: str | None,
) -> WorkflowStoredResourceSummary:
    """为 workflow 文档保存动作构建 sidecar 摘要。"""

    normalized_actor_id = _normalize_optional_text(actor_id)
    existing_summary: WorkflowStoredResourceSummary | None = None
    if dataset_storage.resolve(object_key).is_file():
        existing_summary = read_resource_summary(
            dataset_storage=dataset_storage,
            object_key=object_key,
        )
    now = _now_isoformat()
    return WorkflowStoredResourceSummary(
        created_at=(existing_summary.created_at if existing_summary is not None else now),
        updated_at=now,
        created_by=(
            existing_summary.created_by
            if existing_summary is not None and existing_summary.created_by is not None
            else normalized_actor_id
        ),
        updated_by=(
            normalized_actor_id
            if normalized_actor_id is not None
            else existing_summary.updated_by if existing_summary is not None else None
        ),
    )


def read_resource_summary(
    *,
    dataset_storage: LocalDatasetStorage,
    object_key: str,
) -> WorkflowStoredResourceSummary:
    """读取 workflow 文档的 sidecar 摘要。"""

    summary_key = build_resource_summary_object_key(object_key)
    summary_path = dataset_storage.resolve(summary_key)
    if summary_path.is_file():
        payload = dataset_storage.read_json(summary_key)
        summary = _parse_resource_summary_payload(payload)
        if summary is not None:
            return summary
    created_at, updated_at = _read_object_timestamps(
        dataset_storage=dataset_storage,
        object_key=object_key,
    )
    return WorkflowStoredResourceSummary(
        created_at=created_at,
        updated_at=updated_at,
    )


def write_resource_summary(
    *,
    dataset_storage: LocalDatasetStorage,
    object_key: str,
    summary: WorkflowStoredResourceSummary,
) -> None:
    """写入 workflow 文档的 sidecar 摘要。"""

    dataset_storage.write_json(
        build_resource_summary_object_key(object_key),
        {
            "created_at": summary.created_at,
            "updated_at": summary.updated_at,
            "created_by": summary.created_by,
            "updated_by": summary.updated_by,
        },
    )


def build_resource_summary_object_key(object_key: str) -> str:
    """把主 JSON 路径转换为 sidecar 摘要路径。"""

    if object_key.endswith(".json"):
        return f"{object_key[:-5]}.summary.json"
    return f"{object_key}.summary.json"


def build_template_object_key(
    *,
    project_id: str,
    template_id: str,
    template_version: str,
) -> str:
    """构建图模板 JSON 的对象路径。"""

    return (
        f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates/{template_id}"
        f"/versions/{template_version}/template.json"
    )


def build_templates_dir_key(*, project_id: str) -> str:
    """构建当前 Project 的图模板根目录对象路径。"""

    return f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates"


def build_template_versions_dir_key(*, project_id: str, template_id: str) -> str:
    """构建指定图模板的版本目录对象路径。"""

    return f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates/{template_id}/versions"


def build_template_version_directory_key(
    *,
    project_id: str,
    template_id: str,
    template_version: str,
) -> str:
    """构建指定图模板版本目录对象路径。"""

    return f"{_WORKFLOW_ROOT_DIR}/{project_id}/templates/{template_id}/versions/{template_version}"


def build_application_object_key(
    *,
    project_id: str,
    application_id: str,
) -> str:
    """构建流程应用 JSON 的对象路径。"""

    return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications/{application_id}/application.json"


def build_applications_dir_key(*, project_id: str) -> str:
    """构建当前 Project 的流程应用根目录对象路径。"""

    return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications"


def build_application_directory_key(*, project_id: str, application_id: str) -> str:
    """构建单个流程应用目录对象路径。"""

    return f"{_WORKFLOW_ROOT_DIR}/{project_id}/applications/{application_id}"


def to_object_key(*, dataset_storage: LocalDatasetStorage, path: Path) -> str:
    """把本地绝对路径转换回对象存储相对路径。"""

    return path.relative_to(dataset_storage.root_dir).as_posix()


def build_natural_sort_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """构建用于 template_version 和类似标识的自然排序键。"""

    parts = re.split(r"(\d+)", value)
    return tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts if part)


def normalize_identifier(value: str, field_name: str) -> str:
    """校验 project_id、template_id 等路径关键字段。"""

    normalized_value = value.strip()
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    if "/" in normalized_value or "\\" in normalized_value or ".." in normalized_value:
        raise InvalidRequestError(
            f"{field_name} 不能包含路径分隔符或父目录引用",
            details={field_name: normalized_value},
        )
    return normalized_value


def normalize_optional_non_empty_text(value: str | None, field_name: str) -> str | None:
    """规范化可选非空文本；传空白字符串时抛出请求错误。"""

    if value is None:
        return None
    normalized_value = value.strip()
    if not normalized_value:
        raise InvalidRequestError(
            f"{field_name} 不能为空字符串",
            details={field_name: value},
        )
    return normalized_value


def _parse_resource_summary_payload(payload: object) -> WorkflowStoredResourceSummary | None:
    """把 sidecar JSON 解析为资源摘要。"""

    if not isinstance(payload, dict):
        return None
    created_at = payload.get("created_at")
    updated_at = payload.get("updated_at")
    if not isinstance(created_at, str) or not created_at.strip():
        return None
    if not isinstance(updated_at, str) or not updated_at.strip():
        return None
    return WorkflowStoredResourceSummary(
        created_at=created_at,
        updated_at=updated_at,
        created_by=_normalize_optional_text(payload.get("created_by")),
        updated_by=_normalize_optional_text(payload.get("updated_by")),
    )


def _read_object_timestamps(
    *,
    dataset_storage: LocalDatasetStorage,
    object_key: str,
) -> tuple[str, str]:
    """读取 workflow JSON 文件的创建和更新时间。"""

    file_stat = dataset_storage.resolve(object_key).stat()
    created_at = datetime.fromtimestamp(file_stat.st_ctime, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    updated_at = datetime.fromtimestamp(file_stat.st_mtime, tz=timezone.utc).isoformat().replace(
        "+00:00",
        "Z",
    )
    return created_at, updated_at


def _normalize_optional_text(value: object) -> str | None:
    """规范化可选字符串值。"""

    if not isinstance(value, str):
        return None
    normalized_value = value.strip()
    return normalized_value or None


def _now_isoformat() -> str:
    """返回当前 UTC 时间字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
