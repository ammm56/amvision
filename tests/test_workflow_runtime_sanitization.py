"""workflow runtime 输入输出脱敏测试。"""

from __future__ import annotations

import base64
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

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
from backend.service.application.workflows.runtime_service import (
    WorkflowAppRuntimeCreateRequest,
    WorkflowPreviewRunCreateRequest,
    WorkflowRuntimeInvokeRequest,
    WorkflowRuntimeService,
)
from backend.service.application.workflows.runtime_worker import (
    WorkflowRuntimeWorkerRunResult,
    WorkflowRuntimeWorkerState,
)
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from backend.service.settings import (
    BackendServiceCustomNodesConfig,
    BackendServiceDatabaseConfig,
    BackendServiceDatasetStorageConfig,
    BackendServiceQueueConfig,
    BackendServiceSettings,
    BackendServiceTaskManagerConfig,
)
from tests.api_test_support import build_valid_test_png_bytes, create_test_runtime


def test_preview_run_sanitizes_inline_base64_outputs_and_node_records(tmp_path: Path) -> None:
    """验证 preview run 会对 inline-base64 输出和 node_records 做脱敏。"""

    service, _, _ = _build_runtime_service(tmp_path)
    image_base64 = base64.b64encode(build_valid_test_png_bytes()).decode("ascii")

    preview_run = service.create_preview_run(
        WorkflowPreviewRunCreateRequest(
            project_id="project-1",
            application=_build_image_decode_preview_application(),
            template=_build_image_decode_preview_template(),
            input_bindings={"request_image": {"image_base64": image_base64}},
        ),
        created_by="workflow-user",
    )

    assert preview_run.state == "succeeded"
    preview_image = preview_run.outputs["http_response"]["body"]["image"]
    assert preview_image["transport_kind"] == "inline-base64"
    assert preview_image["image_base64_redacted"] is True
    assert "image_base64" not in preview_image
    assert preview_run.template_outputs["http_response"]["body"]["image"]["image_base64_redacted"] is True
    assert preview_run.node_records[0]["inputs"]["payload"]["image_base64_redacted"] is True
    assert preview_run.node_records[0]["outputs"]["image"]["image_handle_redacted"] is True
    assert preview_run.node_records[1]["inputs"]["image"]["image_handle_redacted"] is True
    assert preview_run.node_records[1]["outputs"]["body"]["image"]["image_base64_redacted"] is True


def test_invoke_workflow_run_sanitizes_input_payload_outputs_and_node_records(tmp_path: Path) -> None:
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
                "inputs": {"payload": {"image_base64": "ZmFrZS1pbnB1dA==", "media_type": "image/png"}},
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
    running_runtime = replace(runtime, observed_state="running")
    service.get_workflow_app_runtime_health = lambda workflow_runtime_id: running_runtime  # type: ignore[method-assign]

    workflow_run = service.invoke_workflow_app_runtime(
        runtime.workflow_runtime_id,
        WorkflowRuntimeInvokeRequest(
            input_bindings={
                "request_image": {
                    "image_base64": "ZmFrZS1yZXF1ZXN0",
                    "media_type": "image/png",
                }
            }
        ),
        created_by="workflow-user",
    )

    assert workflow_run.state == "succeeded"
    assert workflow_run.input_payload["request_image"]["image_base64_redacted"] is True
    assert "image_base64" not in workflow_run.input_payload["request_image"]
    assert workflow_run.outputs["http_response"]["body"]["image"]["image_base64_redacted"] is True
    assert workflow_run.template_outputs["http_response"]["body"]["image"]["image_base64_redacted"] is True
    assert workflow_run.node_records[0]["inputs"]["payload"]["image_base64_redacted"] is True
    assert workflow_run.node_records[0]["outputs"]["image"]["image_handle_redacted"] is True

    persisted_run = service.get_workflow_run(workflow_run.workflow_run_id)
    assert persisted_run.input_payload == workflow_run.input_payload
    assert persisted_run.outputs == workflow_run.outputs


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
    service = WorkflowRuntimeService(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
        worker_manager=worker_manager if worker_manager is not None else SimpleNamespace(),
    )
    return service, workflow_service, node_catalog_registry


def _build_image_decode_preview_template() -> WorkflowGraphTemplate:
    """构造 image-base64 decode 到 preview 的最小模板。"""

    return WorkflowGraphTemplate(
        template_id="image-decode-preview-template",
        template_version="1.0.0",
        display_name="Image Decode Preview Template",
        nodes=(
            WorkflowGraphNode(node_id="decode", node_type_id="core.io.image-base64-decode"),
            WorkflowGraphNode(node_id="preview", node_type_id="core.io.image-preview"),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
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
                input_id="request_image",
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
                binding_id="request_image",
                direction="input",
                template_port_id="request_image",
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
    """返回固定同步执行结果的假 worker manager。"""

    def __init__(self, *, worker_result: WorkflowRuntimeWorkerRunResult) -> None:
        """初始化固定结果的假 worker manager。

        参数：
        - worker_result：预置的同步执行结果。
        """

        self.worker_result = worker_result

    def invoke_runtime(self, **_: object) -> WorkflowRuntimeWorkerRunResult:
        """返回预置的同步执行结果。"""

        return self.worker_result