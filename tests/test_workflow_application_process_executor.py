"""workflow application 隔离进程执行测试。"""

from __future__ import annotations

import json
import multiprocessing
import os
from pathlib import Path

from fastapi.testclient import TestClient

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.api.app import create_app
from backend.service.application.workflows.process_executor import (
    WorkflowApplicationExecutionRequest,
    WorkflowApplicationProcessExecutor,
    WorkflowApplicationRuntimeExecutor,
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
from tests.api_test_support import build_test_headers, create_test_runtime


def test_workflow_application_process_executor_runs_application_in_child_process(
    tmp_path: Path,
) -> None:
    """验证 workflow application 会在独立子进程中执行并按 binding 返回结果。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-process-executor.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
    executor = WorkflowApplicationProcessExecutor(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        )
    )

    try:
        execution_result = executor.execute(
            WorkflowApplicationExecutionRequest(
                project_id="project-1",
                application_id="process-echo-app",
                input_bindings={"request_text": {"value": "hello workflow app"}},
                execution_metadata={"marker": "isolated-run"},
            )
        )
    finally:
        session_factory.engine.dispose()

    response_payload = execution_result.outputs["http_response"]
    assert execution_result.project_id == "project-1"
    assert execution_result.application_id == "process-echo-app"
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["message"] == "hello workflow app"
    assert response_payload["body"]["marker"] == "isolated-run"
    assert response_payload["body"]["pid"] != os.getpid()
    assert response_payload["body"]["is_daemon"] is False
    assert isinstance(response_payload["body"]["workflow_run_id"], str)
    assert execution_result.node_records[0].node_type_id == "custom.test.process-echo"


def test_workflow_application_runtime_executor_runs_application_in_current_process(
    tmp_path: Path,
) -> None:
    """验证当前运行时执行器会复用 backend-service 主进程运行时。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-runtime-executor.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )

    try:
        with TestClient(application):
            execution_result = WorkflowApplicationRuntimeExecutor(
                dataset_storage=dataset_storage,
                node_catalog_registry=node_catalog_registry,
                runtime_registry=application.state.workflow_node_runtime_registry,
                runtime_context=application.state.workflow_service_node_runtime_context,
            ).execute(
                WorkflowApplicationExecutionRequest(
                    project_id="project-1",
                    application_id="process-echo-app",
                    input_bindings={"request_text": {"value": "hello workflow runtime"}},
                    execution_metadata={"marker": "runtime-run"},
                )
            )
    finally:
        session_factory.engine.dispose()

    response_payload = execution_result.outputs["http_response"]
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["message"] == "hello workflow runtime"
    assert response_payload["body"]["marker"] == "runtime-run"
    assert response_payload["body"]["pid"] == os.getpid()
    assert response_payload["body"]["is_daemon"] is False
    assert isinstance(response_payload["body"]["workflow_run_id"], str)


def test_workflow_execute_api_runs_saved_application_in_current_process(
    tmp_path: Path,
) -> None:
    """验证 workflows execute API 会复用 backend-service 当前运行时执行已保存 application。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-process-execute-api.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_echo_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_echo_application(),
    )
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    client = TestClient(application)

    try:
        with client:
            response = client.post(
                "/api/v1/workflows/projects/project-1/applications/process-echo-app/execute",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello execute api"}},
                    "execution_metadata": {"marker": "api-execute"},
                },
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 200
    body = response.json()["outputs"]["http_response"]["body"]
    assert body["message"] == "hello execute api"
    assert body["marker"] == "api-execute"
    assert body["pid"] == os.getpid()
    assert body["is_daemon"] is False
    assert isinstance(body["workflow_run_id"], str)


def test_workflow_execute_api_reports_failed_node_details(
    tmp_path: Path,
) -> None:
    """验证 execute API 在节点失败时会返回失败节点定位信息。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name="workflow-process-execute-api-failure.db",
    )
    custom_nodes_root_dir = _create_process_test_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    workflow_service.save_template(
        project_id="project-1",
        template=_build_process_fail_template(),
    )
    workflow_service.save_application(
        project_id="project-1",
        application=_build_process_fail_application(),
    )
    application = create_app(
        settings=BackendServiceSettings(
            database=BackendServiceDatabaseConfig(url=session_factory.settings.url),
            dataset_storage=BackendServiceDatasetStorageConfig(root_dir=str(dataset_storage.root_dir)),
            queue=BackendServiceQueueConfig(root_dir=str(queue_backend.root_dir)),
            custom_nodes=BackendServiceCustomNodesConfig(root_dir=str(custom_nodes_root_dir)),
            task_manager=BackendServiceTaskManagerConfig(enabled=False),
        ),
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    client = TestClient(application)

    try:
        with client:
            response = client.post(
                "/api/v1/workflows/projects/project-1/applications/process-fail-app/execute",
                headers=build_test_headers(scopes="workflows:read,workflows:write"),
                json={
                    "input_bindings": {"request_text": {"value": "hello execute api"}},
                    "execution_metadata": {"marker": "api-execute-failure"},
                },
            )
    finally:
        session_factory.engine.dispose()

    assert response.status_code == 500
    error = response.json()["error"]
    assert error["code"] == "service_configuration_error"
    assert error["message"] == "workflow 节点执行失败"
    assert error["details"]["node_id"] == "explode"
    assert error["details"]["node_type_id"] == "custom.test.process-fail"
    assert error["details"]["runtime_kind"] == "python-callable"
    assert error["details"]["execution_index"] == 1
    assert error["details"]["sequence_index"] == 1
    assert error["details"]["error_type"] == "AssertionError"
    assert error["details"]["error_message"] == "process fail"


def _build_process_echo_template():
    """构造进程隔离测试使用的最小 workflow 模板。"""

    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphEdge,
        WorkflowGraphInput,
        WorkflowGraphNode,
        WorkflowGraphOutput,
        WorkflowGraphTemplate,
    )

    return WorkflowGraphTemplate(
        template_id="process-echo-template",
        template_version="1.0.0",
        display_name="Process Echo Template",
        nodes=(
            WorkflowGraphNode(
                node_id="echo",
                node_type_id="custom.test.process-echo",
            ),
            WorkflowGraphNode(
                node_id="response",
                node_type_id="core.output.http-response",
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-echo-response",
                source_node_id="echo",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="echo",
                target_port="text",
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


def _build_process_echo_application():
    """构造进程隔离测试使用的最小流程应用。"""

    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        FlowApplicationBinding,
        FlowTemplateReference,
    )

    return FlowApplication(
        application_id="process-echo-app",
        display_name="Process Echo App",
        template_ref=FlowTemplateReference(
            template_id="process-echo-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_text",
                direction="input",
                template_port_id="request_text",
                binding_kind="api-request",
                config={"route": "/execute/process-echo", "method": "POST"},
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


def _build_process_fail_template():
    """构造节点执行失败测试使用的最小 workflow 模板。"""

    from backend.contracts.workflows.workflow_graph import (
        WorkflowGraphInput,
        WorkflowGraphNode,
        WorkflowGraphOutput,
        WorkflowGraphTemplate,
    )

    return WorkflowGraphTemplate(
        template_id="process-fail-template",
        template_version="1.0.0",
        display_name="Process Fail Template",
        nodes=(
            WorkflowGraphNode(
                node_id="explode",
                node_type_id="custom.test.process-fail",
                metadata={"sequence_index": 1},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_text",
                display_name="Request Text",
                payload_type_id="text.v1",
                target_node_id="explode",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="body",
                display_name="Body",
                payload_type_id="response-body.v1",
                source_node_id="explode",
                source_port="body",
            ),
        ),
    )


def _build_process_fail_application():
    """构造节点执行失败测试使用的最小流程应用。"""

    from backend.contracts.workflows.workflow_graph import (
        FlowApplication,
        FlowApplicationBinding,
        FlowTemplateReference,
    )

    return FlowApplication(
        application_id="process-fail-app",
        display_name="Process Fail App",
        template_ref=FlowTemplateReference(
            template_id="process-fail-template",
            template_version="1.0.0",
            source_kind="json-file",
            source_uri="placeholder",
        ),
        bindings=(
            FlowApplicationBinding(
                binding_id="request_text",
                direction="input",
                template_port_id="request_text",
                binding_kind="api-request",
                config={"route": "/execute/process-fail", "method": "POST"},
            ),
            FlowApplicationBinding(
                binding_id="body",
                direction="output",
                template_port_id="body",
                binding_kind="workflow-execute-output",
                config={"status_code": 200},
            ),
        ),
    )


def _create_process_test_node_pack_fixture(tmp_path: Path) -> Path:
    """创建进程隔离测试使用的最小 custom node pack。"""

    node_pack_dir = tmp_path / "custom_nodes" / "process_test_nodes"
    backend_dir = node_pack_dir / "backend"
    workflow_dir = node_pack_dir / "workflow"
    backend_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)
    (node_pack_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "entry.py").write_text(
        """
import os
import multiprocessing


def _process_echo_handler(request):
    text_payload = request.input_values.get("text")
    if isinstance(text_payload, dict):
        message = str(text_payload.get("value") or "")
    else:
        message = str(text_payload or "")
    return {
        "body": {
            "message": message,
            "marker": request.execution_metadata.get("marker"),
            "workflow_run_id": request.execution_metadata.get("workflow_run_id"),
            "pid": os.getpid(),
            "is_daemon": multiprocessing.current_process().daemon,
        }
    }


def _process_fail_handler(request):
    raise AssertionError("process fail")


def register(context):
    context.register_python_callable("custom.test.process-echo", _process_echo_handler)
    context.register_python_callable("custom.test.process-fail", _process_fail_handler)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    manifest_payload = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "test.process-nodes",
        "version": "0.1.0",
        "displayName": "Test Process Nodes",
        "description": "用于验证 workflow application 隔离子进程执行的测试节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node"],
        "entrypoints": {"backend": "custom_nodes.process_test_nodes.backend.entry:register"},
        "compatibility": {"api": ">=0.1 <1.0", "runtime": ">=3.12"},
        "timeout": {"defaultSeconds": 30},
        "enabledByDefault": True,
        "customNodeCatalogPath": "workflow/catalog.json",
    }
    workflow_catalog_payload = {
        "format_id": "amvision.custom-node-catalog.v1",
        "payload_contracts": [
            {
                "format_id": "amvision.workflow-payload-contract.v1",
                "payload_type_id": "text.v1",
                "display_name": "Text",
                "transport_kind": "inline-json",
                "json_schema": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                "artifact_kinds": [],
                "metadata": {},
            }
        ],
        "node_definitions": [
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.test.process-echo",
                "display_name": "Process Echo",
                "category": "test.process",
                "description": "返回当前子进程 pid 与请求文本。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [
                    {
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "output_ports": [
                    {
                        "name": "body",
                        "display_name": "Body",
                        "payload_type_id": "response-body.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["test.process"],
                "runtime_requirements": {},
                "node_pack_id": "test.process-nodes",
                "node_pack_version": "0.1.0",
            },
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.test.process-fail",
                "display_name": "Process Fail",
                "category": "test.process",
                "description": "主动抛出 AssertionError，用于验证失败节点定位。",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "input_ports": [
                    {
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "output_ports": [
                    {
                        "name": "body",
                        "display_name": "Body",
                        "payload_type_id": "response-body.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["test.process"],
                "runtime_requirements": {},
                "node_pack_id": "test.process-nodes",
                "node_pack_version": "0.1.0",
            }
        ],
    }
    (node_pack_dir / "manifest.json").write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (workflow_dir / "catalog.json").write_text(
        json.dumps(workflow_catalog_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return tmp_path / "custom_nodes"