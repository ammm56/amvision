"""workflow runtime 输入输出脱敏测试。"""

from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event, RLock, Thread
from types import SimpleNamespace
from typing import Iterator

import pytest

from backend.contracts.buffers import BufferRef
from backend.contracts.workflows.workflow_graph import (
    FlowApplication,
    FlowApplicationBinding,
    FlowTemplateReference,
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import (
    OperationCancelledError,
    ResourceConflictError,
    ResourceNotFoundError,
    ServiceConfigurationError,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY,
    WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
)
from backend.service.application.workflows.preview_run_manager import (
    WorkflowPreviewRunManager,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.workflows.service_runtime.context import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.model_sessions import (
    WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY,
    WORKFLOW_MODEL_SESSION_SCOPE_WAIT_ENABLED_METADATA_KEY,
)
from backend.service.application.workflows.runtime_payload_sanitizer import (
    MAX_PERSISTED_COLLECTION_ITEMS,
    MAX_PERSISTED_STRING_CHARS,
    sanitize_runtime_mapping,
)
from backend.service.application.workflows.runtime_service import (
    WorkflowAppRuntimeCreateRequest,
    WorkflowAppRuntimeSelectVersionRequest,
    WorkflowPreviewRunCreateRequest,
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeService,
)
from backend.service.application.workflows.app_version_service import (
    compute_workflow_app_content_fingerprint,
)
from backend.service.application.workflows.worker.health import (
    WorkflowRuntimeWorkerState,
)
from backend.service.application.workflows.worker.messages import (
    WorkflowRuntimeWorkerRunResult,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from backend.service.domain.workflows.workflow_runtime_records import WorkflowRun
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
)
from tests.api_test_support import build_valid_test_png_bytes, create_test_runtime


def test_preview_run_sync_response_keeps_inline_base64_but_persisted_copy_is_sanitized(
    tmp_path: Path,
) -> None:
    """验证 preview run 同步响应返回 raw base64，而持久化详情仍会脱敏。"""

    service, _, _ = _build_runtime_service(tmp_path)
    image_base64 = base64.b64encode(build_valid_test_png_bytes()).decode("ascii")

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_image_decode_preview_application(),
            template=_build_image_decode_preview_template(),
            input_bindings={"request_image_base64": {"image_base64": image_base64}},
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    assert (
        preview_run.metadata[WORKFLOW_MODEL_SESSION_SCOPE_ID_METADATA_KEY]
        == "preview:project-1:image-decode-preview-app"
    )
    assert (
        preview_run.metadata[WORKFLOW_MODEL_SESSION_SCOPE_WAIT_ENABLED_METADATA_KEY]
        is False
    )
    preview_image = preview_run.outputs["http_response"]["body"]["image"]
    assert preview_image["transport_kind"] == "inline-base64"
    assert preview_image["image_base64"] == image_base64
    assert (
        preview_run.template_outputs["http_response"]["body"]["image"]["image_base64"]
        == image_base64
    )
    assert (
        preview_run.node_records[0]["inputs"]["payload"]["image_base64_redacted"]
        is True
    )
    assert preview_run.node_records[0]["outputs"]["image"]["image_handle"]
    assert (
        preview_run.node_records[1]["inputs"]["image"]["image_handle_redacted"] is True
    )
    assert (
        preview_run.node_records[1]["outputs"]["body"]["image"]["image_base64"]
        == image_base64
    )
    persisted_preview_run = service.get_preview_run(preview_run.preview_run_id)
    persisted_preview_image = persisted_preview_run.outputs["http_response"]["body"][
        "image"
    ]
    assert persisted_preview_image["image_base64_redacted"] is True
    assert "image_base64" not in persisted_preview_image
    assert (
        persisted_preview_run.template_outputs["http_response"]["body"]["image"][
            "image_base64_redacted"
        ]
        is True
    )
    assert (
        persisted_preview_run.node_records[0]["outputs"]["image"][
            "image_handle_redacted"
        ]
        is True
    )
    assert (
        persisted_preview_run.node_records[1]["outputs"]["body"]["image"][
            "image_base64_redacted"
        ]
        is True
    )


def test_preview_run_storage_ref_image_preview_uses_preview_artifact(
    tmp_path: Path,
) -> None:
    """验证 storage-ref Image Preview 会保存到 Preview Run artifact 目录。"""

    service, _, _ = _build_runtime_service(tmp_path)
    image_base64 = base64.b64encode(build_valid_test_png_bytes()).decode("ascii")

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_image_decode_save_preview_application(),
            template=_build_image_decode_save_preview_template(),
            input_bindings={"request_image_base64": {"image_base64": image_base64}},
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    preview_image = preview_run.outputs["http_response"]["body"]["image"]
    object_key = preview_image["object_key"]
    assert preview_image["transport_kind"] == "storage-ref"
    assert object_key.startswith(
        f"workflows/runtime/preview-runs/{preview_run.preview_run_id}/artifacts/preview/"
    )
    assert service.dataset_storage.resolve(object_key).exists()
    persisted_preview_run = service.get_preview_run(preview_run.preview_run_id)
    assert (
        persisted_preview_run.outputs["http_response"]["body"]["image"]["object_key"]
        == object_key
    )


def test_invoke_workflow_run_sanitizes_input_payload_outputs_and_node_records(
    tmp_path: Path,
) -> None:
    """验证同步 WorkflowRun 会对输入、输出和节点记录做脱敏。"""

    worker_result = WorkflowRuntimeWorkerRunResult(
        state="succeeded",
        outputs={
            "http_response": {
                "status_code": 200,
                "body": {
                    "type": "image-preview",
                    "image": {
                        "transport_kind": "inline-base64",
                        "image_base64": "ZmFrZS1vdXRwdXQ=",
                        "media_type": "image/png",
                    },
                },
            }
        },
        template_outputs={
            "http_response": {
                "status_code": 200,
                "body": {
                    "type": "image-preview",
                    "image": {
                        "transport_kind": "inline-base64",
                        "image_base64": "ZmFrZS10ZW1wbGF0ZS1vdXRwdXQ=",
                        "media_type": "image/png",
                    },
                },
            }
        },
        node_records=(
            {
                "node_id": "decode",
                "node_type_id": "core.io.image-base64-decode",
                "runtime_kind": "python-callable",
                "inputs": {
                    "payload": {
                        "image_base64": "ZmFrZS1pbnB1dA==",
                        "media_type": "image/png",
                    }
                },
                "outputs": {
                    "image": {
                        "transport_kind": "memory",
                        "image_handle": "img-decode-1",
                        "media_type": "image/png",
                    }
                },
            },
        ),
        worker_state=WorkflowRuntimeWorkerState(
            observed_state="running",
            process_id=321,
            health_summary={"worker_state": "running"},
        ),
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=_FakeWorkerManager(worker_result=worker_result),
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    workflow_run = service.invoke_workflow_app_runtime(
        runtime.workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings={
                "request_image_base64": {
                    "image_base64": "ZmFrZS1yZXF1ZXN0",
                    "media_type": "image/png",
                }
            },
            execution_metadata={
                "workflow_run_record_mode": "full",
                "retain_node_records_enabled": True,
            },
        ),
        created_by="workflow-user",
    )

    assert workflow_run.state == "succeeded"
    assert (
        workflow_run.input_payload["request_image_base64"]["image_base64_redacted"]
        is True
    )
    assert "image_base64" not in workflow_run.input_payload["request_image_base64"]
    assert (
        workflow_run.outputs["http_response"]["body"]["image"]["image_base64_redacted"]
        is True
    )
    assert (
        workflow_run.template_outputs["http_response"]["body"]["image"][
            "image_base64_redacted"
        ]
        is True
    )
    assert (
        workflow_run.node_records[0]["inputs"]["payload"]["image_base64_redacted"]
        is True
    )
    assert (
        workflow_run.node_records[0]["outputs"]["image"]["image_handle_redacted"]
        is True
    )

    persisted_run = service.get_workflow_run(workflow_run.workflow_run_id)
    assert persisted_run.input_payload == workflow_run.input_payload
    assert persisted_run.outputs == workflow_run.outputs


def test_invoke_workflow_run_defaults_to_light_persistence(tmp_path: Path) -> None:
    """验证正式 WorkflowRun 默认只保留最小状态且不写磁盘 trace。

    参数：
    - tmp_path：pytest 提供的临时目录。
    """

    worker_result = WorkflowRuntimeWorkerRunResult(
        state="succeeded",
        outputs={"http_response": {"status_code": 200}},
        node_records=(
            {
                "node_id": "echo",
                "node_type_id": "custom.test.echo",
                "runtime_kind": "python-callable",
                "inputs": {"text": "hello"},
                "outputs": {"text": "hello"},
            },
        ),
        worker_state=WorkflowRuntimeWorkerState(
            observed_state="running",
            process_id=321,
            health_summary={"worker_state": "running"},
        ),
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=_FakeWorkerManager(worker_result=worker_result),
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    workflow_run = service.invoke_workflow_app_runtime(
        runtime.workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings={"request_text": {"value": "hello"}}
        ),
        created_by="workflow-user",
    )

    persisted_run = service.get_workflow_run(workflow_run.workflow_run_id)
    assert workflow_run.state == "succeeded"
    assert persisted_run.metadata["trace_level"] == "none"
    assert persisted_run.metadata["retain_trace_enabled"] is False
    assert persisted_run.metadata["retain_node_records_enabled"] is False
    assert persisted_run.metadata["workflow_run_record_mode"] == "minimal"
    assert persisted_run.input_payload == {}
    assert persisted_run.outputs == {"http_response": {"status_code": 200}}
    assert persisted_run.template_outputs == {}
    assert persisted_run.node_records == ()
    assert service.get_workflow_run_events(workflow_run.workflow_run_id) == ()
    assert not service.dataset_storage.resolve(
        f"workflows/runtime/{workflow_run.workflow_run_id}"
    ).exists()


def test_invoke_workflow_run_minimal_record_persists_public_result_and_status(
    tmp_path: Path,
) -> None:
    """验证 minimal 记录模式只保存公开结果与 WorkflowRun 状态。"""

    worker_result = WorkflowRuntimeWorkerRunResult(
        state="succeeded",
        outputs={
            "http_response": {
                "status_code": 200,
                "body": {
                    "data": "ok",
                    "metadata": {"timings": {"model_ms": 12.3}},
                },
            }
        },
        template_outputs={"http_response": {"status_code": 200}},
        node_records=(
            {
                "node_id": "echo",
                "node_type_id": "custom.test.echo",
                "runtime_kind": "python-callable",
                "inputs": {"text": "hello"},
                "outputs": {"text": "hello"},
            },
        ),
        worker_state=WorkflowRuntimeWorkerState(
            observed_state="running",
            process_id=321,
            health_summary={"worker_state": "running"},
        ),
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=_FakeWorkerManager(worker_result=worker_result),
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    workflow_run = service.invoke_workflow_app_runtime(
        runtime.workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings={"request_text": {"value": "hello"}},
            execution_metadata={"workflow_run_record_mode": "minimal"},
        ),
        created_by="workflow-user",
    )

    persisted_run = service.get_workflow_run(workflow_run.workflow_run_id)
    assert persisted_run.state == "succeeded"
    assert persisted_run.input_payload == {}
    assert persisted_run.outputs == {
        "http_response": {
            "status_code": 200,
            "body": {"data": "ok", "metadata": {}},
        }
    }
    assert persisted_run.template_outputs == {}
    assert persisted_run.node_records == ()
    assert "timings" not in persisted_run.metadata
    assert service.get_workflow_run_events(workflow_run.workflow_run_id) == ()


def test_invoke_workflow_run_none_record_mode_skips_database_record(
    tmp_path: Path,
) -> None:
    """验证 none 记录模式的同步调用不写 WorkflowRun 数据库记录。"""

    worker_result = WorkflowRuntimeWorkerRunResult(
        state="succeeded",
        outputs={"http_response": {"status_code": 200}},
        worker_state=WorkflowRuntimeWorkerState(
            observed_state="running",
            process_id=321,
            health_summary={"worker_state": "running"},
        ),
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=_FakeWorkerManager(worker_result=worker_result),
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    workflow_run = service.invoke_workflow_app_runtime(
        runtime.workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings={"request_text": {"value": "hello"}},
            execution_metadata={"workflow_run_record_mode": "none"},
        ),
        created_by="workflow-user",
    )

    assert workflow_run.state == "succeeded"
    with pytest.raises(ResourceNotFoundError):
        service.get_workflow_run(workflow_run.workflow_run_id)


@pytest.mark.parametrize(
    ("invoke_error", "expected_state", "expected_error_detail"),
    (
        (
            ServiceConfigurationError(
                "workflow runtime worker 当前未运行",
                details={"reason": "worker-unavailable"},
            ),
            "failed",
            ("error_code", "service_configuration_error"),
        ),
        (
            ServiceConfigurationError(
                "worker 返回的运行配置无效",
                details={"reason": "worker-service-error"},
            ),
            "failed",
            ("reason", "worker-service-error"),
        ),
        (
            RuntimeError("unexpected worker failure"),
            "failed",
            ("error_type", "RuntimeError"),
        ),
        (
            OperationCancelledError(
                "workflow run 已取消",
                details={"reason": "cancelled-before-dispatch"},
            ),
            "cancelled",
            ("error_code", "operation_cancelled"),
        ),
    ),
    ids=("worker-unavailable", "worker-service-error", "unexpected-error", "cancelled"),
)
def test_sync_invoke_manager_error_terminalizes_persisted_dispatch_record(
    tmp_path: Path,
    invoke_error: Exception,
    expected_state: str,
    expected_error_detail: tuple[str, str],
) -> None:
    """验证同步 manager 异常不会遗留永久 dispatching Run。"""

    worker_manager = _FakeWorkerManager(
        worker_result=WorkflowRuntimeWorkerRunResult(state="succeeded"),
        invoke_error=invoke_error,
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    version_service = service._build_workflow_app_version_service()
    draft = version_service.get_draft_snapshot(
        project_id="project-1",
        application_id="image-decode-preview-app",
    )
    published_version = version_service.publish_version(
        project_id="project-1",
        application_id="image-decode-preview-app",
        expected_draft_fingerprint=draft.draft_fingerprint,
        release_notes="同步异常终态测试",
        display_version=None,
        created_by="workflow-user",
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            workflow_app_version_id=published_version.workflow_app_version_id,
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    with pytest.raises(type(invoke_error), match=str(invoke_error)):
        service.invoke_workflow_app_runtime(
            runtime.workflow_runtime_id,
            WorkflowRuntimeInvokeRequest(
                input_bindings={"request_text": {"value": "hello"}},
                execution_metadata={
                    "workflow_run_record_mode": "full",
                    "retain_trace_enabled": True,
                    "trace_level": "status",
                },
            ),
            created_by="workflow-user",
        )

    with service._open_unit_of_work() as unit_of_work:
        runs = unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
            runtime.workflow_runtime_id
        )
        active_runs = unit_of_work.workflow_runtime.list_active_workflow_runs_for_runtime(
            runtime.workflow_runtime_id
        )
    assert len(runs) == 1
    persisted_run = service.get_workflow_run(runs[0].workflow_run_id)
    assert persisted_run.state == expected_state
    assert persisted_run.finished_at is not None
    assert persisted_run.error_message == str(invoke_error)
    detail_key, detail_value = expected_error_detail
    assert persisted_run.metadata["error_details"][detail_key] == detail_value
    assert active_runs == ()
    events = service.get_workflow_run_events(persisted_run.workflow_run_id)
    assert events[-1].event_type == f"run.{expected_state}"
    assert worker_manager.cleanup_call_count == 1

    # manager 调用错误只终结 Run，不允许旧 epoch 直接回写 Runtime。
    latest_runtime = service.get_workflow_app_runtime(runtime.workflow_runtime_id)
    assert latest_runtime.worker_instance_id == running_runtime.worker_instance_id
    stopped_runtime = service.stop_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    selected_runtime = service.select_workflow_app_runtime_version(
        runtime.workflow_runtime_id,
        WorkflowAppRuntimeSelectVersionRequest(
            workflow_app_version_id=published_version.workflow_app_version_id,
            expected_generation=stopped_runtime.revision_generation,
        ),
        updated_by="workflow-user",
    )
    assert selected_runtime.revision_generation == stopped_runtime.revision_generation + 1
    service.delete_workflow_app_runtime(
        runtime.workflow_runtime_id,
        deleted_by="workflow-user",
    )
    with pytest.raises(ResourceNotFoundError):
        service.get_workflow_app_runtime(runtime.workflow_runtime_id)


def test_sync_invoke_none_mode_manager_error_does_not_create_run(tmp_path: Path) -> None:
    """验证 none 记录模式遇到 manager 异常也不会额外创建 WorkflowRun。"""

    invoke_error = ServiceConfigurationError("workflow runtime worker 当前未运行")
    worker_manager = _FakeWorkerManager(
        worker_result=WorkflowRuntimeWorkerRunResult(state="succeeded"),
        invoke_error=invoke_error,
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    with pytest.raises(ServiceConfigurationError, match="当前未运行"):
        service.invoke_workflow_app_runtime(
            runtime.workflow_runtime_id,
            WorkflowRuntimeInvokeRequest(
                input_bindings={},
                execution_metadata={"workflow_run_record_mode": "none"},
            ),
            created_by="workflow-user",
        )

    with service._open_unit_of_work() as unit_of_work:
        runs = unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
            runtime.workflow_runtime_id
        )
    assert runs == ()


def test_async_run_admission_holds_lifecycle_guard_until_submit_registered(
    tmp_path: Path,
) -> None:
    """验证异步 queued 持久化与 submit 登记期间删除必须等待并最终返回 409。"""

    worker_manager = _FakeWorkerManager(
        worker_result=WorkflowRuntimeWorkerRunResult(state="succeeded"),
    )
    worker_manager.submit_entered_event = Event()
    worker_manager.submit_release_event = Event()
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
        ),
        created_by="workflow-user",
    )
    service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    create_result: dict[str, object] = {}
    delete_result: dict[str, object] = {}
    delete_started = Event()
    delete_finished = Event()

    def create_run() -> None:
        try:
            create_result["run"] = service.create_workflow_run(
                runtime.workflow_runtime_id,
                WorkflowRuntimeInvokeRequest(input_bindings={}),
                created_by="workflow-user",
            )
        except Exception as error:  # noqa: BLE001 - 断言线程异常
            create_result["error"] = error

    def delete_runtime() -> None:
        delete_started.set()
        try:
            service.delete_workflow_app_runtime(
                runtime.workflow_runtime_id,
                deleted_by="workflow-user",
            )
        except Exception as error:  # noqa: BLE001 - 断言线程异常
            delete_result["error"] = error
        finally:
            delete_finished.set()

    create_thread = Thread(target=create_run, daemon=True)
    create_thread.start()
    assert worker_manager.submit_entered_event.wait(timeout=2)
    delete_thread = Thread(target=delete_runtime, daemon=True)
    delete_thread.start()
    assert delete_started.wait(timeout=2)
    assert not delete_finished.wait(timeout=0.2)

    worker_manager.submit_release_event.set()
    create_thread.join(timeout=2)
    delete_thread.join(timeout=2)
    assert not create_thread.is_alive()
    assert not delete_thread.is_alive()
    assert "error" not in create_result
    workflow_run = create_result["run"]
    assert isinstance(workflow_run, WorkflowRun)
    assert workflow_run.state == "queued"
    delete_error = delete_result.get("error")
    assert isinstance(delete_error, ResourceConflictError)
    assert delete_error.status_code == 409
    assert delete_error.details["workflow_run_ids"] == [
        workflow_run.workflow_run_id
    ]


def test_sync_dispatch_admission_holds_guard_and_blocks_runtime_delete(
    tmp_path: Path,
) -> None:
    """验证同步 dispatching 在释放生命周期锁前可见并阻断删除。"""

    worker_manager = _FakeWorkerManager(
        worker_result=WorkflowRuntimeWorkerRunResult(
            state="succeeded",
            worker_state=WorkflowRuntimeWorkerState(observed_state="running"),
        ),
    )
    worker_manager.invoke_entered_event = Event()
    worker_manager.invoke_release_event = Event()
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
        ),
        created_by="workflow-user",
    )
    service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    dispatch_persisted = Event()
    admission_release = Event()
    original_append_run_event = service._append_workflow_run_event

    def append_run_event(
        workflow_run: WorkflowRun,
        *,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> object:
        if event_type == "run.dispatching":
            dispatch_persisted.set()
            assert admission_release.wait(timeout=2)
        return original_append_run_event(
            workflow_run,
            event_type=event_type,
            message=message,
            payload=payload,
        )

    service._append_workflow_run_event = append_run_event  # type: ignore[method-assign]
    invoke_result: dict[str, object] = {}
    delete_result: dict[str, object] = {}
    delete_started = Event()
    delete_finished = Event()

    def invoke_runtime() -> None:
        try:
            invoke_result["run"] = service.invoke_workflow_app_runtime(
                runtime.workflow_runtime_id,
                WorkflowRuntimeInvokeRequest(
                    input_bindings={},
                    execution_metadata={"workflow_run_record_mode": "full"},
                ),
                created_by="workflow-user",
            )
        except Exception as error:  # noqa: BLE001 - 断言线程异常
            invoke_result["error"] = error

    def delete_runtime() -> None:
        delete_started.set()
        try:
            service.delete_workflow_app_runtime(
                runtime.workflow_runtime_id,
                deleted_by="workflow-user",
            )
        except Exception as error:  # noqa: BLE001 - 断言线程异常
            delete_result["error"] = error
        finally:
            delete_finished.set()

    invoke_thread = Thread(target=invoke_runtime, daemon=True)
    invoke_thread.start()
    assert dispatch_persisted.wait(timeout=2)
    delete_thread = Thread(target=delete_runtime, daemon=True)
    delete_thread.start()
    assert delete_started.wait(timeout=2)
    assert not delete_finished.wait(timeout=0.2)

    admission_release.set()
    assert worker_manager.invoke_entered_event.wait(timeout=2)
    assert delete_finished.wait(timeout=2)
    delete_error = delete_result.get("error")
    assert isinstance(delete_error, ResourceConflictError)
    assert delete_error.status_code == 409
    worker_manager.invoke_release_event.set()
    invoke_thread.join(timeout=2)
    delete_thread.join(timeout=2)
    assert not invoke_thread.is_alive()
    assert not delete_thread.is_alive()
    assert "error" not in invoke_result
    workflow_run = invoke_result["run"]
    assert isinstance(workflow_run, WorkflowRun)
    assert workflow_run.state == "succeeded"


@pytest.mark.parametrize("record_mode", ("minimal", "none"))
def test_lightweight_sync_admission_blocks_delete_without_database_dispatch_write(
    tmp_path: Path,
    record_mode: str,
) -> None:
    """验证 minimal/none 以纯内存占用关闭删除窗口且不预写 dispatching。"""

    worker_manager = _FakeWorkerManager(
        worker_result=WorkflowRuntimeWorkerRunResult(
            state="succeeded",
            worker_state=WorkflowRuntimeWorkerState(observed_state="running"),
        ),
    )
    worker_manager.reserve_entered_event = Event()
    worker_manager.reserve_release_event = Event()
    worker_manager.invoke_entered_event = Event()
    worker_manager.invoke_release_event = Event()
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
        ),
        created_by="workflow-user",
    )
    service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    invoke_result: dict[str, object] = {}
    delete_result: dict[str, object] = {}
    delete_started = Event()
    delete_finished = Event()

    def invoke_runtime() -> None:
        try:
            invoke_result["run"] = service.invoke_workflow_app_runtime(
                runtime.workflow_runtime_id,
                WorkflowRuntimeInvokeRequest(
                    input_bindings={},
                    execution_metadata={"workflow_run_record_mode": record_mode},
                ),
                created_by="workflow-user",
            )
        except Exception as error:  # noqa: BLE001 - 断言线程异常
            invoke_result["error"] = error

    def delete_runtime() -> None:
        delete_started.set()
        try:
            service.delete_workflow_app_runtime(
                runtime.workflow_runtime_id,
                deleted_by="workflow-user",
            )
        except Exception as error:  # noqa: BLE001 - 断言线程异常
            delete_result["error"] = error
        finally:
            delete_finished.set()

    invoke_thread = Thread(target=invoke_runtime, daemon=True)
    invoke_thread.start()
    assert worker_manager.reserve_entered_event.wait(timeout=2)
    delete_thread = Thread(target=delete_runtime, daemon=True)
    delete_thread.start()
    assert delete_started.wait(timeout=2)
    assert not delete_finished.wait(timeout=0.2)

    worker_manager.reserve_release_event.set()
    assert worker_manager.invoke_entered_event.wait(timeout=2)
    assert delete_finished.wait(timeout=2)
    delete_error = delete_result.get("error")
    assert isinstance(delete_error, ResourceConflictError)
    assert delete_error.status_code == 409
    blocked_run_ids = delete_error.details["workflow_run_ids"]
    assert len(blocked_run_ids) == 1
    assert delete_error.details["workflow_run_states"] == {
        blocked_run_ids[0]: "sync-admission"
    }
    with service._open_unit_of_work() as unit_of_work:
        runs_during_invoke = (
            unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
                runtime.workflow_runtime_id
            )
        )
    assert runs_during_invoke == ()

    worker_manager.invoke_release_event.set()
    invoke_thread.join(timeout=2)
    delete_thread.join(timeout=2)
    assert not invoke_thread.is_alive()
    assert not delete_thread.is_alive()
    assert "error" not in invoke_result
    workflow_run = invoke_result["run"]
    assert isinstance(workflow_run, WorkflowRun)
    assert workflow_run.state == "succeeded"
    assert worker_manager.list_sync_admission_run_ids(
        runtime.workflow_runtime_id
    ) == ()
    with service._open_unit_of_work() as unit_of_work:
        persisted_runs = unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
            runtime.workflow_runtime_id
        )
    assert len(persisted_runs) == (1 if record_mode == "minimal" else 0)


@pytest.mark.parametrize("record_mode", ("minimal", "none"))
@pytest.mark.parametrize(
    "invoke_error",
    (
        ServiceConfigurationError("worker unavailable"),
        RuntimeError("unexpected worker error"),
    ),
    ids=("service-error", "unexpected-error"),
)
def test_lightweight_sync_admission_is_released_after_invoke_error(
    tmp_path: Path,
    record_mode: str,
    invoke_error: Exception,
) -> None:
    """验证 minimal/none 的同步内存占用在所有异常路径都不会泄漏。"""

    worker_manager = _FakeWorkerManager(
        worker_result=WorkflowRuntimeWorkerRunResult(state="succeeded"),
        invoke_error=invoke_error,
    )
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
        ),
        created_by="workflow-user",
    )
    service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )

    with pytest.raises(type(invoke_error), match=str(invoke_error)):
        service.invoke_workflow_app_runtime(
            runtime.workflow_runtime_id,
            WorkflowRuntimeInvokeRequest(
                input_bindings={},
                execution_metadata={"workflow_run_record_mode": record_mode},
            ),
            created_by="workflow-user",
        )

    assert worker_manager.list_sync_admission_run_ids(
        runtime.workflow_runtime_id
    ) == ()
    with service._open_unit_of_work() as unit_of_work:
        runs = unit_of_work.workflow_runtime.list_workflow_runs_by_runtime(
            runtime.workflow_runtime_id
        )
    assert runs == ()
    service.delete_workflow_app_runtime(
        runtime.workflow_runtime_id,
        deleted_by="workflow-user",
    )
    with pytest.raises(ResourceNotFoundError):
        service.get_workflow_app_runtime(runtime.workflow_runtime_id)


def test_runtime_payload_sanitizer_bounds_large_database_values() -> None:
    """验证运行时持久化 payload 会裁剪超大数据库字段。"""

    sanitized = sanitize_runtime_mapping(
        {
            "text": "x" * (MAX_PERSISTED_STRING_CHARS + 1),
            "items": list(range(MAX_PERSISTED_COLLECTION_ITEMS + 1)),
            "image_base64": "a" * (MAX_PERSISTED_STRING_CHARS + 1),
        }
    )

    assert sanitized["text"] == {
        "text_redacted": True,
        "char_length": MAX_PERSISTED_STRING_CHARS + 1,
    }
    assert sanitized["items"]["sequence_truncated"] is True
    assert sanitized["items"]["item_count"] == MAX_PERSISTED_COLLECTION_ITEMS + 1
    assert len(sanitized["items"]["items"]) == MAX_PERSISTED_COLLECTION_ITEMS
    assert sanitized["image_base64_redacted"] is True
    assert sanitized["image_base64_char_length"] == MAX_PERSISTED_STRING_CHARS + 1


def test_invoke_workflow_run_registers_input_buffer_cleanup_and_skips_trace_file(
    tmp_path: Path,
) -> None:
    """验证正式调用会释放输入 BufferRef 且可跳过 workflow-run 事件文件。

    参数：
    - tmp_path：pytest 提供的临时目录。
    """

    worker_result = WorkflowRuntimeWorkerRunResult(
        state="succeeded",
        worker_state=WorkflowRuntimeWorkerState(
            observed_state="running",
            process_id=321,
            health_summary={"worker_state": "running"},
        ),
    )
    worker_manager = _FakeWorkerManager(worker_result=worker_result)
    service, workflow_service, _ = _build_runtime_service(
        tmp_path,
        worker_manager=worker_manager,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_image_decode_preview_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_image_decode_preview_application(),
    )
    runtime = service.create_workflow_app_runtime(
        WorkflowAppRuntimeCreateRequest(
            project_id="project-1",
            application_id="image-decode-preview-app",
            request_timeout_seconds=30,
        ),
        created_by="workflow-user",
    )
    running_runtime = service.start_workflow_app_runtime(
        runtime.workflow_runtime_id,
        updated_by="workflow-user",
    )
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: (
        running_runtime
    )  # type: ignore[method-assign]

    workflow_run = service.invoke_workflow_app_runtime(
        runtime.workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings={
                "request_image_base64": {
                    "transport_kind": "buffer",
                    "buffer_ref": _build_buffer_ref_payload(lease_id="lease-input-1"),
                }
            },
            execution_metadata={
                "marker": "no-trace-buffer-input",
                "trace_level": "none",
                "retain_trace_enabled": False,
            },
        ),
        created_by="workflow-user",
    )

    worker_execution_metadata = worker_manager.last_invoke_kwargs["execution_metadata"]
    cleanup_items = worker_execution_metadata[WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY]
    persisted_run = service.get_workflow_run(workflow_run.workflow_run_id)
    assert workflow_run.state == "succeeded"
    assert cleanup_items == [
        {
            "resource_kind": WORKFLOW_EXECUTION_CLEANUP_KIND_LOCAL_BUFFER_LEASE,
            "resource_id": "lease-input-1",
            "metadata": {},
        }
    ]
    assert WORKFLOW_EXECUTION_CLEANUP_ITEMS_KEY not in persisted_run.metadata
    assert service.get_workflow_run_events(workflow_run.workflow_run_id) == ()
    assert not service.dataset_storage.resolve(
        f"workflows/runtime/{workflow_run.workflow_run_id}"
    ).exists()


def _build_runtime_service(
    tmp_path: Path,
    *,
    worker_manager: object | None = None,
) -> tuple[WorkflowRuntimeService, LocalWorkflowJsonService, NodeCatalogRegistry]:
    """构造 runtime service 测试夹具。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-sanitization.db",
    )
    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    settings = BackendServiceSettings(
        database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
        dataset_storage=BackendServiceDatasetStorageConfig(
            root_dir=str(dataset_storage.root_dir)
        ),
        queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
        custom_nodes=BackendServiceCustomNodesConfig(
            root_dir=str(custom_nodes_root_dir)
        ),
    )
    preview_run_manager = WorkflowPreviewRunManager(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
        load_custom_node_handlers=True,
    )
    runtime_registry_loader.refresh()
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    service = WorkflowRuntimeService(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
        preview_run_manager=preview_run_manager,
        worker_manager=worker_manager
        if worker_manager is not None
        else SimpleNamespace(),
        workflow_node_runtime_registry=runtime_registry_loader.get_runtime_registry(),
        workflow_service_node_runtime_context=runtime_context,
    )
    if isinstance(worker_manager, _FakeWorkerManager):
        worker_manager.dataset_storage = dataset_storage
        worker_manager.node_catalog_registry = node_catalog_registry
    return service, workflow_service, node_catalog_registry


def _build_image_decode_preview_template() -> WorkflowGraphTemplate:
    """构造 image-base64 decode 到 preview 的最小模板。"""

    return WorkflowGraphTemplate(
        template_id="image-decode-preview-template",
        template_version="1.0.0",
        display_name="Image Decode Preview Template",
        nodes=(
            WorkflowGraphNode(
                node_id="decode", node_type_id="core.io.image-base64-decode"
            ),
            WorkflowGraphNode(node_id="preview", node_type_id="core.io.image-preview"),
            WorkflowGraphNode(
                node_id="response", node_type_id="core.output.http-response"
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-decode-preview",
                source_node_id="decode",
                source_port="image",
                target_node_id="preview",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-preview-response",
                source_node_id="preview",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-base64.v1",
                target_node_id="decode",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="http_response",
                display_name="HTTP Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )


def _build_image_decode_save_preview_template() -> WorkflowGraphTemplate:
    """构造 image-base64 decode、save、storage-ref preview 的模板。"""

    return WorkflowGraphTemplate(
        template_id="image-decode-save-preview-template",
        template_version="1.0.0",
        display_name="Image Decode Save Preview Template",
        nodes=(
            WorkflowGraphNode(
                node_id="decode", node_type_id="core.io.image-base64-decode"
            ),
            WorkflowGraphNode(
                node_id="save",
                node_type_id="core.io.image-save",
                parameters={
                    "save_location": "projects/project-1/results/formal-preview-source.png"
                },
            ),
            WorkflowGraphNode(
                node_id="preview",
                node_type_id="core.io.image-preview",
                parameters={"response_transport_mode": "storage-ref"},
            ),
            WorkflowGraphNode(
                node_id="response", node_type_id="core.output.http-response"
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-decode-save",
                source_node_id="decode",
                source_port="image",
                target_node_id="save",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-save-preview",
                source_node_id="save",
                source_port="image",
                target_node_id="preview",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-preview-response",
                source_node_id="preview",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image_base64",
                display_name="Request Image",
                payload_type_id="image-base64.v1",
                target_node_id="decode",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="http_response",
                display_name="HTTP Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )


def _build_image_decode_preview_application() -> FlowApplication:
    """构造 image-base64 decode 到 preview 的最小流程应用。"""

    return FlowApplication(
        application_id="image-decode-preview-app",
        display_name="Image Decode Preview App",
        template_ref=FlowTemplateReference(
            template_id="image-decode-preview-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image_base64",
                direction="input",
                template_port_id="request_image_base64",
                binding_kind="api-request",
                config={"route": "/execute/image-preview", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="http_response",
                direction="output",
                template_port_id="http_response",
                binding_kind="http-response",
                config={"status_code": 200},
            ),
        ),
    )


def _build_image_decode_save_preview_application() -> FlowApplication:
    """构造 image-base64 decode、save、storage-ref preview 的流程应用。"""

    return FlowApplication(
        application_id="image-decode-save-preview-app",
        display_name="Image Decode Save Preview App",
        template_ref=FlowTemplateReference(
            template_id="image-decode-save-preview-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_image_base64",
                direction="input",
                template_port_id="request_image_base64",
                binding_kind="api-request",
                config={"route": "/execute/image-preview", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="http_response",
                direction="output",
                template_port_id="http_response",
                binding_kind="http-response",
                config={"status_code": 200},
            ),
        ),
    )


class _FakeWorkerManager:
    """返回固定同步执行结果的假 worker manager。

    字段：
    - worker_result：预置的同步执行结果。
    - last_invoke_kwargs：最近一次 invoke_runtime 调用参数。
    """

    def __init__(
        self,
        *,
        worker_result: WorkflowRuntimeWorkerRunResult,
        invoke_error: Exception | None = None,
    ) -> None:
        """初始化固定结果的假 worker manager。

        参数：
        - worker_result：预置的同步执行结果。
        """

        self.worker_result = worker_result
        self.invoke_error = invoke_error
        self.last_invoke_kwargs: dict[str, object] = {}
        self.cleanup_call_count = 0
        self.dataset_storage = None
        self.node_catalog_registry = None
        self.runtime_state = WorkflowRuntimeWorkerState(observed_state="stopped")
        self.lifecycle_lock = RLock()
        self.submit_entered_event: Event | None = None
        self.submit_release_event: Event | None = None
        self.invoke_entered_event: Event | None = None
        self.invoke_release_event: Event | None = None
        self.reserve_entered_event: Event | None = None
        self.reserve_release_event: Event | None = None
        self.manager_lock = RLock()
        self.sync_admissions: dict[str, set[str]] = {}

    @contextmanager
    def runtime_lifecycle_guard(self, workflow_runtime_id: str) -> Iterator[None]:
        """模拟生产 manager 的 Runtime 生命周期锁。"""

        del workflow_runtime_id
        with self.lifecycle_lock:
            yield

    def reserve_sync_admission(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> None:
        """模拟 manager 锁保护的同步调用占用登记。"""

        with self.manager_lock:
            self.sync_admissions.setdefault(workflow_runtime_id, set()).add(
                workflow_run_id
            )
        if self.reserve_entered_event is not None:
            self.reserve_entered_event.set()
        if self.reserve_release_event is not None:
            if not self.reserve_release_event.wait(timeout=2):
                raise AssertionError("测试未释放同步 admission 登记")

    def release_sync_admission(
        self,
        workflow_runtime_id: str,
        workflow_run_id: str,
    ) -> None:
        """模拟同步调用占用的幂等释放。"""

        with self.manager_lock:
            workflow_run_ids = self.sync_admissions.get(workflow_runtime_id)
            if workflow_run_ids is None:
                return
            workflow_run_ids.discard(workflow_run_id)
            if not workflow_run_ids:
                self.sync_admissions.pop(workflow_runtime_id, None)

    def list_sync_admission_run_ids(
        self,
        workflow_runtime_id: str,
    ) -> tuple[str, ...]:
        """读取当前同步调用占用。"""

        with self.manager_lock:
            return tuple(sorted(self.sync_admissions.get(workflow_runtime_id, ())))

    def start_runtime(
        self,
        workflow_app_runtime,
        **identity: object,
    ) -> WorkflowRuntimeWorkerState:
        """按真实不可变快照计算指纹并返回 running 状态。"""

        if self.dataset_storage is None or self.node_catalog_registry is None:
            raise AssertionError("测试 worker manager 尚未绑定 runtime 依赖")
        snapshot_fingerprint = compute_workflow_app_content_fingerprint(
            application=FlowApplication.model_validate(
                self.dataset_storage.read_json(
                    workflow_app_runtime.application_snapshot_object_key
                )
            ),
            template=WorkflowGraphTemplate.model_validate(
                self.dataset_storage.read_json(
                    workflow_app_runtime.template_snapshot_object_key
                )
            ),
            node_catalog_registry=self.node_catalog_registry,
        )
        self.runtime_state = WorkflowRuntimeWorkerState(
            observed_state="running",
            instance_id="fake-worker-epoch-1",
            process_id=321,
            loaded_snapshot_fingerprint=snapshot_fingerprint,
            health_summary={
                "worker_state": "running",
                "identity": dict(identity),
            },
        )
        return self.runtime_state

    def get_runtime_health(self, workflow_runtime_id: str) -> WorkflowRuntimeWorkerState:
        """返回假 worker 当前健康状态。"""

        del workflow_runtime_id
        return self.runtime_state

    def stop_runtime(self, workflow_runtime_id: str) -> WorkflowRuntimeWorkerState:
        """把假 worker 标记为 stopped。"""

        del workflow_runtime_id
        self.runtime_state = WorkflowRuntimeWorkerState(observed_state="stopped")
        return self.runtime_state

    def invoke_runtime(self, **kwargs: object) -> WorkflowRuntimeWorkerRunResult:
        """记录调用参数并返回预置的同步执行结果。

        参数：
        - kwargs：WorkflowRuntimeService 传入 worker manager 的调用参数。

        返回：
        - WorkflowRuntimeWorkerRunResult：预置同步执行结果。
        """

        self.last_invoke_kwargs = dict(kwargs)
        if self.invoke_entered_event is not None:
            self.invoke_entered_event.set()
        if self.invoke_release_event is not None:
            if not self.invoke_release_event.wait(timeout=2):
                raise AssertionError("测试未释放同步 invoke")
        if self.invoke_error is not None:
            raise self.invoke_error
        return replace(
            self.worker_result,
            worker_state=replace(
                self.worker_result.worker_state,
                instance_id=self.runtime_state.instance_id,
            ),
        )

    def is_runtime_available(self, workflow_runtime_id: str) -> bool:
        """返回假 worker 是否处于 running。"""

        del workflow_runtime_id
        return self.runtime_state.observed_state == "running"

    def submit_async_run(self, **kwargs: object) -> None:
        """模拟异步句柄登记，并可在测试中暂停登记窗口。"""

        self.last_invoke_kwargs = dict(kwargs)
        if self.submit_entered_event is not None:
            self.submit_entered_event.set()
        if self.submit_release_event is not None:
            if not self.submit_release_event.wait(timeout=2):
                raise AssertionError("测试未释放异步 submit")

    def cleanup_parent_local_buffer_leases(
        self,
        execution_metadata: dict[str, object],
    ) -> int:
        """记录异常路径触发的父进程输入 lease 清理。"""

        del execution_metadata
        self.cleanup_call_count += 1
        return 0


def _build_buffer_ref_payload(*, lease_id: str = "lease-1") -> dict[str, object]:
    """构造测试用 BufferRef payload。

    参数：
    - lease_id：测试使用的 lease id。

    返回：
    - dict[str, object]：JSON 可序列化的 BufferRef payload。
    """

    return BufferRef(
        buffer_id="buffer-1",
        lease_id=lease_id,
        path="data/buffers/pool-001.dat",
        offset=0,
        size=10,
        media_type="image/png",
        broker_epoch="epoch-1",
        generation=1,
    ).model_dump(mode="json")
