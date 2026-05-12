"""workflow 节点运行时注册表加载器测试。"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import backend.nodes.core_nodes.yolox_inference_submit as yolox_inference_submit_node
from backend.contracts.workflows.workflow_graph import (
    WorkflowGraphEdge,
    WorkflowGraphInput,
    WorkflowGraphNode,
    WorkflowGraphOutput,
    WorkflowGraphTemplate,
)
from backend.nodes import ExecutionImageRegistry, build_memory_image_payload
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.datasets.dataset_export_delivery import DatasetExportPackage
from backend.service.application.errors import ServiceConfigurationError
from backend.service.application.models.yolox_evaluation_task_service import YoloXEvaluationTaskPackage
from backend.service.application.models.yolox_inference_task_service import (
    YoloXInferenceExecutionResult,
)
from backend.service.application.deployments import PublishedInferenceResult
from backend.service.application.models.yolox_training_service import (
    YoloXTrainingTaskSubmission,
)
from backend.service.application.workflows.execution_cleanup import (
    WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT,
    list_registered_execution_cleanups,
)
from backend.service.application.workflows.graph_executor import WorkflowGraphExecutor
from backend.service.application.workflows.service_node_runtime import (
    WorkflowServiceNodeRuntimeContext,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from tests.api_test_support import build_test_jpeg_bytes, build_valid_test_png_bytes
from tests.yolox_test_support import FakeDeploymentProcessSupervisor


def test_runtime_registry_loader_registers_python_and_worker_handlers_from_entrypoint(
    tmp_path: Path,
) -> None:
    """验证 node pack backend entrypoint 会把 python-callable 与 worker-task handler 注册到执行器。"""

    custom_nodes_root_dir = _create_executable_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="custom-text-pipeline",
        template_version="1.0.0",
        display_name="Custom Text Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="normalize", node_type_id="custom.text.normalize"),
            WorkflowGraphNode(node_id="uppercase", node_type_id="custom.text.uppercase-worker"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-normalize-uppercase",
                source_node_id="normalize",
                source_port="text",
                target_node_id="uppercase",
                target_port="text",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="source_text",
                display_name="Source Text",
                payload_type_id="text.v1",
                target_node_id="normalize",
                target_port="text",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="final_text",
                display_name="Final Text",
                payload_type_id="text.v1",
                source_node_id="uppercase",
                source_port="result",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={"source_text": {"value": "  hello node pack  "}},
    )

    assert execution_result.outputs["final_text"]["value"] == "HELLO NODE PACK"
    assert [record.runtime_kind for record in execution_result.node_records] == [
        "python-callable",
        "worker-task",
    ]


def test_runtime_registry_loader_requires_backend_entrypoint_for_executable_custom_nodes(
    tmp_path: Path,
) -> None:
    """验证可执行 custom node 缺少 backend entrypoint 时会在注册阶段直接失败。"""

    custom_nodes_root_dir = _create_missing_entrypoint_node_pack_fixture(tmp_path)
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )

    with pytest.raises(ServiceConfigurationError, match="backend entrypoint"):
        runtime_registry_loader.refresh()


def test_runtime_registry_loader_registers_core_basic_nodes(
    tmp_path: Path,
) -> None:
    """验证 runtime registry loader 会为基础 core 节点注册可执行 handler。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.png", build_valid_test_png_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="core-basic-pipeline",
        template_version="1.0.0",
        display_name="Core Basic Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="save",
                node_type_id="core.io.image-save",
                parameters={"object_key": "workflow/previews/saved-source.png"},
            ),
            WorkflowGraphNode(
                node_id="preview",
                node_type_id="core.io.image-preview",
                parameters={"title": "Saved Preview"},
            ),
            WorkflowGraphNode(
                node_id="response",
                node_type_id="core.output.http-response",
                parameters={"status_code": 201},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-save",
                source_node_id="input",
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
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="inspection_response",
                display_name="Inspection Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.png",
                "width": 2,
                "height": 2,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "core-basic",
        },
    )

    response_payload = execution_result.outputs["inspection_response"]
    assert response_payload["status_code"] == 201
    assert response_payload["body"]["type"] == "image-preview"
    assert response_payload["body"]["title"] == "Saved Preview"
    assert response_payload["body"]["image"]["transport_kind"] == "inline-base64"
    assert response_payload["body"]["image"]["media_type"] == "image/png"
    assert response_payload["body"]["image"]["image_base64"]
    assert dataset_storage.resolve("workflow/previews/saved-source.png").is_file()


def test_runtime_registry_loader_registers_core_service_nodes(
    tmp_path: Path,
) -> None:
    """验证 runtime registry loader 会为内建 service nodes 注册 handler。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )

    runtime_registry_loader.refresh()
    runtime_registry = runtime_registry_loader.get_runtime_registry()

    expected_node_type_ids = {
        "core.service.dataset-export.package",
        "core.service.dataset-export.submit",
        "core.service.yolox-training.submit",
        "core.service.yolox-conversion.submit",
        "core.service.yolox-deployment.health",
        "core.service.yolox-deployment.reset",
        "core.service.yolox-deployment.start",
        "core.service.yolox-deployment.status",
        "core.service.yolox-deployment.stop",
        "core.service.yolox-deployment.warmup",
        "core.service.yolox-validation-session.create",
        "core.service.yolox-evaluation.package",
        "core.service.yolox-evaluation.submit",
        "core.service.yolox-deployment.create",
        "core.service.yolox-inference.submit",
        "core.model.yolox-detection",
    }
    for node_type_id in expected_node_type_ids:
        node_definition = runtime_registry.get_node_definition(node_type_id)
        assert runtime_registry.has_registered_handler(node_definition=node_definition)

    stop_node_definition = runtime_registry.get_node_definition("core.service.yolox-deployment.stop")
    assert [port.name for port in stop_node_definition.input_ports] == ["request", "dependency"]


def test_core_training_service_node_uses_runtime_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 core 训练 service node 会通过 runtime context 调用现有 service。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    captured: dict[str, object] = {}

    class _FakeTrainingService:
        """记录训练提交调用参数的假 service。"""

        def submit_training_task(self, request, *, created_by=None, display_name=""):
            """记录一次训练任务提交。"""

            captured["request"] = request
            captured["created_by"] = created_by
            captured["display_name"] = display_name
            return YoloXTrainingTaskSubmission(
                task_id="task-training-1",
                status="queued",
                queue_name="yolox-trainings",
                queue_task_id="queue-training-1",
                dataset_export_id="dataset-export-1",
                dataset_export_manifest_key="exports/manifest.json",
                dataset_version_id="dataset-version-1",
                format_id="coco-detection-v1",
            )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_training_task_service",
        lambda self: _FakeTrainingService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
    )
    template = WorkflowGraphTemplate(
        template_id="training-submit-workflow",
        template_version="1.0.0",
        display_name="Training Submit Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="train",
                node_type_id="core.service.yolox-training.submit",
                parameters={
                    "project_id": "project-1",
                    "dataset_export_id": "dataset-export-1",
                    "recipe_id": "recipe-1",
                    "model_scale": "s",
                    "output_model_name": "demo-model",
                    "max_epochs": 3,
                    "display_name": "training flow",
                    "created_by": "workflow-user",
                },
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="submission",
                display_name="Submission",
                payload_type_id="response-body.v1",
                source_node_id="train",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={},
        runtime_context=runtime_context,
    )

    body = execution_result.outputs["submission"]
    assert body["task_id"] == "task-training-1"
    assert body["queue_name"] == "yolox-trainings"
    assert captured["created_by"] == "workflow-user"
    assert captured["display_name"] == "training flow"
    assert captured["request"].project_id == "project-1"
    assert captured["request"].recipe_id == "recipe-1"
    assert captured["request"].max_epochs == 3


def test_core_dataset_export_package_service_node_uses_runtime_context_and_registers_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 core 数据集导出打包节点会调用 delivery service，并登记临时 zip cleanup。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    captured: dict[str, object] = {}

    class _FakeDatasetExportDeliveryService:
        """记录 package 调用参数并返回稳定打包结果的假 service。"""

        def package_export(
            self,
            dataset_export_id: str,
            *,
            rebuild: bool = False,
            package_object_key: str | None = None,
            persist_package_metadata: bool = True,
        ) -> DatasetExportPackage:
            """记录打包调用参数。"""

            captured["dataset_export_id"] = dataset_export_id
            captured["rebuild"] = rebuild
            captured["package_object_key"] = package_object_key
            captured["persist_package_metadata"] = persist_package_metadata
            return DatasetExportPackage(
                dataset_export_id=dataset_export_id,
                export_path="exports/dataset-export-1",
                manifest_object_key="exports/dataset-export-1/manifest.json",
                package_object_key=str(package_object_key),
                package_file_name="dataset-1-coco-detection-v1-dataset-export-1.zip",
                package_size=256,
                packaged_at="2026-05-09T00:00:00+00:00",
            )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_dataset_export_delivery_service",
        lambda self: _FakeDatasetExportDeliveryService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
    )
    execution_metadata: dict[str, object] = {"workflow_run_id": "run-1"}
    template = WorkflowGraphTemplate(
        template_id="dataset-export-package-workflow",
        template_version="1.0.0",
        display_name="Dataset Export Package Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="package",
                node_type_id="core.service.dataset-export.package",
                parameters={
                    "dataset_export_id": "dataset-export-1",
                    "cleanup_on_completion": True,
                },
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="package_body",
                display_name="Package Body",
                payload_type_id="response-body.v1",
                source_node_id="package",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={},
        execution_metadata=execution_metadata,
        runtime_context=runtime_context,
    )

    package_body = execution_result.outputs["package_body"]
    assert package_body["dataset_export_id"] == "dataset-export-1"
    assert captured["dataset_export_id"] == "dataset-export-1"
    assert captured["rebuild"] is False
    assert captured["persist_package_metadata"] is False
    assert captured["package_object_key"] == "workflows/runtime/run-1/package/dataset-export-dataset-export-1.zip"
    cleanup_items = list_registered_execution_cleanups(execution_metadata)
    assert len(cleanup_items) == 1
    assert cleanup_items[0].resource_kind == WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT
    assert cleanup_items[0].resource_id == captured["package_object_key"]


def test_core_yolox_evaluation_package_service_node_uses_runtime_context_and_registers_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 core YOLOX evaluation package 节点会调用 task service，并登记临时 zip cleanup。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    captured: dict[str, object] = {}

    class _FakeYoloXEvaluationTaskService:
        """记录 evaluation package 调用参数并返回稳定结果的假 service。"""

        def package_evaluation_result(
            self,
            task_id: str,
            *,
            rebuild: bool = False,
            package_object_key: str | None = None,
        ) -> YoloXEvaluationTaskPackage:
            """记录打包调用参数。"""

            captured["task_id"] = task_id
            captured["rebuild"] = rebuild
            captured["package_object_key"] = package_object_key
            return YoloXEvaluationTaskPackage(
                task_id=task_id,
                package_object_key=str(package_object_key),
                package_file_name="yolox-evaluation-task-evaluation-1-result-package.zip",
                package_size=512,
                packaged_at="2026-05-09T00:00:00+00:00",
            )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_evaluation_task_service",
        lambda self: _FakeYoloXEvaluationTaskService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
    )
    execution_metadata: dict[str, object] = {"workflow_run_id": "run-1"}
    template = WorkflowGraphTemplate(
        template_id="yolox-evaluation-package-workflow",
        template_version="1.0.0",
        display_name="YOLOX Evaluation Package Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="package",
                node_type_id="core.service.yolox-evaluation.package",
                parameters={
                    "task_id": "task-evaluation-1",
                    "cleanup_on_completion": True,
                },
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="package_body",
                display_name="Package Body",
                payload_type_id="response-body.v1",
                source_node_id="package",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={},
        execution_metadata=execution_metadata,
        runtime_context=runtime_context,
    )

    package_body = execution_result.outputs["package_body"]
    assert package_body["task_id"] == "task-evaluation-1"
    assert captured["task_id"] == "task-evaluation-1"
    assert captured["rebuild"] is False
    assert (
        captured["package_object_key"]
        == "workflows/runtime/run-1/package/yolox-evaluation-task-evaluation-1-result-package.zip"
    )
    cleanup_items = list_registered_execution_cleanups(execution_metadata)
    assert len(cleanup_items) == 1
    assert cleanup_items[0].resource_kind == WORKFLOW_EXECUTION_CLEANUP_KIND_DATASET_STORAGE_OBJECT
    assert cleanup_items[0].resource_id == captured["package_object_key"]


def test_core_yolox_detection_node_uses_sync_runtime_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 core.model.yolox-detection 会通过同步 deployment runtime 执行推理。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())
    runtime_registry_loader.refresh()

    fake_supervisor_calls: dict[str, object] = {}

    class _FakeDeploymentService:
        """返回稳定 process_config 的假 deployment service。"""

        def resolve_process_config(self, deployment_instance_id: str):
            """返回最小 process_config。"""

            return SimpleNamespace(deployment_instance_id=deployment_instance_id)

    class _FakeSyncSupervisor:
        """记录同步 deployment 调用的假 supervisor。"""

        def ensure_deployment(self, config) -> None:
            """记录 ensure 调用。"""

            fake_supervisor_calls["ensure_config"] = config

        def get_status(self, config):
            """返回 running 状态。"""

            fake_supervisor_calls["status_config"] = config
            return SimpleNamespace(process_state="running")

    def _fake_run_yolox_inference_task(**kwargs):
        """返回固定 detection 结果。"""

        fake_supervisor_calls["inference_kwargs"] = kwargs
        return YoloXInferenceExecutionResult(
            instance_id="instance-1",
            detections=(
                {
                    "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                    "score": 0.97,
                    "class_id": 0,
                    "class_name": "defect",
                },
            ),
            latency_ms=8.5,
            image_width=64,
            image_height=64,
            preview_image_bytes=None,
            runtime_session_info={"backend_name": "fake"},
        )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )
    _install_fake_published_inference_gateway(monkeypatch, fake_supervisor_calls, class_name="defect")

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=dataset_storage,
        yolox_sync_deployment_process_supervisor=_FakeSyncSupervisor(),
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-detection-workflow",
        template_version="1.0.0",
        display_name="YOLOX Detection Workflow",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="detect",
                node_type_id="core.model.yolox-detection",
                parameters={
                    "deployment_instance_id": "deployment-instance-1",
                    "score_threshold": 0.42,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-detect",
                source_node_id="input",
                source_port="image",
                target_node_id="detect",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
                source_node_id="detect",
                source_port="detections",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            }
        },
        execution_metadata={"dataset_storage": dataset_storage},
        runtime_context=runtime_context,
    )

    detections = execution_result.outputs["detections"]
    assert detections["items"][0]["class_name"] == "defect"
    assert fake_supervisor_calls["inference_kwargs"]["input_uri"] == "inputs/source.jpg"
    assert fake_supervisor_calls["inference_kwargs"]["score_threshold"] == 0.42
    assert fake_supervisor_calls["ensure_config"].deployment_instance_id == "deployment-instance-1"


def test_core_yolox_detection_node_accepts_dynamic_request_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 core.model.yolox-detection 可以从 request 输入读取动态 deployment_instance_id。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source-dynamic.jpg", build_test_jpeg_bytes())
    runtime_registry_loader.refresh()

    fake_supervisor_calls: dict[str, object] = {}

    class _FakeDeploymentService:
        """返回稳定 process_config 的假 deployment service。"""

        def resolve_process_config(self, deployment_instance_id: str):
            """返回最小 process_config。"""

            fake_supervisor_calls["resolved_deployment_instance_id"] = deployment_instance_id
            return SimpleNamespace(deployment_instance_id=deployment_instance_id)

    class _FakeSyncSupervisor:
        """记录同步 deployment 调用的假 supervisor。"""

        def ensure_deployment(self, config) -> None:
            """记录 ensure 调用。"""

            fake_supervisor_calls["ensure_config"] = config

        def get_status(self, config):
            """返回 running 状态。"""

            fake_supervisor_calls["status_config"] = config
            return SimpleNamespace(process_state="running")

    def _fake_run_yolox_inference_task(**kwargs):
        """返回固定 detection 结果。"""

        fake_supervisor_calls["inference_kwargs"] = kwargs
        return YoloXInferenceExecutionResult(
            instance_id="instance-dynamic-1",
            detections=(
                {
                    "bbox_xyxy": [6.0, 8.0, 28.0, 32.0],
                    "score": 0.91,
                    "class_id": 0,
                    "class_name": "qr-region",
                },
            ),
            latency_ms=7.2,
            image_width=64,
            image_height=64,
            preview_image_bytes=None,
            runtime_session_info={"backend_name": "fake"},
        )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )
    _install_fake_published_inference_gateway(monkeypatch, fake_supervisor_calls, class_name="qr-region")

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=dataset_storage,
        yolox_sync_deployment_process_supervisor=_FakeSyncSupervisor(),
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-detection-dynamic-workflow",
        template_version="1.0.0",
        display_name="YOLOX Detection Dynamic Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="detect",
                node_type_id="core.model.yolox-detection",
                parameters={},
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="detect",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_payload",
                display_name="Request Payload",
                payload_type_id="value.v1",
                target_node_id="detect",
                target_port="request",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
                source_node_id="detect",
                source_port="detections",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source-dynamic.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            },
            "request_payload": {
                "value": {
                    "deployment_instance_id": "deployment-instance-dynamic-1",
                    "score_threshold": 0.55,
                }
            },
        },
        execution_metadata={"dataset_storage": dataset_storage},
        runtime_context=runtime_context,
    )

    detections = execution_result.outputs["detections"]
    assert detections["items"][0]["class_name"] == "qr-region"
    assert fake_supervisor_calls["resolved_deployment_instance_id"] == "deployment-instance-dynamic-1"
    assert fake_supervisor_calls["inference_kwargs"]["score_threshold"] == 0.55


def test_core_yolox_detection_node_auto_starts_sync_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证检测节点在 workflow 内默认会自动拉起本地 sync deployment 进程。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())
    runtime_registry_loader.refresh()

    fake_supervisor_calls: dict[str, object] = {"process_state": "stopped"}

    class _FakeDeploymentService:
        """返回稳定 process_config 的假 deployment service。"""

        def resolve_process_config(self, deployment_instance_id: str):
            """返回最小 process_config。"""

            return SimpleNamespace(deployment_instance_id=deployment_instance_id)

    class _FakeSyncSupervisor:
        """模拟从 stopped 到 running 的 sync supervisor。"""

        def ensure_deployment(self, config) -> None:
            """记录 ensure 调用。"""

            fake_supervisor_calls["ensure_config"] = config

        def get_status(self, config):
            """返回当前进程状态。"""

            fake_supervisor_calls["status_config"] = config
            return SimpleNamespace(process_state=fake_supervisor_calls["process_state"])

        def start_deployment(self, config):
            """把进程状态切到 running。"""

            fake_supervisor_calls["start_config"] = config
            fake_supervisor_calls["process_state"] = "running"
            return SimpleNamespace(process_state="running")

    def _fake_run_yolox_inference_task(**kwargs):
        """返回固定 detection 结果。"""

        fake_supervisor_calls["inference_kwargs"] = kwargs
        return YoloXInferenceExecutionResult(
            instance_id="instance-1",
            detections=(
                {
                    "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                    "score": 0.97,
                    "class_id": 0,
                    "class_name": "defect",
                },
            ),
            latency_ms=8.5,
            image_width=64,
            image_height=64,
            preview_image_bytes=None,
            runtime_session_info={"backend_name": "fake"},
        )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )
    _install_fake_published_inference_gateway(monkeypatch, fake_supervisor_calls, class_name="defect")

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=dataset_storage,
        yolox_sync_deployment_process_supervisor=_FakeSyncSupervisor(),
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-detection-auto-start-workflow",
        template_version="1.0.0",
        display_name="YOLOX Detection Auto Start Workflow",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="detect",
                node_type_id="core.model.yolox-detection",
                parameters={
                    "deployment_instance_id": "deployment-instance-1",
                    "score_threshold": 0.42,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-detect",
                source_node_id="input",
                source_port="image",
                target_node_id="detect",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
                source_node_id="detect",
                source_port="detections",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            }
        },
        execution_metadata={"dataset_storage": dataset_storage},
        runtime_context=runtime_context,
    )

    assert execution_result.outputs["detections"]["items"][0]["class_name"] == "defect"
    assert fake_supervisor_calls["start_config"].deployment_instance_id == "deployment-instance-1"


def test_core_image_base64_decode_node_outputs_memory_image_ref(tmp_path: Path) -> None:
    """验证 core.io.image-base64-decode 会输出 execution-scoped memory image-ref。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    registry = ExecutionImageRegistry()
    source_bytes = build_valid_test_png_bytes()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="image-base64-decode-workflow",
        template_version="1.0.0",
        display_name="Image Base64 Decode Workflow",
        nodes=(
            WorkflowGraphNode(node_id="decode", node_type_id="core.io.image-base64-decode"),
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
                output_id="image",
                display_name="Image",
                payload_type_id="image-ref.v1",
                source_node_id="decode",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "image_base64": base64.b64encode(source_bytes).decode("ascii"),
            }
        },
        execution_metadata={"execution_image_registry": registry},
    )

    image_payload = execution_result.outputs["image"]
    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/png"
    assert isinstance(image_payload["image_handle"], str)
    assert registry.read_bytes(str(image_payload["image_handle"])) == source_bytes


def test_core_yolox_detection_node_accepts_memory_image_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 core.model.yolox-detection 在 memory image-ref 输入下会直接传递图片字节。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    image_registry = ExecutionImageRegistry()
    source_bytes = build_test_jpeg_bytes()
    registered_image = image_registry.register_image_bytes(
        content=source_bytes,
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )
    fake_supervisor_calls: dict[str, object] = {}

    class _FakeDeploymentService:
        """返回稳定 process_config 的假 deployment service。"""

        def resolve_process_config(self, deployment_instance_id: str):
            """返回最小 process_config。"""

            return SimpleNamespace(deployment_instance_id=deployment_instance_id)

    class _FakeSyncSupervisor:
        """记录同步 deployment 调用的假 supervisor。"""

        def ensure_deployment(self, config) -> None:
            """记录 ensure 调用。"""

            fake_supervisor_calls["ensure_config"] = config

        def get_status(self, config):
            """返回 running 状态。"""

            fake_supervisor_calls["status_config"] = config
            return SimpleNamespace(process_state="running")

    def _fake_run_yolox_inference_task(**kwargs):
        """返回固定 detection 结果并记录输入参数。"""

        fake_supervisor_calls["inference_kwargs"] = kwargs
        return YoloXInferenceExecutionResult(
            instance_id="instance-1",
            detections=(
                {
                    "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                    "score": 0.97,
                    "class_id": 0,
                    "class_name": "defect",
                },
            ),
            latency_ms=8.5,
            image_width=64,
            image_height=64,
            preview_image_bytes=None,
            runtime_session_info={"backend_name": "fake"},
        )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )
    _install_fake_published_inference_gateway(monkeypatch, fake_supervisor_calls, class_name="defect")

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
        yolox_sync_deployment_process_supervisor=_FakeSyncSupervisor(),
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-detection-memory-workflow",
        template_version="1.0.0",
        display_name="YOLOX Detection Memory Workflow",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="detect",
                node_type_id="core.model.yolox-detection",
                parameters={
                    "deployment_instance_id": "deployment-instance-1",
                    "score_threshold": 0.42,
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-detect",
                source_node_id="input",
                source_port="image",
                target_node_id="detect",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="detections",
                display_name="Detections",
                payload_type_id="detections.v1",
                source_node_id="detect",
                source_port="detections",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": build_memory_image_payload(
                image_handle=registered_image.image_handle,
                media_type="image/jpeg",
                width=64,
                height=64,
            )
        },
        execution_metadata={"execution_image_registry": image_registry},
        runtime_context=runtime_context,
    )

    assert execution_result.outputs["detections"]["items"][0]["class_name"] == "defect"
    assert fake_supervisor_calls["inference_kwargs"]["input_uri"] is None
    assert fake_supervisor_calls["inference_kwargs"]["input_image_bytes"] == source_bytes


def test_core_yolox_inference_submit_node_auto_starts_async_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证异步推理提交节点在 workflow 内默认会自动拉起本地 async deployment 进程。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())
    runtime_registry_loader.refresh()

    fake_supervisor_calls: dict[str, object] = {"process_state": "stopped"}

    class _FakeDeploymentService:
        """返回稳定 deployment 视图与 process_config 的假 service。"""

        def get_deployment_instance(self, deployment_instance_id: str):
            """返回最小 deployment view。"""

            return SimpleNamespace(
                deployment_instance_id=deployment_instance_id,
                project_id="project-1",
            )

        def resolve_process_config(self, deployment_instance_id: str):
            """返回最小 process_config。"""

            return SimpleNamespace(deployment_instance_id=deployment_instance_id)

    class _FakeAsyncSupervisor:
        """模拟从 stopped 到 running 的 async supervisor。"""

        def ensure_deployment(self, config) -> None:
            """记录 ensure 调用。"""

            fake_supervisor_calls["ensure_config"] = config

        def get_status(self, config):
            """返回当前进程状态。"""

            fake_supervisor_calls["status_config"] = config
            return SimpleNamespace(process_state=fake_supervisor_calls["process_state"])

        def start_deployment(self, config):
            """把进程状态切到 running。"""

            fake_supervisor_calls["start_config"] = config
            fake_supervisor_calls["process_state"] = "running"
            return SimpleNamespace(process_state="running")

    class _FakeInferenceTaskService:
        """记录推理任务提交调用的假 service。"""

        def submit_inference_task(self, request, *, created_by=None, display_name=""):
            """记录一次推理任务提交。"""

            fake_supervisor_calls["request"] = request
            fake_supervisor_calls["created_by"] = created_by
            fake_supervisor_calls["display_name"] = display_name
            return SimpleNamespace(
                task_id="task-inference-1",
                status="queued",
                queue_name="yolox-inference",
                queue_task_id="queue-inference-1",
                deployment_instance_id=request.deployment_instance_id,
                input_uri=request.input_uri,
            )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )
    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_inference_task_service",
        lambda self: _FakeInferenceTaskService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=dataset_storage,
        yolox_async_deployment_process_supervisor=_FakeAsyncSupervisor(),
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-inference-submit-auto-start-workflow",
        template_version="1.0.0",
        display_name="YOLOX Inference Submit Auto Start Workflow",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="infer",
                node_type_id="core.service.yolox-inference.submit",
                parameters={
                    "project_id": "project-1",
                    "deployment_instance_id": "deployment-instance-1",
                    "display_name": "workflow inference",
                    "created_by": "workflow-user",
                },
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-infer",
                source_node_id="input",
                source_port="image",
                target_node_id="infer",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="submission",
                display_name="Submission",
                payload_type_id="response-body.v1",
                source_node_id="infer",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            }
        },
        execution_metadata={"dataset_storage": dataset_storage},
        runtime_context=runtime_context,
    )

    submission = execution_result.outputs["submission"]
    assert submission["task_id"] == "task-inference-1"
    assert fake_supervisor_calls["start_config"].deployment_instance_id == "deployment-instance-1"
    assert fake_supervisor_calls["request"].input_uri == "inputs/source.jpg"


def test_core_yolox_deployment_create_node_accepts_dynamic_request_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 deployment.create 节点可以从 request 输入读取动态参数并显式写入 keep_warm。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    captured: dict[str, object] = {}

    class _FakeDeploymentService:
        """记录 create request 的假 deployment service。"""

        def create_deployment_instance(self, request, *, created_by: str):
            """返回固定 deployment view。"""

            captured["request"] = request
            captured["created_by"] = created_by
            return {
                "deployment_instance_id": "deployment-instance-created-1",
                "project_id": request.project_id,
                "model_build_id": request.model_build_id,
                "display_name": request.display_name,
            }

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-deployment-create-dynamic-workflow",
        template_version="1.0.0",
        display_name="YOLOX Deployment Create Dynamic Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="create",
                node_type_id="core.service.yolox-deployment.create",
                parameters={},
            ),
        ),
        edges=(),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_payload",
                display_name="Request Payload",
                payload_type_id="value.v1",
                target_node_id="create",
                target_port="request",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="body",
                display_name="Body",
                payload_type_id="response-body.v1",
                source_node_id="create",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_payload": {
                "value": {
                    "project_id": "project-1",
                    "model_build_id": "model-build-dynamic-1",
                    "runtime_backend": "tensorrt",
                    "runtime_precision": "fp16",
                    "instance_count": 3,
                    "keep_warm_enabled": True,
                    "metadata": {
                        "deployment_process": {
                            "warmup_dummy_inference_count": 6,
                        },
                        "request_source": "workflow-runtime",
                    },
                    "display_name": "dynamic deployment",
                    "created_by": "workflow-user",
                }
            }
        },
        runtime_context=runtime_context,
    )

    body = execution_result.outputs["body"]
    assert body["deployment_instance_id"] == "deployment-instance-created-1"
    assert captured["request"].project_id == "project-1"
    assert captured["request"].model_build_id == "model-build-dynamic-1"
    assert captured["request"].runtime_backend == "tensorrt"
    assert captured["request"].runtime_precision == "fp16"
    assert captured["request"].instance_count == 3
    assert captured["request"].metadata == {
        "deployment_process": {
            "warmup_dummy_inference_count": 6,
            "keep_warm_enabled": True,
        },
        "request_source": "workflow-runtime",
    }
    assert captured["created_by"] == "workflow-user"


def test_core_yolox_deployment_lifecycle_nodes_drive_sync_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 deployment lifecycle 节点可以驱动 sync supervisor 的完整控制链。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    deployment_view = _build_fake_deployment_view()
    process_config = _build_fake_process_config(instance_count=2)
    sync_supervisor = FakeDeploymentProcessSupervisor(runtime_mode="sync")
    async_supervisor = FakeDeploymentProcessSupervisor(runtime_mode="async")

    class _FakeDeploymentService:
        """返回固定 deployment view 与 process_config 的假 service。"""

        def get_deployment_instance(self, deployment_instance_id: str):
            """返回固定 deployment view。"""

            assert deployment_instance_id == deployment_view.deployment_instance_id
            return deployment_view

        def resolve_process_config(self, deployment_instance_id: str):
            """返回固定 process_config。"""

            assert deployment_instance_id == deployment_view.deployment_instance_id
            return process_config

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeDeploymentService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
        yolox_sync_deployment_process_supervisor=sync_supervisor,
        yolox_async_deployment_process_supervisor=async_supervisor,
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-deployment-lifecycle-sync-workflow",
        template_version="1.0.0",
        display_name="YOLOX Deployment Lifecycle Sync Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="start",
                node_type_id="core.service.yolox-deployment.start",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "sync",
                },
            ),
            WorkflowGraphNode(
                node_id="status",
                node_type_id="core.service.yolox-deployment.status",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "sync",
                },
            ),
            WorkflowGraphNode(
                node_id="warmup",
                node_type_id="core.service.yolox-deployment.warmup",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "sync",
                },
            ),
            WorkflowGraphNode(
                node_id="health",
                node_type_id="core.service.yolox-deployment.health",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "sync",
                },
            ),
            WorkflowGraphNode(
                node_id="reset",
                node_type_id="core.service.yolox-deployment.reset",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "sync",
                },
            ),
            WorkflowGraphNode(
                node_id="stop",
                node_type_id="core.service.yolox-deployment.stop",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "sync",
                },
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="start_body",
                display_name="Start Body",
                payload_type_id="response-body.v1",
                source_node_id="start",
                source_port="body",
            ),
            WorkflowGraphOutput(
                output_id="status_body",
                display_name="Status Body",
                payload_type_id="response-body.v1",
                source_node_id="status",
                source_port="body",
            ),
            WorkflowGraphOutput(
                output_id="warmup_body",
                display_name="Warmup Body",
                payload_type_id="response-body.v1",
                source_node_id="warmup",
                source_port="body",
            ),
            WorkflowGraphOutput(
                output_id="health_body",
                display_name="Health Body",
                payload_type_id="response-body.v1",
                source_node_id="health",
                source_port="body",
            ),
            WorkflowGraphOutput(
                output_id="reset_body",
                display_name="Reset Body",
                payload_type_id="response-body.v1",
                source_node_id="reset",
                source_port="body",
            ),
            WorkflowGraphOutput(
                output_id="stop_body",
                display_name="Stop Body",
                payload_type_id="response-body.v1",
                source_node_id="stop",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={},
        runtime_context=runtime_context,
    )

    start_body = execution_result.outputs["start_body"]
    status_body = execution_result.outputs["status_body"]
    warmup_body = execution_result.outputs["warmup_body"]
    health_body = execution_result.outputs["health_body"]
    reset_body = execution_result.outputs["reset_body"]
    stop_body = execution_result.outputs["stop_body"]

    assert start_body["process_state"] == "running"
    assert start_body["runtime_mode"] == "sync"
    assert status_body["desired_state"] == "running"
    assert warmup_body["warmed_instance_count"] == 2
    assert health_body["healthy_instance_count"] == 2
    assert reset_body["warmed_instance_count"] == 0
    assert stop_body["process_state"] == "stopped"
    assert sync_supervisor.load_calls == ["artifacts/runtime/model.onnx", "artifacts/runtime/model.onnx"]
    assert async_supervisor.load_calls == []


def test_core_yolox_deployment_health_node_uses_async_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证 deployment health 节点会按 runtime_mode 选择 async supervisor。"""

    custom_nodes_root_dir = tmp_path / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()

    deployment_view = _build_fake_deployment_view()
    process_config = _build_fake_process_config(instance_count=1)
    sync_supervisor = FakeDeploymentProcessSupervisor(runtime_mode="sync")
    async_supervisor = FakeDeploymentProcessSupervisor(runtime_mode="async")
    async_supervisor.warmup_deployment(process_config)
    async_state = async_supervisor._states[deployment_view.deployment_instance_id]
    async_state.last_error = "async-last-error"
    async_state.restart_count = 3

    class _FakeAsyncDeploymentService:
        """返回固定 deployment view 与 process_config 的假 service。"""

        def get_deployment_instance(self, deployment_instance_id: str):
            """返回固定 deployment view。"""

            assert deployment_instance_id == deployment_view.deployment_instance_id
            return deployment_view

        def resolve_process_config(self, deployment_instance_id: str):
            """返回固定 process_config。"""

            assert deployment_instance_id == deployment_view.deployment_instance_id
            return process_config

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: _FakeAsyncDeploymentService(),
    )

    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=object(),
        dataset_storage=_create_dataset_storage(tmp_path),
        yolox_sync_deployment_process_supervisor=sync_supervisor,
        yolox_async_deployment_process_supervisor=async_supervisor,
    )
    template = WorkflowGraphTemplate(
        template_id="yolox-deployment-health-async-workflow",
        template_version="1.0.0",
        display_name="YOLOX Deployment Health Async Workflow",
        nodes=(
            WorkflowGraphNode(
                node_id="health",
                node_type_id="core.service.yolox-deployment.health",
                parameters={
                    "deployment_instance_id": deployment_view.deployment_instance_id,
                    "runtime_mode": "async",
                },
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="health_body",
                display_name="Health Body",
                payload_type_id="response-body.v1",
                source_node_id="health",
                source_port="body",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={},
        runtime_context=runtime_context,
    )

    health_body = execution_result.outputs["health_body"]
    assert health_body["runtime_mode"] == "async"
    assert health_body["process_state"] == "running"
    assert health_body["healthy_instance_count"] == 1
    assert health_body["warmed_instance_count"] == 1
    assert health_body["restart_count"] == 3
    assert health_body["last_error"] == "async-last-error"
    assert health_body["keep_warm"] == {
        "enabled": False,
        "activated": False,
        "paused": False,
        "idle": True,
        "interval_seconds": 0.0,
        "yield_timeout_seconds": 0.0,
        "success_count": 0,
        "success_count_rollover_count": 0,
        "error_count": 0,
        "error_count_rollover_count": 0,
        "last_error": None,
    }
    assert sync_supervisor.load_calls == []
    assert async_supervisor.load_calls == ["artifacts/runtime/model.onnx"]


def test_repository_opencv_node_pack_executes_filter_nodes(
    tmp_path: Path,
) -> None:
    """验证仓库内置 OpenCV 节点包可以执行 blur 与 threshold 节点。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-filter-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Filter Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="blur",
                node_type_id="custom.opencv.gaussian-blur",
                parameters={"kernel_size": 5, "sigma_x": 1.2},
            ),
            WorkflowGraphNode(
                node_id="threshold",
                node_type_id="custom.opencv.binary-threshold",
                parameters={"threshold": 120, "max_value": 255},
            ),
            WorkflowGraphNode(node_id="preview", node_type_id="core.io.image-preview"),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-blur",
                source_node_id="input",
                source_port="image",
                target_node_id="blur",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-blur-threshold",
                source_node_id="blur",
                source_port="image",
                target_node_id="threshold",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-threshold-preview",
                source_node_id="threshold",
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
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="inspection_response",
                display_name="Inspection Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-filter",
        },
    )

    response_payload = execution_result.outputs["inspection_response"]
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["type"] == "image-preview"
    assert response_payload["body"]["image"]["transport_kind"] == "inline-base64"
    assert response_payload["body"]["image"]["media_type"] == "image/png"
    assert response_payload["body"]["image"]["image_base64"]
    assert [record.node_type_id for record in execution_result.node_records] == [
        "core.io.template-input.image",
        "custom.opencv.gaussian-blur",
        "custom.opencv.binary-threshold",
        "core.io.image-preview",
        "core.output.http-response",
    ]


def test_repository_opencv_filter_nodes_accept_memory_image_payload(
    tmp_path: Path,
) -> None:
    """验证 blur 与 threshold 节点链可以直接处理 memory image-ref。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    image_registry = ExecutionImageRegistry()
    source_image = image_registry.register_image_bytes(
        content=build_test_jpeg_bytes(),
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-filter-memory-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Filter Memory Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="blur",
                node_type_id="custom.opencv.gaussian-blur",
                parameters={"kernel_size": 5, "sigma_x": 1.2},
            ),
            WorkflowGraphNode(
                node_id="threshold",
                node_type_id="custom.opencv.binary-threshold",
                parameters={"threshold": 120, "max_value": 255},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-blur-threshold",
                source_node_id="blur",
                source_port="image",
                target_node_id="threshold",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="blur",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result_image",
                display_name="Result Image",
                payload_type_id="image-ref.v1",
                source_node_id="threshold",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": build_memory_image_payload(
                image_handle=source_image.image_handle,
                media_type="image/jpeg",
                width=64,
                height=64,
            )
        },
        execution_metadata={
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-filter-memory",
        },
    )

    image_payload = execution_result.outputs["result_image"]
    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/png"
    assert image_registry.read_bytes(str(image_payload["image_handle"])).startswith(b"\x89PNG\r\n\x1a\n")


def test_repository_opencv_node_pack_executes_draw_detections_node(
    tmp_path: Path,
) -> None:
    """验证仓库内置 OpenCV 节点包可以执行 draw-detections 节点。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-draw-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Draw Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="draw",
                node_type_id="custom.opencv.draw-detections",
                parameters={"line_thickness": 2, "font_scale": 0.5, "draw_scores": True},
            ),
            WorkflowGraphNode(node_id="preview", node_type_id="core.io.image-preview"),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-draw",
                source_node_id="input",
                source_port="image",
                target_node_id="draw",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-draw-preview",
                source_node_id="draw",
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
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_detections",
                display_name="Request Detections",
                payload_type_id="detections.v1",
                target_node_id="draw",
                target_port="detections",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="inspection_response",
                display_name="Inspection Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            },
            "request_detections": {
                "items": [
                    {
                        "bbox_xyxy": [5, 5, 40, 40],
                        "score": 0.95,
                        "class_name": "defect",
                    }
                ]
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-draw",
        },
    )

    response_payload = execution_result.outputs["inspection_response"]
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["type"] == "image-preview"
    assert response_payload["body"]["image"]["transport_kind"] == "inline-base64"
    assert response_payload["body"]["image"]["media_type"] == "image/png"
    assert response_payload["body"]["image"]["image_base64"]
    assert any(record.node_type_id == "custom.opencv.draw-detections" for record in execution_result.node_records)


def test_repository_opencv_draw_detections_node_defaults_to_memory_output_with_memory_input(
    tmp_path: Path,
) -> None:
    """验证 draw-detections 在 memory 输入下默认返回 memory image-ref。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    image_registry = ExecutionImageRegistry()
    source_image = image_registry.register_image_bytes(
        content=build_test_jpeg_bytes(),
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-draw-memory-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Draw Memory Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="draw",
                node_type_id="custom.opencv.draw-detections",
                parameters={"line_thickness": 2, "font_scale": 0.5, "draw_scores": True},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="draw",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_detections",
                display_name="Request Detections",
                payload_type_id="detections.v1",
                target_node_id="draw",
                target_port="detections",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="rendered_image",
                display_name="Rendered Image",
                payload_type_id="image-ref.v1",
                source_node_id="draw",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": build_memory_image_payload(
                image_handle=source_image.image_handle,
                media_type="image/jpeg",
                width=64,
                height=64,
            ),
            "request_detections": {
                "items": [
                    {
                        "bbox_xyxy": [5, 5, 40, 40],
                        "score": 0.95,
                        "class_name": "defect",
                    }
                ]
            },
        },
        execution_metadata={
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-draw-memory",
        },
    )

    image_payload = execution_result.outputs["rendered_image"]
    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/png"
    assert image_registry.read_bytes(str(image_payload["image_handle"])).startswith(b"\x89PNG\r\n\x1a\n")


def test_repository_opencv_node_pack_executes_morphology_and_canny_nodes(
    tmp_path: Path,
) -> None:
    """验证仓库内置 OpenCV 节点包可以执行 morphology 与 canny 节点。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-edge-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Edge Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="morphology",
                node_type_id="custom.opencv.morphology",
                parameters={"operation": "close", "shape": "rect", "kernel_size": 3, "iterations": 1},
            ),
            WorkflowGraphNode(
                node_id="canny",
                node_type_id="custom.opencv.canny",
                parameters={"threshold1": 20, "threshold2": 80, "aperture_size": 3, "l2_gradient": False},
            ),
            WorkflowGraphNode(node_id="preview", node_type_id="core.io.image-preview"),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-morphology",
                source_node_id="input",
                source_port="image",
                target_node_id="morphology",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-morphology-canny",
                source_node_id="morphology",
                source_port="image",
                target_node_id="canny",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-canny-preview",
                source_node_id="canny",
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
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="inspection_response",
                display_name="Inspection Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-edge",
        },
    )

    response_payload = execution_result.outputs["inspection_response"]
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["type"] == "image-preview"
    assert response_payload["body"]["image"]["transport_kind"] == "inline-base64"
    assert response_payload["body"]["image"]["media_type"] == "image/png"
    assert response_payload["body"]["image"]["image_base64"]
    assert [record.node_type_id for record in execution_result.node_records] == [
        "core.io.template-input.image",
        "custom.opencv.morphology",
        "custom.opencv.canny",
        "core.io.image-preview",
        "core.output.http-response",
    ]


def test_repository_opencv_morphology_and_canny_nodes_accept_memory_image_payload(
    tmp_path: Path,
) -> None:
    """验证 morphology 与 canny 节点链可以直接处理 memory image-ref。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    image_registry = ExecutionImageRegistry()
    source_image = image_registry.register_image_bytes(
        content=build_test_jpeg_bytes(),
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-edge-memory-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Edge Memory Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="morphology",
                node_type_id="custom.opencv.morphology",
                parameters={"operation": "close", "shape": "rect", "kernel_size": 3, "iterations": 1},
            ),
            WorkflowGraphNode(
                node_id="canny",
                node_type_id="custom.opencv.canny",
                parameters={"threshold1": 20, "threshold2": 80, "aperture_size": 3, "l2_gradient": False},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-morphology-canny",
                source_node_id="morphology",
                source_port="image",
                target_node_id="canny",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="morphology",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="result_image",
                display_name="Result Image",
                payload_type_id="image-ref.v1",
                source_node_id="canny",
                source_port="image",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": build_memory_image_payload(
                image_handle=source_image.image_handle,
                media_type="image/jpeg",
                width=64,
                height=64,
            )
        },
        execution_metadata={
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-edge-memory",
        },
    )

    image_payload = execution_result.outputs["result_image"]
    assert image_payload["transport_kind"] == "memory"
    assert image_payload["media_type"] == "image/png"
    assert image_registry.read_bytes(str(image_payload["image_handle"])).startswith(b"\x89PNG\r\n\x1a\n")


def test_repository_opencv_node_pack_executes_crop_export_node(
    tmp_path: Path,
) -> None:
    """验证仓库内置 OpenCV 节点包可以导出裁剪图集合。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-crop-export-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Crop Export Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="crop",
                node_type_id="custom.opencv.crop-export",
                parameters={"box_padding": 2, "max_crops": 2, "output_dir": "workflow/crops"},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-crop",
                source_node_id="input",
                source_port="image",
                target_node_id="crop",
                target_port="image",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_detections",
                display_name="Request Detections",
                payload_type_id="detections.v1",
                target_node_id="crop",
                target_port="detections",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="exported_crops",
                display_name="Exported Crops",
                payload_type_id="image-refs.v1",
                source_node_id="crop",
                source_port="crops",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            },
            "request_detections": {
                "items": [
                    {
                        "bbox_xyxy": [4, 4, 28, 28],
                        "score": 0.9,
                        "class_name": "part-a",
                    },
                    {
                        "bbox_xyxy": [20, 20, 52, 52],
                        "score": 0.8,
                        "class_name": "part-b",
                    },
                    {
                        "bbox_xyxy": [30, 30, 40, 40],
                        "score": 0.7,
                        "class_name": "part-c",
                    }
                ]
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-crop",
        },
    )

    crops_payload = execution_result.outputs["exported_crops"]
    assert crops_payload["count"] == 2
    assert crops_payload["source_object_key"] == "inputs/source.jpg"
    assert len(crops_payload["items"]) == 2
    for crop_item in crops_payload["items"]:
        assert crop_item["object_key"].startswith("workflow/crops/")
        assert crop_item["object_key"].endswith(".png")
        assert dataset_storage.resolve(crop_item["object_key"]).is_file()
        assert isinstance(crop_item["bbox_xyxy"], list)
        assert crop_item["crop_index"] >= 1


def test_repository_opencv_crop_export_node_defaults_to_memory_crops_with_memory_input(
    tmp_path: Path,
) -> None:
    """验证 crop-export 在 memory 输入且未显式 output_dir 时默认返回 memory crops。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    image_registry = ExecutionImageRegistry()
    source_image = image_registry.register_image_bytes(
        content=build_test_jpeg_bytes(),
        media_type="image/jpeg",
        width=64,
        height=64,
        created_by_node_id="fixture",
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-crop-memory-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Crop Memory Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="crop",
                node_type_id="custom.opencv.crop-export",
                parameters={"box_padding": 2, "max_crops": 2},
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="crop",
                target_port="image",
            ),
            WorkflowGraphInput(
                input_id="request_detections",
                display_name="Request Detections",
                payload_type_id="detections.v1",
                target_node_id="crop",
                target_port="detections",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="exported_crops",
                display_name="Exported Crops",
                payload_type_id="image-refs.v1",
                source_node_id="crop",
                source_port="crops",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": build_memory_image_payload(
                image_handle=source_image.image_handle,
                media_type="image/jpeg",
                width=64,
                height=64,
            ),
            "request_detections": {
                "items": [
                    {
                        "bbox_xyxy": [4, 4, 28, 28],
                        "score": 0.9,
                        "class_name": "part-a",
                    },
                    {
                        "bbox_xyxy": [20, 20, 52, 52],
                        "score": 0.8,
                        "class_name": "part-b",
                    },
                    {
                        "bbox_xyxy": [30, 30, 40, 40],
                        "score": 0.7,
                        "class_name": "part-c",
                    },
                ]
            },
        },
        execution_metadata={
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-crop-memory",
        },
    )

    crops_payload = execution_result.outputs["exported_crops"]
    assert crops_payload["count"] == 2
    assert crops_payload["source_image"]["transport_kind"] == "memory"
    assert "source_object_key" not in crops_payload
    assert len(crops_payload["items"]) == 2
    for crop_item in crops_payload["items"]:
        assert crop_item["transport_kind"] == "memory"
        assert crop_item["media_type"] == "image/png"
        assert isinstance(crop_item["bbox_xyxy"], list)
        assert crop_item["crop_index"] >= 1
        assert image_registry.read_bytes(str(crop_item["image_handle"])).startswith(b"\x89PNG\r\n\x1a\n")


def test_repository_opencv_node_pack_executes_contour_and_measure_nodes(
    tmp_path: Path,
) -> None:
    """验证仓库内置 OpenCV 节点包可以执行 contour 与 measure 节点。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/contours.png", _build_contour_test_png_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-measure-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Measure Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="contour",
                node_type_id="custom.opencv.contour",
                parameters={"threshold": 127, "min_area": 20, "retrieval_mode": "external"},
            ),
            WorkflowGraphNode(
                node_id="measure",
                node_type_id="custom.opencv.measure",
                parameters={"sort_by": "area", "descending": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-contour",
                source_node_id="input",
                source_port="image",
                target_node_id="contour",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-contour-measure",
                source_node_id="contour",
                source_port="contours",
                target_node_id="measure",
                target_port="contours",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="measurement_result",
                display_name="Measurement Result",
                payload_type_id="measurements.v1",
                source_node_id="measure",
                source_port="measurements",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/contours.png",
                "width": 96,
                "height": 96,
                "media_type": "image/png",
            }
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-measure",
        },
    )

    measurements_payload = execution_result.outputs["measurement_result"]
    assert measurements_payload["count"] == 2
    assert measurements_payload["summary"]["total_area"] > 0
    assert measurements_payload["items"][0]["area"] > measurements_payload["items"][1]["area"]
    assert measurements_payload["items"][0]["width"] >= measurements_payload["items"][1]["width"]
    assert [record.node_type_id for record in execution_result.node_records] == [
        "core.io.template-input.image",
        "custom.opencv.contour",
        "custom.opencv.measure",
    ]


def test_repository_opencv_contour_and_measure_nodes_accept_memory_image_payload(
    tmp_path: Path,
) -> None:
    """验证 contour 与 measure 节点链在 memory 输入下会保留 source_image。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    image_registry = ExecutionImageRegistry()
    source_image = image_registry.register_image_bytes(
        content=_build_contour_test_png_bytes(),
        media_type="image/png",
        width=96,
        height=96,
        created_by_node_id="fixture",
    )

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-measure-memory-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Measure Memory Pipeline",
        nodes=(
            WorkflowGraphNode(
                node_id="contour",
                node_type_id="custom.opencv.contour",
                parameters={"threshold": 127, "min_area": 20, "retrieval_mode": "external"},
            ),
            WorkflowGraphNode(
                node_id="measure",
                node_type_id="custom.opencv.measure",
                parameters={"sort_by": "area", "descending": True},
            ),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-contour-measure",
                source_node_id="contour",
                source_port="contours",
                target_node_id="measure",
                target_port="contours",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="contour",
                target_port="image",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="measurement_result",
                display_name="Measurement Result",
                payload_type_id="measurements.v1",
                source_node_id="measure",
                source_port="measurements",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": build_memory_image_payload(
                image_handle=source_image.image_handle,
                media_type="image/png",
                width=96,
                height=96,
            )
        },
        execution_metadata={
            "execution_image_registry": image_registry,
            "workflow_run_id": "opencv-measure-memory",
        },
    )

    measurements_payload = execution_result.outputs["measurement_result"]
    assert measurements_payload["count"] == 2
    assert measurements_payload["summary"]["total_area"] > 0
    assert measurements_payload["source_image"]["transport_kind"] == "memory"
    assert measurements_payload["source_image"]["image_handle"] == source_image.image_handle
    assert "source_object_key" not in measurements_payload


def test_repository_opencv_node_pack_executes_gallery_preview_node(
    tmp_path: Path,
) -> None:
    """验证仓库内置 OpenCV 节点包可以把裁剪图集合转换为 gallery preview。"""

    custom_nodes_root_dir = _get_repository_custom_nodes_root()
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    dataset_storage = _create_dataset_storage(tmp_path)
    dataset_storage.write_bytes("inputs/source.jpg", build_test_jpeg_bytes())

    runtime_registry_loader.refresh()
    executor = WorkflowGraphExecutor(registry=runtime_registry_loader.get_runtime_registry())
    template = WorkflowGraphTemplate(
        template_id="opencv-gallery-preview-pipeline",
        template_version="1.0.0",
        display_name="OpenCV Gallery Preview Pipeline",
        nodes=(
            WorkflowGraphNode(node_id="input", node_type_id="core.io.template-input.image"),
            WorkflowGraphNode(
                node_id="crop",
                node_type_id="custom.opencv.crop-export",
                parameters={"box_padding": 1, "max_crops": 2, "output_dir": "workflow/gallery"},
            ),
            WorkflowGraphNode(
                node_id="gallery",
                node_type_id="custom.opencv.gallery-preview",
                parameters={"title": "Crop Gallery", "max_items": 2},
            ),
            WorkflowGraphNode(node_id="response", node_type_id="core.output.http-response"),
        ),
        edges=(
            WorkflowGraphEdge(
                edge_id="edge-input-crop",
                source_node_id="input",
                source_port="image",
                target_node_id="crop",
                target_port="image",
            ),
            WorkflowGraphEdge(
                edge_id="edge-crop-gallery",
                source_node_id="crop",
                source_port="crops",
                target_node_id="gallery",
                target_port="images",
            ),
            WorkflowGraphEdge(
                edge_id="edge-gallery-response",
                source_node_id="gallery",
                source_port="body",
                target_node_id="response",
                target_port="body",
            ),
        ),
        template_inputs=(
            WorkflowGraphInput(
                input_id="request_image",
                display_name="Request Image",
                payload_type_id="image-ref.v1",
                target_node_id="input",
                target_port="payload",
            ),
            WorkflowGraphInput(
                input_id="request_detections",
                display_name="Request Detections",
                payload_type_id="detections.v1",
                target_node_id="crop",
                target_port="detections",
            ),
        ),
        template_outputs=(
            WorkflowGraphOutput(
                output_id="inspection_response",
                display_name="Inspection Response",
                payload_type_id="http-response.v1",
                source_node_id="response",
                source_port="response",
            ),
        ),
    )

    execution_result = executor.execute(
        template=template,
        input_values={
            "request_image": {
                "object_key": "inputs/source.jpg",
                "width": 64,
                "height": 64,
                "media_type": "image/jpeg",
            },
            "request_detections": {
                "items": [
                    {
                        "bbox_xyxy": [4, 4, 28, 28],
                        "score": 0.9,
                        "class_name": "part-a",
                    },
                    {
                        "bbox_xyxy": [20, 20, 52, 52],
                        "score": 0.8,
                        "class_name": "part-b",
                    }
                ]
            },
        },
        execution_metadata={
            "dataset_storage": dataset_storage,
            "workflow_run_id": "opencv-gallery",
        },
    )

    response_payload = execution_result.outputs["inspection_response"]
    assert response_payload["status_code"] == 200
    assert response_payload["body"]["type"] == "gallery-preview"
    assert response_payload["body"]["title"] == "Crop Gallery"
    assert response_payload["body"]["count"] == 2
    assert response_payload["body"]["total_count"] == 2
    assert response_payload["body"]["items"][0]["image"]["transport_kind"] == "inline-base64"
    assert response_payload["body"]["items"][0]["image"]["media_type"] == "image/png"
    assert response_payload["body"]["items"][0]["image"]["image_base64"]


def _create_executable_node_pack_fixture(tmp_path: Path) -> Path:
    """创建带 backend entrypoint 的最小可执行 node pack 目录。"""

    node_pack_dir = tmp_path / "custom_nodes" / "text-basic-nodes"
    backend_dir = node_pack_dir / "backend"
    workflow_dir = node_pack_dir / "workflow"
    backend_dir.mkdir(parents=True, exist_ok=True)
    workflow_dir.mkdir(parents=True, exist_ok=True)

    (node_pack_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "__init__.py").write_text("", encoding="utf-8")
    (backend_dir / "entry.py").write_text(
        """
def _normalize_handler(request):
    raw_payload = request.input_values[\"text\"]
    raw_text = str(raw_payload.get(\"value\") or \"\") if isinstance(raw_payload, dict) else str(raw_payload)
    return {\"text\": {\"value\": raw_text.strip()}}


def _uppercase_worker(request):
    raw_payload = request.input_values[\"text\"]
    raw_text = str(raw_payload.get(\"value\") or \"\") if isinstance(raw_payload, dict) else str(raw_payload)
    return {\"result\": {\"value\": raw_text.upper()}}


def register(context):
    context.register_python_callable(\"custom.text.normalize\", _normalize_handler)
    context.register_worker_task(\"custom.text.uppercase-worker\", _uppercase_worker)
""".strip()
        + "\n",
        encoding="utf-8",
    )

    manifest_payload = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "text.basic-nodes",
        "version": "0.1.0",
        "displayName": "Text Basic Nodes",
        "description": "测试用文本节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node"],
        "entrypoints": {"backend": "custom_nodes.text_basic_nodes.backend.entry:register"},
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
                "node_type_id": "custom.text.normalize",
                "display_name": "Normalize Text",
                "category": "utility.text",
                "description": "去除输入文本两端空白。",
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
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["text.normalize"],
                "runtime_requirements": {},
                "node_pack_id": "text.basic-nodes",
                "node_pack_version": "0.1.0",
            },
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.text.uppercase-worker",
                "display_name": "Uppercase Worker",
                "category": "worker.text",
                "description": "把文本转换成大写。",
                "implementation_kind": "custom-node",
                "runtime_kind": "worker-task",
                "input_ports": [
                    {
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "output_ports": [
                    {
                        "name": "result",
                        "display_name": "Result",
                        "payload_type_id": "text.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["text.uppercase"],
                "runtime_requirements": {},
                "node_pack_id": "text.basic-nodes",
                "node_pack_version": "0.1.0",
            },
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

    renamed_node_pack_dir = node_pack_dir.parent / "text_basic_nodes"
    node_pack_dir.rename(renamed_node_pack_dir)
    return tmp_path / "custom_nodes"


def _create_missing_entrypoint_node_pack_fixture(tmp_path: Path) -> Path:
    """创建缺少 backend entrypoint 的最小可执行 node pack 目录。"""

    node_pack_dir = tmp_path / "custom_nodes" / "missing-entrypoint-nodes"
    workflow_dir = node_pack_dir / "workflow"
    workflow_dir.mkdir(parents=True, exist_ok=True)
    manifest_payload = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "missing.entrypoint-nodes",
        "version": "0.1.0",
        "displayName": "Missing Entrypoint Nodes",
        "description": "测试用缺少 backend entrypoint 的节点包。",
        "category": "custom-node-pack",
        "capabilities": ["pipeline.node"],
        "entrypoints": {},
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
                "node_type_id": "custom.text.no-entrypoint",
                "display_name": "No Entrypoint",
                "category": "utility.text",
                "description": "测试缺少 backend entrypoint 的错误路径。",
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
                        "name": "text",
                        "display_name": "Text",
                        "payload_type_id": "text.v1",
                    }
                ],
                "parameter_schema": {"type": "object", "properties": {}},
                "capability_tags": ["text.no-entrypoint"],
                "runtime_requirements": {},
                "node_pack_id": "missing.entrypoint-nodes",
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


def _create_dataset_storage(tmp_path: Path) -> LocalDatasetStorage:
    """创建 workflow 运行时测试使用的本地文件存储。"""

    return LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files")))


def _install_fake_published_inference_gateway(
    monkeypatch: pytest.MonkeyPatch,
    calls: dict[str, object],
    *,
    class_name: str,
) -> None:
    """把 workflow runtime context 的 PublishedInferenceGateway 替换为测试实现。

    参数：
    - monkeypatch：pytest monkeypatch fixture。
    - calls：记录 gateway 调用的字典。
    - class_name：测试 detection 结果使用的类别名。
    """

    class _FakePublishedInferenceGateway:
        """记录 PublishedInferenceRequest 的测试 gateway。"""

        def infer(self, request):
            """记录请求并返回固定 detection。"""

            calls["published_inference_request"] = request
            calls["resolved_deployment_instance_id"] = request.deployment_instance_id
            calls["ensure_config"] = SimpleNamespace(deployment_instance_id=request.deployment_instance_id)
            if request.auto_start_process:
                calls["start_config"] = SimpleNamespace(deployment_instance_id=request.deployment_instance_id)
            calls["inference_kwargs"] = {
                "input_uri": request.image_payload.get("object_key"),
                "input_image_bytes": request.input_image_bytes,
                "input_image_payload": request.image_payload,
                "score_threshold": request.score_threshold,
                "save_result_image": request.save_result_image,
                "extra_options": request.extra_options,
            }
            return PublishedInferenceResult(
                deployment_instance_id=request.deployment_instance_id,
                detections=(
                    {
                        "bbox_xyxy": [4.0, 4.0, 24.0, 24.0],
                        "score": 0.97,
                        "class_id": 0,
                        "class_name": class_name,
                    },
                ),
                latency_ms=8.5,
                image_width=64,
                image_height=64,
                runtime_session_info={"backend_name": "fake"},
                metadata={"instance_id": "instance-1"},
            )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_published_inference_gateway",
        lambda self: _FakePublishedInferenceGateway(),
    )


def _get_repository_custom_nodes_root() -> Path:
    """返回仓库内置 custom_nodes 根目录。"""

    return Path(__file__).resolve().parents[1] / "custom_nodes"


def _build_contour_test_png_bytes() -> bytes:
    """构建带两个实心白色矩形的 contour 测试 PNG 图片。

    返回：
    - bytes：可被 OpenCV 稳定提取出两个 contour 的 PNG 图片字节。
    """

    import cv2
    import numpy as np

    image = np.zeros((96, 96, 3), dtype=np.uint8)
    cv2.rectangle(image, (8, 8), (32, 40), (255, 255, 255), thickness=-1)
    cv2.rectangle(image, (48, 20), (80, 72), (255, 255, 255), thickness=-1)
    success, encoded = cv2.imencode(".png", image)
    assert success is True
    return encoded.tobytes()


def _build_fake_deployment_view() -> SimpleNamespace:
    """构造 deployment lifecycle 节点测试使用的最小 deployment view。"""

    return SimpleNamespace(
        deployment_instance_id="deployment-instance-1",
        display_name="Demo Deployment",
    )


def _build_fake_process_config(*, instance_count: int) -> SimpleNamespace:
    """构造 deployment lifecycle 节点测试使用的最小 process_config。"""

    return SimpleNamespace(
        deployment_instance_id="deployment-instance-1",
        instance_count=instance_count,
        runtime_target=SimpleNamespace(runtime_artifact_storage_uri="artifacts/runtime/model.onnx"),
    )