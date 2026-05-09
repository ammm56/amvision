"""workflow 执行期通用 cleanup 接口测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_DEPLOYMENT_CLEANUP_IDS_KEY,
    WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE,
    execute_registered_execution_cleanups,
    list_registered_deployment_cleanup_ids,
    list_registered_execution_cleanups,
    register_deployment_cleanup,
    register_execution_cleanup,
)


def test_register_execution_cleanup_lists_generic_items_and_keeps_deployment_compatibility() -> None:
    """验证通用 cleanup 注册表会去重合并，并兼容旧 deployment id 列表。"""

    execution_metadata: dict[str, object] = {
        WORKFLOW_DEPLOYMENT_CLEANUP_IDS_KEY: [" legacy-deployment-1 ", "deployment-1", None],
    }

    register_execution_cleanup(
        execution_metadata,
        resource_kind=" temporary_file ",
        resource_id=" file-1 ",
        metadata={"path": "artifacts/demo.txt"},
    )
    register_execution_cleanup(
        execution_metadata,
        resource_kind="temporary_file",
        resource_id="file-1",
        metadata={"bucket": "preview-cache"},
    )
    register_deployment_cleanup(execution_metadata, deployment_instance_id=" deployment-1 ")

    registered_items = list_registered_execution_cleanups(execution_metadata)

    assert [
        (item.resource_kind, item.resource_id, item.metadata)
        for item in registered_items
    ] == [
        (
            "temporary_file",
            "file-1",
            {"path": "artifacts/demo.txt", "bucket": "preview-cache"},
        ),
        (WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE, "deployment-1", {}),
        (WORKFLOW_EXECUTION_CLEANUP_KIND_DEPLOYMENT_INSTANCE, "legacy-deployment-1", {}),
    ]
    assert list_registered_deployment_cleanup_ids(execution_metadata) == (
        "deployment-1",
        "legacy-deployment-1",
    )


def test_execute_registered_execution_cleanups_dispatches_handlers_and_reports_missing_kind() -> None:
    """验证通用 cleanup 执行接口会按资源类型分发，并聚合缺失 handler 错误。"""

    execution_metadata: dict[str, object] = {}
    handled_items: list[tuple[str, str, str]] = []

    register_execution_cleanup(
        execution_metadata,
        resource_kind="temporary_file",
        resource_id="file-1",
        metadata={"path": "artifacts/demo.txt"},
    )
    register_execution_cleanup(
        execution_metadata,
        resource_kind="missing_resource",
        resource_id="resource-1",
    )

    def _temporary_file_cleanup_handler(*, cleanup, runtime_context) -> list[dict[str, object]]:
        handled_items.append(
            (cleanup.resource_kind, cleanup.resource_id, runtime_context.runtime_name)
        )
        return []

    cleanup_error = execute_registered_execution_cleanups(
        execution_metadata=execution_metadata,
        runtime_context=SimpleNamespace(runtime_name="test-runtime"),
        handlers={"temporary_file": _temporary_file_cleanup_handler},
    )

    assert handled_items == [("temporary_file", "file-1", "test-runtime")]
    assert isinstance(cleanup_error, ServiceConfigurationError)
    assert cleanup_error.details["cleanup_errors"] == [
        {
            "resource_kind": "missing_resource",
            "resource_id": "resource-1",
            "action": "dispatch",
            "error_code": "workflow_execution_cleanup_handler_not_found",
            "error_message": "未找到资源类型 missing_resource 的 cleanup handler",
        }
    ]