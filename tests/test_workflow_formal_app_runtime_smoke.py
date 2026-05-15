"""正式 workflow app 当前运行时烟测。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path, PurePosixPath

import pytest

from backend.contracts.workflows.workflow_graph import FlowApplication, WorkflowGraphTemplate
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.deployments.yolox_deployment_service import (
    SqlAlchemyYoloXDeploymentService,
    YoloXDeploymentInstanceView,
)
from backend.service.application.errors import ServiceConfigurationError
from backend.service.domain.deployments.deployment_instance import DeploymentInstance
from backend.service.application.workflows.graph_executor import WorkflowNodeRuntimeRegistry
from backend.service.application.workflows.process_executor import (
    WorkflowApplicationExecutionRequest,
    WorkflowApplicationRuntimeExecutor,
)
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)
from backend.service.application.workflows.service_node_runtime import WorkflowServiceNodeRuntimeContext
from backend.service.application.workflows.workflow_service import LocalWorkflowJsonService
from tests.api_test_support import build_valid_test_png_bytes, create_test_runtime
from tests.test_workflow_barcode_protocol_nodes import _build_barcode_test_png_bytes


def test_yolox_deployment_sync_infer_health_app_runtime_smoke_executes_in_explicit_order(
    tmp_path: Path,
) -> None:
    """验证第二类正式 app 会按显式 edge 顺序完成 start、warmup、detect、health。"""

    executor, workflow_service, _, runtime_registry = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-sync-infer-health.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="yolox_deployment_sync_infer_health",
    )
    call_order: list[str] = []

    def _start_handler(request) -> dict[str, object]:
        call_order.append("start")
        assert request.input_values["request"] == _build_deployment_request_payload()
        return {
            "body": {
                "deployment_instance_id": "deployment-instance-1",
                "process_state": "running",
            }
        }

    def _warmup_handler(request) -> dict[str, object]:
        call_order.append("warmup")
        assert request.input_values["request"] == _build_deployment_request_payload()
        assert request.input_values["dependency"]["deployment_instance_id"] == "deployment-instance-1"
        return {
            "body": {
                "deployment_instance_id": "deployment-instance-1",
                "process_state": "running",
                "warmed_instance_count": 1,
            }
        }

    def _detect_handler(request) -> dict[str, object]:
        call_order.append("detect")
        assert request.input_values["request"] == _build_deployment_request_payload()
        assert request.input_values["dependency"]["warmed_instance_count"] == 1
        return {
            "detections": {
                "items": [
                    {
                        "bbox_xyxy": [0.0, 0.0, 1.0, 1.0],
                        "score": 0.97,
                        "label": "qr",
                        "class_name": "qr",
                    }
                ]
            }
        }

    def _health_handler(request) -> dict[str, object]:
        call_order.append("health")
        assert request.input_values["request"] == _build_deployment_request_payload()
        assert request.input_values["dependency"]["items"][0]["bbox_xyxy"] == [0.0, 0.0, 1.0, 1.0]
        return {
            "body": {
                "deployment_instance_id": "deployment-instance-1",
                "process_state": "running",
                "healthy_instance_count": 1,
                "warmed_instance_count": 1,
            }
        }

    _override_python_handler(runtime_registry, "core.service.yolox-deployment.start", _start_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-deployment.warmup", _warmup_handler)
    _override_worker_task_handler(runtime_registry, "core.model.yolox-detection", _detect_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-deployment.health", _health_handler)

    execution_result = executor.execute(
        WorkflowApplicationExecutionRequest(
            project_id="project-1",
            application_id=application.application_id,
            input_bindings={
                "request_image": _build_image_base64_payload(build_valid_test_png_bytes()),
                "deployment_request": _build_deployment_request_payload(),
            },
            execution_metadata={"scenario": "smoke-sync-infer-health"},
        )
    )

    assert call_order == ["start", "warmup", "detect", "health"]
    assert execution_result.outputs["start_body"]["process_state"] == "running"
    assert execution_result.outputs["warmup_body"]["warmed_instance_count"] == 1
    assert execution_result.outputs["detections"]["items"][0]["class_name"] == "qr"
    assert execution_result.outputs["health_body"]["healthy_instance_count"] == 1


def test_opencv_process_save_image_app_runtime_smoke_saves_unique_object_key(tmp_path: Path) -> None:
    """验证第五类正式 app 会真实保存图片，并生成带 workflow_run_id 与时间戳的 object key。"""

    executor, workflow_service, dataset_storage, _ = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-opencv-save-image.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="opencv_process_save_image",
    )

    execution_result = executor.execute(
        WorkflowApplicationExecutionRequest(
            project_id="project-1",
            application_id=application.application_id,
            input_bindings={"request_image": _build_image_base64_payload(build_valid_test_png_bytes())},
            execution_metadata={"scenario": "smoke-opencv-save-image"},
        )
    )

    response_payload = execution_result.outputs["http_response"]
    response_body = response_payload["body"]
    image_payload = response_body["image"]
    object_key = image_payload["object_key"]
    object_key_parts = PurePosixPath(object_key).parts

    assert response_payload["status_code"] == 200
    assert response_body["title"] == "Saved Edge Image"
    assert response_body["type"] == "image-preview"
    assert image_payload["transport_kind"] == "storage-ref"
    assert object_key_parts[:6] == (
        "projects",
        "project-1",
        "results",
        "workflow-applications",
        "opencv-process-save-image-app",
        "runs",
    )
    assert len(object_key_parts) == 8
    assert re.match(r"^[0-9a-f]{32}$", object_key_parts[6]) is not None
    assert re.match(r"^save_image-\d{8}T\d{12}Z\.png$", object_key_parts[7]) is not None
    assert dataset_storage.resolve(object_key).is_file()


def test_yolox_deployment_infer_opencv_health_app_runtime_smoke_returns_health_summary(
    tmp_path: Path,
) -> None:
    """验证第四类正式 app 会返回叠加图和 deployment health 摘要。"""

    executor, workflow_service, _, runtime_registry = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-infer-opencv-health.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="yolox_deployment_infer_opencv_health",
    )

    def _health_handler(request) -> dict[str, object]:
        assert request.input_values["request"] == _build_deployment_request_payload()
        return {
            "body": {
                "deployment_instance_id": "deployment-instance-1",
                "process_state": "running",
                "healthy_instance_count": 1,
                "warmed_instance_count": 1,
                "keep_warm": True,
            }
        }

    def _detect_handler(request) -> dict[str, object]:
        assert request.input_values["request"] == _build_deployment_request_payload()
        return {
            "detections": {
                "items": [
                    {
                        "bbox_xyxy": [0.0, 0.0, 1.0, 1.0],
                        "score": 0.95,
                        "label": "box",
                        "class_name": "box",
                    }
                ]
            }
        }

    _override_python_handler(runtime_registry, "core.service.yolox-deployment.health", _health_handler)
    _override_worker_task_handler(runtime_registry, "core.model.yolox-detection", _detect_handler)

    execution_result = executor.execute(
        WorkflowApplicationExecutionRequest(
            project_id="project-1",
            application_id=application.application_id,
            input_bindings={
                "request_image": _build_image_base64_payload(build_valid_test_png_bytes()),
                "deployment_request": _build_deployment_request_payload(),
            },
            execution_metadata={"scenario": "smoke-infer-opencv-health"},
        )
    )

    response_payload = execution_result.outputs["http_response"]
    response_body = response_payload["body"]
    response_data = response_body["data"]

    assert response_payload["status_code"] == 200
    assert response_body["code"] == 0
    assert response_body["message"] == "ok"
    assert response_data["health"]["deployment_instance_id"] == "deployment-instance-1"
    assert response_data["health"]["process_state"] == "running"
    assert response_data["health"]["healthy_instance_count"] == 1
    assert response_data["annotated_image"]["transport_kind"] == "inline-base64"
    assert response_data["annotated_image"]["media_type"] == "image/png"


def test_yolox_deployment_infer_opencv_health_zeromq_app_runtime_smoke_returns_detections_and_image(
    tmp_path: Path,
) -> None:
    """验证第六类正式 app 会返回检测框列表和绘制后的 inline-base64 图片。"""

    executor, workflow_service, _, runtime_registry = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-infer-opencv-health-zeromq.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="yolox_deployment_infer_opencv_health_zeromq",
    )

    def _health_handler(request) -> dict[str, object]:
        assert request.input_values["request"] == _build_deployment_request_payload()
        return {
            "body": {
                "deployment_instance_id": "deployment-instance-1",
                "process_state": "running",
                "healthy_instance_count": 1,
                "warmed_instance_count": 1,
                "keep_warm": True,
            }
        }

    def _detect_handler(request) -> dict[str, object]:
        assert request.input_values["request"] == _build_deployment_request_payload()
        return {
            "detections": {
                "items": [
                    {
                        "bbox_xyxy": [0.0, 0.0, 1.0, 1.0],
                        "score": 0.95,
                        "label": "box-a",
                        "class_name": "box-a",
                    },
                    {
                        "bbox_xyxy": [1.0, 1.0, 2.0, 2.0],
                        "score": 0.85,
                        "label": "box-b",
                        "class_name": "box-b",
                    },
                ]
            }
        }

    _override_python_handler(runtime_registry, "core.service.yolox-deployment.health", _health_handler)
    _override_worker_task_handler(runtime_registry, "core.model.yolox-detection", _detect_handler)

    execution_result = executor.execute(
        WorkflowApplicationExecutionRequest(
            project_id="project-1",
            application_id=application.application_id,
            input_bindings={
                "request_image_base64": _build_image_base64_payload(build_valid_test_png_bytes()),
                "deployment_request": _build_deployment_request_payload(),
            },
            execution_metadata={"scenario": "smoke-infer-opencv-health-zeromq"},
        )
    )

    response_payload = execution_result.outputs["http_response"]
    response_body = response_payload["body"]
    response_data = response_body["data"]

    assert response_payload["status_code"] == 200
    assert response_body["code"] == 0
    assert response_body["message"] == "ok"
    assert response_data["health"]["deployment_instance_id"] == "deployment-instance-1"
    assert response_data["health"]["process_state"] == "running"
    assert len(response_data["detections"]) == 2
    assert response_data["detections"][0]["bbox_xyxy"] == [0.0, 0.0, 1.0, 1.0]
    assert response_data["detections"][1]["class_name"] == "box-b"
    assert response_data["annotated_image"]["transport_kind"] == "inline-base64"
    assert response_data["annotated_image"]["media_type"] == "image/png"
    assert isinstance(response_data["annotated_image"]["image_base64"], str)
    assert response_data["annotated_image"]["image_base64"]


def test_yolox_deployment_qr_crop_remap_app_runtime_smoke_decodes_qr_from_real_crop(
    tmp_path: Path,
) -> None:
    """验证第三类正式 app 会真实走 crop 导出和 QR remap 解码链。"""

    executor, workflow_service, _, runtime_registry = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-qr-crop-remap.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="yolox_deployment_qr_crop_remap",
    )

    def _detect_handler(request) -> dict[str, object]:
        assert request.input_values["request"] == _build_deployment_request_payload()
        return {
            "detections": {
                "items": [
                    {
                        "bbox_xyxy": [0.0, 0.0, 999.0, 999.0],
                        "score": 0.99,
                        "label": "qr",
                        "class_name": "qr",
                    }
                ]
            }
        }

    _override_worker_task_handler(runtime_registry, "core.model.yolox-detection", _detect_handler)

    execution_result = executor.execute(
        WorkflowApplicationExecutionRequest(
            project_id="project-1",
            application_id=application.application_id,
            input_bindings={
                "deployment_request": _build_deployment_request_payload(),
                "request_image": _build_image_base64_payload(
                    _build_barcode_test_png_bytes(
                        payload_text="qr-app-smoke",
                        barcode_format_name="QRCode",
                    )
                )
            },
            execution_metadata={"scenario": "smoke-qr-crop-remap"},
        )
    )

    response_payload = execution_result.outputs["http_response"]
    response_body = response_payload["body"]
    response_data = response_body["data"]

    assert response_payload["status_code"] == 200
    assert response_body["code"] == 0
    assert response_body["message"] == "decoded"
    assert response_data["barcode_summary"]["count"] >= 1
    assert "qr-app-smoke" in response_data["barcode_summary"]["texts"]
    assert response_data["annotated_image"]["transport_kind"] == "inline-base64"


def test_yolox_end_to_end_qr_crop_remap_app_runtime_smoke_returns_slim_stage_summaries_and_cleans_up_created_deployment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证第一类正式 app 会返回裁剪后的 stage 摘要，并清理本次临时 deployment。"""

    executor, workflow_service, _, runtime_registry = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-end-to-end.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="yolox_end_to_end_qr_crop_remap",
    )
    waited_task_ids: list[str] = []
    tracked_deployment_service = _install_tracked_deployment_service(
        monkeypatch=monkeypatch,
        executor=executor,
    )

    def _submit_import_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        assert request_value["format_type"] == "coco"
        return {"body": {"task_id": "task-import-1", "status": "received"}}

    def _submit_export_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        assert request_value["format_id"] == "coco-detection-v1"
        return {
            "body": {
                "task_id": "task-export-1",
                "status": "queued",
                "dataset_export_id": "dataset-export-1",
            }
        }

    def _submit_training_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        assert request_value["model_scale"] == "s"
        assert request_value["warm_start_model_version_id"] == "model-version-pretrained-yolox-s"
        return {"body": {"task_id": "task-training-1", "status": "queued"}}

    def _submit_evaluation_handler(request) -> dict[str, object]:
        return {"body": {"task_id": "task-evaluation-1", "status": "queued"}}

    def _submit_conversion_handler(request) -> dict[str, object]:
        return {"body": {"task_id": "task-conversion-1", "status": "queued"}}

    def _task_wait_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        task_id = str(request_value["task_id"])
        waited_task_ids.append(task_id)
        assert request_value["include_events"] is False
        task_payloads = {
            "task-import-1": {
                "task_id": "task-import-1",
                "state": "succeeded",
                "result": {
                    "dataset_version_id": "dataset-version-1",
                },
                    "task_spec": {"dataset_id": "dataset-1"},
                "error_message": None,
            },
            "task-export-1": {
                "task_id": "task-export-1",
                "state": "succeeded",
                "result": {"export_manifest_object_key": "exports/dataset-export-1/manifest.json"},
                "error_message": None,
            },
            "task-training-1": {
                "task_id": "task-training-1",
                "state": "succeeded",
                "result": {"model_version_id": "model-version-1"},
                "error_message": None,
            },
            "task-evaluation-1": {
                "task_id": "task-evaluation-1",
                "state": "succeeded",
                "result": {"metrics": {"mAP": 0.91}},
                "error_message": None,
            },
            "task-conversion-1": {
                "task_id": "task-conversion-1",
                "state": "succeeded",
                "result": {
                    "model_build_id": "model-build-onnx-1",
                    "builds": [
                        {"model_build_id": "model-build-onnx-1", "build_format": "onnx"},
                        {
                            "model_build_id": "model-build-optimized-1",
                            "build_format": "onnx-optimized",
                        },
                        {
                            "model_build_id": "model-build-tensorrt-1",
                            "build_format": "tensorrt-engine",
                        },
                    ],
                },
                "error_message": None,
            },
        }
        return {"body": task_payloads[task_id]}

    def _detect_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        assert request_value["deployment_instance_id"] == "deployment-instance-1"
        return {
            "detections": {
                "items": [
                    {
                        "bbox_xyxy": [0.0, 0.0, 999.0, 999.0],
                        "score": 0.99,
                        "label": "qr",
                        "class_name": "qr",
                    }
                ]
            }
        }

    _override_python_handler(runtime_registry, "core.service.dataset-import.submit", _submit_import_handler)
    _override_python_handler(runtime_registry, "core.service.dataset-export.submit", _submit_export_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-training.submit", _submit_training_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-evaluation.submit", _submit_evaluation_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-conversion.submit", _submit_conversion_handler)
    _override_python_handler(runtime_registry, "core.service.task.wait", _task_wait_handler)
    _override_worker_task_handler(runtime_registry, "core.model.yolox-detection", _detect_handler)

    execution_result = executor.execute(
        WorkflowApplicationExecutionRequest(
            project_id="project-1",
            application_id=application.application_id,
            input_bindings={
                "import_request_payload": {
                    "value": {
                        "project_id": "project-1",
                        "dataset_id": "dataset-1",
                        "format_type": "coco",
                    }
                },
                "request_package": {
                    "package_file_name": "demo-dataset.zip",
                    "package_bytes": b"demo-zip",
                },
                "export_request_payload": {"value": {"project_id": "project-1", "format_id": "coco-detection-v1"}},
                "training_request_payload": {
                    "value": {
                        "project_id": "project-1",
                        "recipe_id": "recipe-1",
                        "model_scale": "s",
                    }
                },
                "evaluation_request_payload": {"value": {"project_id": "project-1", "score_threshold": 0.25}},
                "conversion_request_payload": {
                    "value": {
                        "project_id": "project-1",
                        "target_formats": ["tensorrt-engine"],
                        "extra_options": {"tensorrt_engine_precision": "fp16"},
                    }
                },
                "deployment_request_payload": {
                    "value": {
                        "project_id": "project-1",
                        "runtime_backend": "tensorrt",
                        "device_name": "cuda",
                        "runtime_precision": "fp16",
                        "instance_count": 3,
                        "keep_warm_enabled": True,
                    }
                },
                "inference_request_payload": {"value": {"score_threshold": 0.3}},
                "request_image": _build_image_base64_payload(
                    _build_barcode_test_png_bytes(
                        payload_text="qr-end-to-end-smoke",
                        barcode_format_name="QRCode",
                    )
                ),
            },
            execution_metadata={"scenario": "smoke-end-to-end"},
        )
    )

    response_body = execution_result.outputs["response_body"]
    response_data = response_body["data"]
    stages = response_data["stages"]

    assert response_body["code"] == 0
    assert response_body["message"] == "completed"
    assert waited_task_ids == [
        "task-import-1",
        "task-export-1",
        "task-training-1",
        "task-evaluation-1",
        "task-conversion-1",
    ]
    assert response_data["artifact_ids"] == {
        "dataset_id": "dataset-1",
        "dataset_version_id": "dataset-version-1",
        "dataset_export_id": "dataset-export-1",
        "model_version_id": "model-version-1",
        "model_build_id": "model-build-tensorrt-1",
        "deployment_instance_id": "deployment-instance-1",
    }
    for stage_name in [
        "import_task",
        "export_task",
        "training_task",
        "evaluation_task",
        "conversion_task",
    ]:
        assert set(stages[stage_name]) == {"task_id", "state", "result", "error_message"}
        assert "events" not in stages[stage_name]
    assert stages["training_task"]["result"]["model_version_id"] == "model-version-1"
    assert stages["conversion_task"]["result"]["model_build_id"] == "model-build-onnx-1"
    assert stages["conversion_task"]["result"]["builds"][-1]["model_build_id"] == "model-build-tensorrt-1"
    assert stages["deployment"]["deployment_instance_id"] == "deployment-instance-1"
    assert response_data["barcode_summary"]["count"] >= 1
    assert "qr-end-to-end-smoke" in response_data["barcode_summary"]["texts"]
    assert tracked_deployment_service.create_requests[0]["request"].model_build_id == "model-build-tensorrt-1"
    assert tracked_deployment_service.deleted_deployment_ids == ["deployment-instance-1"]
    assert tracked_deployment_service.list_saved_deployment_ids(project_id="project-1") == ()


def test_yolox_end_to_end_qr_crop_remap_app_runtime_cleans_up_created_deployment_after_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证第一类正式 app 即使在推理阶段失败，也会清理本次临时 deployment。"""

    executor, workflow_service, _, runtime_registry = _build_example_runtime(
        tmp_path,
        database_name="workflow-formal-end-to-end-failure.db",
    )
    _, application = _save_example_documents(
        workflow_service,
        example_name="yolox_end_to_end_qr_crop_remap",
    )
    tracked_deployment_service = _install_tracked_deployment_service(
        monkeypatch=monkeypatch,
        executor=executor,
    )

    _install_end_to_end_submit_chain_runtime_overrides(runtime_registry)

    def _failing_detect_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        assert request_value["deployment_instance_id"] == "deployment-instance-1"
        raise RuntimeError("forced detect failure")

    _override_worker_task_handler(runtime_registry, "core.model.yolox-detection", _failing_detect_handler)

    with pytest.raises(ServiceConfigurationError):
        executor.execute(
            WorkflowApplicationExecutionRequest(
                project_id="project-1",
                application_id=application.application_id,
                input_bindings=_build_end_to_end_input_bindings(),
                execution_metadata={"scenario": "smoke-end-to-end-failure"},
            )
        )

    assert tracked_deployment_service.deleted_deployment_ids == ["deployment-instance-1"]
    assert tracked_deployment_service.list_saved_deployment_ids(project_id="project-1") == ()


def _build_example_runtime(
    tmp_path: Path,
    *,
    database_name: str,
) -> tuple[
    WorkflowApplicationRuntimeExecutor,
    LocalWorkflowJsonService,
    object,
    WorkflowNodeRuntimeRegistry,
]:
    """构造正式 workflow app 烟测共用的当前运行时执行器。"""

    session_factory, dataset_storage, queue_backend = create_test_runtime(
        tmp_path,
        database_name=database_name,
    )
    custom_nodes_root_dir = Path(__file__).resolve().parents[1] / "custom_nodes"
    node_pack_loader = LocalNodePackLoader(custom_nodes_root_dir)
    node_pack_loader.refresh()
    node_catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    runtime_registry_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=node_catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_registry_loader.refresh()
    workflow_service = LocalWorkflowJsonService(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
    )
    runtime_context = WorkflowServiceNodeRuntimeContext(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    executor = WorkflowApplicationRuntimeExecutor(
        dataset_storage=dataset_storage,
        node_catalog_registry=node_catalog_registry,
        runtime_registry=runtime_registry_loader.get_runtime_registry(),
        runtime_context=runtime_context,
    )
    return executor, workflow_service, dataset_storage, runtime_registry_loader.get_runtime_registry()


def _save_example_documents(
    workflow_service: LocalWorkflowJsonService,
    *,
    example_name: str,
) -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """保存指定正式示例的 template 与 application。"""

    template, application = _load_example_documents(example_name)
    workflow_service.save_template(project_id="project-1", template=template)
    workflow_service.save_application(project_id="project-1", application=application)
    return template, application


def _load_example_documents(example_name: str) -> tuple[WorkflowGraphTemplate, FlowApplication]:
    """读取指定名称的正式示例 template 与 application。"""

    example_dir = Path(__file__).resolve().parents[1] / "docs" / "examples" / "workflows"
    template = WorkflowGraphTemplate.model_validate(
        json.loads((example_dir / f"{example_name}.template.json").read_text(encoding="utf-8"))
    )
    application = FlowApplication.model_validate(
        json.loads((example_dir / f"{example_name}.application.json").read_text(encoding="utf-8"))
    )
    return template, application


def _override_python_handler(
    runtime_registry: WorkflowNodeRuntimeRegistry,
    node_type_id: str,
    handler,
) -> None:
    """替换指定 python-callable 节点的运行时 handler。"""

    runtime_registry.register_python_callable(
        runtime_registry.get_node_definition(node_type_id),
        handler,
    )


def _override_worker_task_handler(
    runtime_registry: WorkflowNodeRuntimeRegistry,
    node_type_id: str,
    handler,
) -> None:
    """替换指定 worker-task 节点的运行时 handler。"""

    runtime_registry.register_worker_task(
        runtime_registry.get_node_definition(node_type_id),
        handler,
    )


def _build_image_base64_payload(image_bytes: bytes) -> dict[str, object]:
    """把图片字节编码成 image-base64.v1 输入 payload。"""

    return {
        "image_base64": base64.b64encode(image_bytes).decode("ascii"),
        "media_type": "image/png",
    }


def _build_deployment_request_payload() -> dict[str, object]:
    """构造复用发布模型的 value.v1 输入 payload。"""

    return {"value": {"deployment_instance_id": "deployment-instance-1"}}


def _build_end_to_end_input_bindings() -> dict[str, object]:
    """构造第一类正式 app 烟测共用的输入绑定。"""

    return {
        "import_request_payload": {
            "value": {
                "project_id": "project-1",
                "dataset_id": "dataset-1",
                "format_type": "coco",
            }
        },
        "request_package": {
            "package_file_name": "demo-dataset.zip",
            "package_bytes": b"demo-zip",
        },
        "export_request_payload": {"value": {"project_id": "project-1", "format_id": "coco-detection-v1"}},
        "training_request_payload": {
            "value": {
                "project_id": "project-1",
                "recipe_id": "recipe-1",
                "model_scale": "s",
            }
        },
        "evaluation_request_payload": {"value": {"project_id": "project-1", "score_threshold": 0.25}},
        "conversion_request_payload": {
            "value": {
                "project_id": "project-1",
                "target_formats": ["tensorrt-engine"],
                "extra_options": {"tensorrt_engine_precision": "fp16"},
            }
        },
        "deployment_request_payload": {
            "value": {
                "project_id": "project-1",
                "runtime_backend": "tensorrt",
                "device_name": "cuda",
                "runtime_precision": "fp16",
                "instance_count": 3,
                "keep_warm_enabled": True,
            }
        },
        "inference_request_payload": {"value": {"score_threshold": 0.3}},
        "request_image": _build_image_base64_payload(
            _build_barcode_test_png_bytes(
                payload_text="qr-end-to-end-smoke",
                barcode_format_name="QRCode",
            )
        ),
    }


def _install_end_to_end_submit_chain_runtime_overrides(
    runtime_registry: WorkflowNodeRuntimeRegistry,
) -> list[str]:
    """安装第一类正式 app 上游 submit/wait 链的 fake runtime handler。"""

    waited_task_ids: list[str] = []

    def _submit_import_handler(request) -> dict[str, object]:
        return {"body": {"task_id": "task-import-1", "status": "received"}}

    def _submit_export_handler(request) -> dict[str, object]:
        return {
            "body": {
                "task_id": "task-export-1",
                "status": "queued",
                "dataset_export_id": "dataset-export-1",
            }
        }

    def _submit_training_handler(request) -> dict[str, object]:
        return {"body": {"task_id": "task-training-1", "status": "queued"}}

    def _submit_evaluation_handler(request) -> dict[str, object]:
        return {"body": {"task_id": "task-evaluation-1", "status": "queued"}}

    def _submit_conversion_handler(request) -> dict[str, object]:
        return {"body": {"task_id": "task-conversion-1", "status": "queued"}}

    def _task_wait_handler(request) -> dict[str, object]:
        request_payload = request.input_values.get("request")
        request_value = request_payload.get("value") if isinstance(request_payload, dict) else None
        assert isinstance(request_value, dict)
        task_id = str(request_value["task_id"])
        waited_task_ids.append(task_id)
        assert request_value["include_events"] is False
        task_payloads = {
            "task-import-1": {
                "task_id": "task-import-1",
                "state": "succeeded",
                "result": {
                    "dataset_version_id": "dataset-version-1",
                },
                    "task_spec": {"dataset_id": "dataset-1"},
                "error_message": None,
            },
            "task-export-1": {
                "task_id": "task-export-1",
                "state": "succeeded",
                "result": {"export_manifest_object_key": "exports/dataset-export-1/manifest.json"},
                "error_message": None,
            },
            "task-training-1": {
                "task_id": "task-training-1",
                "state": "succeeded",
                "result": {"model_version_id": "model-version-1"},
                "error_message": None,
            },
            "task-evaluation-1": {
                "task_id": "task-evaluation-1",
                "state": "succeeded",
                "result": {"metrics": {"mAP": 0.91}},
                "error_message": None,
            },
            "task-conversion-1": {
                "task_id": "task-conversion-1",
                "state": "succeeded",
                "result": {
                    "model_build_id": "model-build-onnx-1",
                    "builds": [
                        {"model_build_id": "model-build-onnx-1", "build_format": "onnx"},
                        {
                            "model_build_id": "model-build-optimized-1",
                            "build_format": "onnx-optimized",
                        },
                        {
                            "model_build_id": "model-build-tensorrt-1",
                            "build_format": "tensorrt-engine",
                        },
                    ],
                },
                "error_message": None,
            },
        }
        return {"body": task_payloads[task_id]}

    _override_python_handler(runtime_registry, "core.service.dataset-import.submit", _submit_import_handler)
    _override_python_handler(runtime_registry, "core.service.dataset-export.submit", _submit_export_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-training.submit", _submit_training_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-evaluation.submit", _submit_evaluation_handler)
    _override_python_handler(runtime_registry, "core.service.yolox-conversion.submit", _submit_conversion_handler)
    _override_python_handler(runtime_registry, "core.service.task.wait", _task_wait_handler)
    return waited_task_ids


def _install_tracked_deployment_service(
    *,
    monkeypatch: pytest.MonkeyPatch,
    executor: WorkflowApplicationRuntimeExecutor,
) -> "_TrackedDeploymentService":
    """安装一个可记录 create/delete 且会真实落库/删库的 deployment service。"""

    tracked_service = _TrackedDeploymentService(executor.runtime_context)
    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self: tracked_service,
    )
    return tracked_service


class _TrackedDeploymentService(SqlAlchemyYoloXDeploymentService):
    """用于 end-to-end cleanup 烟测的可跟踪 deployment service。"""

    def __init__(self, runtime_context: WorkflowServiceNodeRuntimeContext) -> None:
        """初始化可跟踪 deployment service。

        参数：
        - runtime_context：当前 workflow service node 运行时上下文。
        """

        super().__init__(
            session_factory=runtime_context.session_factory,
            dataset_storage=runtime_context.dataset_storage,
        )
        self.create_requests: list[dict[str, object]] = []
        self.deleted_deployment_ids: list[str] = []

    def create_deployment_instance(self, request, *, created_by: str | None):
        """保存一个最小 DeploymentInstance 记录，并返回固定 view。"""

        self.create_requests.append({"request": request, "created_by": created_by})
        deployment_instance = DeploymentInstance(
            deployment_instance_id="deployment-instance-1",
            project_id=request.project_id,
            model_id="model-1",
            model_version_id=request.model_version_id or "model-version-1",
            model_build_id=request.model_build_id or "model-build-tensorrt-1",
            runtime_backend=request.runtime_backend or "tensorrt",
            device_name=request.device_name or "cpu",
            instance_count=request.instance_count,
            status="active",
            display_name=request.display_name or "demo-deployment",
            created_at="2026-05-09T00:00:00+00:00",
            updated_at="2026-05-09T00:00:00+00:00",
            created_by=created_by,
            metadata={},
        )
        with self._open_unit_of_work() as unit_of_work:
            unit_of_work.deployments.save_deployment_instance(deployment_instance)
            unit_of_work.commit()
        return YoloXDeploymentInstanceView(
            deployment_instance_id=deployment_instance.deployment_instance_id,
            project_id=deployment_instance.project_id,
            display_name=deployment_instance.display_name,
            status=deployment_instance.status,
            model_id=deployment_instance.model_id,
            model_version_id=deployment_instance.model_version_id,
            model_build_id=deployment_instance.model_build_id,
            model_name="demo-model",
            model_scale="s",
            task_type="detection",
            source_kind="model-build",
            runtime_profile_id=None,
            runtime_backend=deployment_instance.runtime_backend,
            device_name=deployment_instance.device_name,
            runtime_precision=request.runtime_precision or "fp16",
            runtime_execution_mode=(
                f"{deployment_instance.runtime_backend}:{request.runtime_precision or 'fp16'}:"
                f"{deployment_instance.device_name}"
            ),
            instance_count=deployment_instance.instance_count,
            input_size=(640, 640),
            labels=("qr",),
            created_at=deployment_instance.created_at,
            updated_at=deployment_instance.updated_at,
            created_by=deployment_instance.created_by,
            metadata={},
        )

    def delete_deployment_instance(self, deployment_instance_id: str) -> bool:
        """记录 delete 调用，并委托基类执行真实删库。"""

        self.deleted_deployment_ids.append(deployment_instance_id)
        return super().delete_deployment_instance(deployment_instance_id)

    def list_saved_deployment_ids(self, *, project_id: str) -> tuple[str, ...]:
        """列出当前测试数据库里剩余的 DeploymentInstance id。"""

        with self._open_unit_of_work() as unit_of_work:
            return tuple(
                item.deployment_instance_id
                for item in unit_of_work.deployments.list_deployment_instances(project_id)
            )