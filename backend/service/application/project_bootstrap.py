"""Project 目录 bootstrap 与 manifest 读写辅助。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from backend.service.application.errors import InvalidRequestError
from backend.service.infrastructure.object_store.local_dataset_storage import LocalDatasetStorage


PROJECT_MANIFEST_FILE_NAME = "project.json"
PROJECT_BOOTSTRAP_WORKSPACE_DIRS = (
    "inputs",
    "results",
    "datasets",
    "workflow/templates",
    "workflow/applications",
)


@dataclass(frozen=True)
class ProjectBootstrapRequest:
    """描述一次 Project 初始化请求。

    字段：
    - project_id：Project id，同时也是磁盘目录名。
    - display_name：可选展示名称；为空时回退到 project_id。
    - description：可选项目说明。
    - metadata：附加元数据。
    """

    project_id: str
    display_name: str | None = None
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectManifest:
    """描述保存在项目目录里的最小 Project manifest。

    字段：
    - project_id：Project id。
    - display_name：展示名称。
    - description：项目说明。
    - metadata：附加元数据。
    - created_at：初始化时间。
    - updated_at：最近更新时间。
    - initialized_by：执行初始化的主体 id。
    """

    project_id: str
    display_name: str
    description: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    initialized_by: str | None = None


class LocalProjectBootstrapService:
    """基于本地 ObjectStore 管理 Project 初始化目录和 manifest。"""

    def __init__(self, *, dataset_storage: LocalDatasetStorage) -> None:
        """初始化 Project bootstrap 服务。

        参数：
        - dataset_storage：本地 ObjectStore 服务。
        """

        self.dataset_storage = dataset_storage

    def bootstrap_project(
        self,
        request: ProjectBootstrapRequest,
        *,
        initialized_by: str | None,
    ) -> ProjectManifest:
        """初始化一个 Project 目录和最小 manifest。

        参数：
        - request：Project 初始化请求。
        - initialized_by：执行初始化的主体 id。

        返回：
        - ProjectManifest：已写入本地磁盘的项目 manifest。
        """

        normalized_project_id = _normalize_identifier(request.project_id, field_name="project_id")
        existing_manifest = self.get_project_manifest(normalized_project_id)
        if existing_manifest is not None:
            raise InvalidRequestError(
                "Project 已初始化",
                details={"project_id": normalized_project_id},
            )

        self._ensure_project_workspace(normalized_project_id)
        now = _now_isoformat()
        manifest = ProjectManifest(
            project_id=normalized_project_id,
            display_name=(
                _normalize_optional_non_empty_text(request.display_name, field_name="display_name")
                or normalized_project_id
            ),
            description=_normalize_optional_non_empty_text(request.description, field_name="description"),
            metadata=dict(request.metadata),
            created_at=now,
            updated_at=now,
            initialized_by=_normalize_optional_non_empty_text(initialized_by, field_name="initialized_by"),
        )
        self.dataset_storage.write_json(
            build_project_manifest_object_key(normalized_project_id),
            _serialize_project_manifest(manifest),
        )
        return manifest

    def get_project_manifest(self, project_id: str) -> ProjectManifest | None:
        """读取一个 Project 的本地 manifest。

        参数：
        - project_id：目标 Project id。

        返回：
        - ProjectManifest | None：存在时返回 manifest，否则返回 None。
        """

        normalized_project_id = _normalize_identifier(project_id, field_name="project_id")
        object_key = build_project_manifest_object_key(normalized_project_id)
        manifest_path = self.dataset_storage.resolve(object_key)
        if not manifest_path.is_file():
            return None
        payload = self.dataset_storage.read_json(object_key)
        if not isinstance(payload, dict):
            raise InvalidRequestError(
                "Project manifest 格式不合法",
                details={"project_id": normalized_project_id},
            )
        return _build_project_manifest_from_payload(normalized_project_id, payload)

    def _ensure_project_workspace(self, project_id: str) -> None:
        """确保 Project 根目录和最小工作区目录存在。"""

        self.dataset_storage.resolve(build_project_root_object_key(project_id)).mkdir(parents=True, exist_ok=True)
        for relative_dir in PROJECT_BOOTSTRAP_WORKSPACE_DIRS:
            self.dataset_storage.resolve(
                f"{build_project_root_object_key(project_id)}/{relative_dir}"
            ).mkdir(parents=True, exist_ok=True)


def build_project_root_object_key(project_id: str) -> str:
    """返回 Project 根目录 object key。"""

    normalized_project_id = _normalize_identifier(project_id, field_name="project_id")
    return f"projects/{normalized_project_id}"


def build_project_manifest_object_key(project_id: str) -> str:
    """返回 Project manifest 文件 object key。"""

    normalized_project_id = _normalize_identifier(project_id, field_name="project_id")
    return f"{build_project_root_object_key(normalized_project_id)}/{PROJECT_MANIFEST_FILE_NAME}"


def _serialize_project_manifest(manifest: ProjectManifest) -> dict[str, object]:
    """把 ProjectManifest 转成稳定 JSON 字典。"""

    return {
        "project_id": manifest.project_id,
        "display_name": manifest.display_name,
        "description": manifest.description,
        "metadata": dict(manifest.metadata),
        "created_at": manifest.created_at,
        "updated_at": manifest.updated_at,
        "initialized_by": manifest.initialized_by,
    }


def _build_project_manifest_from_payload(
    project_id: str,
    payload: dict[str, object],
) -> ProjectManifest:
    """把 JSON 载荷恢复为 ProjectManifest。"""

    payload_project_id = _read_required_str(payload, "project_id")
    if payload_project_id != project_id:
        raise InvalidRequestError(
            "Project manifest 与目录不一致",
            details={"project_id": project_id, "payload_project_id": payload_project_id},
        )
    display_name = _read_required_str(payload, "display_name")
    metadata = payload.get("metadata")
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise InvalidRequestError(
            "Project manifest.metadata 格式不合法",
            details={"project_id": project_id},
        )
    return ProjectManifest(
        project_id=payload_project_id,
        display_name=display_name,
        description=_normalize_optional_non_empty_text(_read_optional_str(payload, "description"), field_name="description"),
        metadata=dict(metadata),
        created_at=_read_required_str(payload, "created_at"),
        updated_at=_read_required_str(payload, "updated_at"),
        initialized_by=_normalize_optional_non_empty_text(
            _read_optional_str(payload, "initialized_by"),
            field_name="initialized_by",
        ),
    )


def _normalize_identifier(value: str, *, field_name: str) -> str:
    """规范化 project_id 这类路径关键标识。"""

    normalized_value = value.strip()
    if not normalized_value:
        raise InvalidRequestError(f"{field_name} 不能为空")
    if "/" in normalized_value or "\\" in normalized_value or ".." in normalized_value:
        raise InvalidRequestError(
            f"{field_name} 不能包含路径分隔符或父目录引用",
            details={field_name: normalized_value},
        )
    return normalized_value


def _normalize_optional_non_empty_text(value: str | None, *, field_name: str) -> str | None:
    """规范化可选非空文本。"""

    if value is None:
        return None
    normalized_value = value.strip()
    if not normalized_value:
        raise InvalidRequestError(
            f"{field_name} 不能为空字符串",
            details={field_name: value},
        )
    return normalized_value


def _read_required_str(payload: dict[str, object], field_name: str) -> str:
    """读取 manifest 里的必填字符串字段。"""

    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise InvalidRequestError(
            f"Project manifest.{field_name} 缺失或不合法",
            details={field_name: value},
        )
    return value.strip()


def _read_optional_str(payload: dict[str, object], field_name: str) -> str | None:
    """读取 manifest 里的可选字符串字段。"""

    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidRequestError(
            f"Project manifest.{field_name} 格式不合法",
            details={field_name: value},
        )
    return value


def _now_isoformat() -> str:
    """返回当前 UTC 时间的 ISO8601 字符串。"""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")