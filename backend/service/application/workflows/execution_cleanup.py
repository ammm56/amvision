"""workflow 执行期临时资源清理注册表与分发接口。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from backend.service.application.errors import ServiceConfigurationError, ServiceError

if TYPE_CHECKING:
    from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext


WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY = "workflow_execution_cleanup_items"
WORKFLOW_DEPLOYMENT_CLEANUP_IDS_KEY = "workflow_deployment_cleanup_ids"
WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE = "deployment_instance"
WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT = "dataset_storage_object"
WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE = "dataset_storage_tree"


@dataclass(frozen=True)
class WorkflowExecutionCleanupItem:
    """描述一条 workflow 执行结束后需要回收的临时资源。

    字段：
    - resource_kind：资源类型标识，用于分发给对应 cleanup handler。
    - resource_id：资源唯一标识。
    - metadata：清理时可能需要的附加元数据。
    """

    resource_kind: str
    resource_id: str
    metadata: dict[str, object] = field(default_factory=dict)


class WorkflowExecutionCleanupHandler(Protocol):
    """定义单类临时资源的 cleanup handler 接口。"""

    def __call__(
        self,
        *,
        cleanup: WorkflowExecutionCleanupItem,
        runtime_context: WorkflowServiceNodeRuntimeContext,
    ) -> list[dict[str, object]]:
        """执行一条临时资源清理。

        参数：
        - cleanup：待清理的临时资源描述。
        - runtime_context：当前 workflow service node 运行时上下文。

        返回：
        - list[dict[str, object]]：清理过程中收集到的错误详情列表；空列表表示成功。
        """


def register_execution_cleanup(
    execution_metadata: dict[str, object],
    *,
    resource_kind: str,
    resource_id: str,
    metadata: dict[str, object] | None = None,
) -> None:
    """登记执行结束后需要清理的一条临时资源。

    参数：
    - execution_metadata：当前 workflow 执行元数据。
    - resource_kind：资源类型标识。
    - resource_id：资源唯一标识。
    - metadata：清理阶段需要的附加元数据。
    """

    normalized_resource_kind = resource_kind.strip()
    normalized_resource_id = resource_id.strip()
    if not normalized_resource_kind or not normalized_resource_id:
        return
    normalized_metadata = _normalize_cleanup_metadata(metadata)
    raw_items = execution_metadata.get(WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY)
    if not isinstance(raw_items, list):
        raw_items = []
        execution_metadata[WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY] = raw_items
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        if raw_item.get("resource_kind") != normalized_resource_kind:
            continue
        if raw_item.get("resource_id") != normalized_resource_id:
            continue
        existing_metadata = raw_item.get("metadata")
        if isinstance(existing_metadata, dict):
            existing_metadata.update(normalized_metadata)
        elif normalized_metadata:
            raw_item["metadata"] = dict(normalized_metadata)
        return
    raw_items.append(
        {
            "resource_kind": normalized_resource_kind,
            "resource_id": normalized_resource_id,
            "metadata": dict(normalized_metadata),
        }
    )


def list_registered_execution_cleanups(
    execution_metadata: dict[str, object],
) -> tuple[WorkflowExecutionCleanupItem, ...]:
    """读取当前 workflow 执行里登记的临时资源清理列表。

    参数：
    - execution_metadata：当前 workflow 执行元数据。

    返回：
    - tuple[WorkflowExecutionCleanupItem, ...]：已规范化并去重后的临时资源清理项。
    """

    normalized_items: list[WorkflowExecutionCleanupItem] = []
    normalized_item_index: dict[tuple[str, str], int] = {}
    raw_items = execution_metadata.get(WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY)
    if isinstance(raw_items, list):
        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            normalized_resource_kind = raw_item.get("resource_kind")
            normalized_resource_id = raw_item.get("resource_id")
            if not isinstance(normalized_resource_kind, str) or not isinstance(normalized_resource_id, str):
                continue
            normalized_resource_kind = normalized_resource_kind.strip()
            normalized_resource_id = normalized_resource_id.strip()
            if not normalized_resource_kind or not normalized_resource_id:
                continue
            _append_or_merge_cleanup_item(
                normalized_items,
                normalized_item_index,
                WorkflowExecutionCleanupItem(
                    resource_kind=normalized_resource_kind,
                    resource_id=normalized_resource_id,
                    metadata=_normalize_cleanup_metadata(raw_item.get("metadata")),
                ),
            )

    raw_legacy_deployment_ids = execution_metadata.get(WORKFLOW_DEPLOYMENT_CLEANUP_IDS_KEY)
    if isinstance(raw_legacy_deployment_ids, list):
        for raw_deployment_id in raw_legacy_deployment_ids:
            if not isinstance(raw_deployment_id, str):
                continue
            normalized_deployment_id = raw_deployment_id.strip()
            if not normalized_deployment_id:
                continue
            _append_or_merge_cleanup_item(
                normalized_items,
                normalized_item_index,
                WorkflowExecutionCleanupItem(
                    resource_kind=WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE,
                    resource_id=normalized_deployment_id,
                ),
            )
    return tuple(normalized_items)


def execute_registered_execution_cleanups(
    *,
    execution_metadata: dict[str, object],
    runtime_context: WorkflowServiceNodeRuntimeContext,
    handlers: dict[str, WorkflowExecutionCleanupHandler],
) -> ServiceConfigurationError | None:
    """按登记项和 handler 映射执行 workflow 临时资源 cleanup。

    参数：
    - execution_metadata：当前 workflow 执行元数据。
    - runtime_context：当前 workflow service node 运行时上下文。
    - handlers：按资源类型组织的 cleanup handler 映射。

    返回：
    - ServiceConfigurationError | None：全部成功时返回 None；存在任何 cleanup 失败时返回聚合错误。
    """

    cleanup_items = list_registered_execution_cleanups(execution_metadata)
    if not cleanup_items:
        return None
    cleanup_errors: list[dict[str, object]] = []
    for cleanup_item in cleanup_items:
        handler = handlers.get(cleanup_item.resource_kind)
        if handler is None:
            cleanup_errors.append(
                _build_cleanup_error_detail(
                    cleanup_item,
                    action="dispatch",
                    error_code="workflow_execution_cleanup_handler_not_found",
                    error_message=f"未找到资源类型 {cleanup_item.resource_kind} 的 cleanup handler",
                )
            )
            continue
        try:
            cleanup_errors.extend(
                _normalize_cleanup_error_details(
                    cleanup_item,
                    handler(cleanup=cleanup_item, runtime_context=runtime_context),
                )
            )
        except ServiceError as exc:
            cleanup_errors.append(
                _build_cleanup_error_detail(
                    cleanup_item,
                    action="cleanup",
                    error_code=exc.code,
                    error_message=exc.message,
                )
            )
        except Exception as exc:  # pragma: no cover - 兜底分支靠行为测试覆盖
            cleanup_errors.append(
                _build_cleanup_error_detail(
                    cleanup_item,
                    action="cleanup",
                    error_code="workflow_execution_cleanup_handler_failed",
                    error_message=str(exc) or exc.__class__.__name__,
                )
            )
    if not cleanup_errors:
        return None
    return ServiceConfigurationError(
        "workflow 执行结束后清理临时资源失败",
        details={"cleanup_errors": cleanup_errors},
    )


def register_deployment_cleanup(
    execution_metadata: dict[str, object],
    *,
    deployment_instance_id: str,
) -> None:
    """登记执行结束后需要清理的 DeploymentInstance。

    参数：
    - execution_metadata：当前 workflow 执行元数据。
    - deployment_instance_id：需要在执行结束后清理的 DeploymentInstance id。
    """

    register_execution_cleanup(
        execution_metadata,
        resource_kind=WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE,
        resource_id=deployment_instance_id,
    )


def register_dataset_storage_object_cleanup(
    execution_metadata: dict[str, object],
    *,
    object_key: str,
) -> None:
    """登记执行结束后需要删除的 dataset storage 单文件对象。

    参数：
    - execution_metadata：当前 workflow 执行元数据。
    - object_key：要删除的 dataset storage 相对路径。
    """

    register_execution_cleanup(
        execution_metadata,
        resource_kind=WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT,
        resource_id=object_key,
    )


def register_dataset_storage_tree_cleanup(
    execution_metadata: dict[str, object],
    *,
    relative_path: str,
) -> None:
    """登记执行结束后需要删除的 dataset storage 目录树。

    参数：
    - execution_metadata：当前 workflow 执行元数据。
    - relative_path：要删除的 dataset storage 相对目录。
    """

    register_execution_cleanup(
        execution_metadata,
        resource_kind=WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_TREE,
        resource_id=relative_path,
    )


def list_registered_deployment_cleanup_ids(
    execution_metadata: dict[str, object],
) -> tuple[str, ...]:
    """读取当前 workflow 执行里登记的 DeploymentInstance 清理列表。

    参数：
    - execution_metadata：当前 workflow 执行元数据。

    返回：
    - tuple[str, ...]：已登记且去重后的 DeploymentInstance id 列表。
    """

    return tuple(
        cleanup_item.resource_id
        for cleanup_item in list_registered_execution_cleanups(execution_metadata)
        if cleanup_item.resource_kind == WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE
    )


def _append_or_merge_cleanup_item(
    normalized_items: list[WorkflowExecutionCleanupItem],
    normalized_item_index: dict[tuple[str, str], int],
    cleanup_item: WorkflowExecutionCleanupItem,
) -> None:
    """向规范化列表追加或合并一条 cleanup 项。"""

    item_key = (cleanup_item.resource_kind, cleanup_item.resource_id)
    existing_index = normalized_item_index.get(item_key)
    if existing_index is None:
        normalized_item_index[item_key] = len(normalized_items)
        normalized_items.append(cleanup_item)
        return
    existing_item = normalized_items[existing_index]
    merged_metadata = dict(existing_item.metadata)
    merged_metadata.update(cleanup_item.metadata)
    normalized_items[existing_index] = WorkflowExecutionCleanupItem(
        resource_kind=existing_item.resource_kind,
        resource_id=existing_item.resource_id,
        metadata=merged_metadata,
    )


def _normalize_cleanup_metadata(raw_metadata: object) -> dict[str, object]:
    """把外部 metadata 规范化为可序列化的字符串键字典。"""

    if not isinstance(raw_metadata, dict):
        return {}
    normalized_metadata: dict[str, object] = {}
    for key, value in raw_metadata.items():
        if isinstance(key, str):
            normalized_metadata[key] = value
    return normalized_metadata


def _normalize_cleanup_error_details(
    cleanup_item: WorkflowExecutionCleanupItem,
    raw_errors: object,
) -> list[dict[str, object]]:
    """把 handler 返回的错误详情规范化到统一结构。"""

    if not isinstance(raw_errors, list):
        return []
    normalized_errors: list[dict[str, object]] = []
    for raw_error in raw_errors:
        if isinstance(raw_error, dict):
            normalized_error = dict(raw_error)
        else:
            normalized_error = {
                "action": "cleanup",
                "error_code": "workflow_execution_cleanup_handler_failed",
                "error_message": str(raw_error),
            }
        normalized_error.setdefault("resource_kind", cleanup_item.resource_kind)
        normalized_error.setdefault("resource_id", cleanup_item.resource_id)
        normalized_errors.append(normalized_error)
    return normalized_errors


def _build_cleanup_error_detail(
    cleanup_item: WorkflowExecutionCleanupItem,
    *,
    action: str,
    error_code: str,
    error_message: str,
) -> dict[str, object]:
    """构造一条统一的 cleanup 错误详情。"""

    return {
        "resource_kind": cleanup_item.resource_kind,
        "resource_id": cleanup_item.resource_id,
        "action": action,
        "error_code": error_code,
        "error_message": error_message,
    }