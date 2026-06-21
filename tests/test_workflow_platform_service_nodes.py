"""workflow 平台 service node 定向测试。"""

from __future__ import annotations

from types import SimpleNamespace

from backend.nodes.core_nodes import (
    model_conversion_submit as conversion_node,
    model_deployment_create as deployment_create_node,
    model_evaluation_submit as evaluation_node,
    model_inference_submit as inference_node,
    model_training_submit as training_node,
    model_validation_session_create as validation_node,
)
from backend.service.application.deployments.classification_deployment_service import (
    ClassificationDeploymentInstanceCreateRequest,
)
from backend.service.application.models.segmentation_inference_task_service import (
    SegmentationInferenceTaskRequest,
)
from backend.service.application.models.validation.pose_session_service import (
    PoseValidationSessionCreateRequest,
)
from backend.service.application.models.yolo_primary_classification_evaluation_task_service import (
    YoloPrimaryClassificationEvaluationTaskRequest,
)
from backend.service.application.models.yolo11_classification_training_service import (
    Yolo11ClassificationTrainingTaskRequest,
)
from backend.service.application.models.yolo11_segmentation_training_service import (
    Yolo11SegmentationTrainingTaskRequest,
)
from backend.service.application.models.yolo11_pose_training_service import (
    Yolo11PoseTrainingTaskRequest,
)
from backend.service.application.models.yolo11_obb_training_service import (
    Yolo11ObbTrainingTaskRequest,
)
from backend.service.application.models.training.rfdetr_detection_task_service import (
    RfdetrTrainingTaskRequest,
)
from backend.service.application.conversions.yolo_model_conversion_task_service import (
    YoloConversionTaskRequest,
)
from backend.service.application.conversions.rfdetr_conversion_task_service import (
    RfdetrConversionTaskRequest,
)
from backend.service.application.workflows.graph_executor import (
    WorkflowNodeExecutionRequest,
)
from backend.service.application.workflows.service_node_runtime import (
    WorkflowServiceNodeRuntimeContext,
)


def test_training_service_node_routes_to_platform_training_service(
    monkeypatch,
) -> None:
    """显式 task_type/model_type 时，训练节点应走平台 training service。"""

    captured: dict[str, object] = {}

    class _FakeTrainingService:
        def submit_training_task(self, request, *, created_by=None, **kwargs):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["submit_kwargs"] = kwargs
            return {"task_id": "task-training-1", "status": "queued"}

    def _build_training_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeTrainingService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_training_task_service",
        _build_training_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="training-node",
        node_definition=training_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "classification",
            "model_type": "yolo11",
            "project_id": "project-1",
            "dataset_export_id": "dataset-export-1",
            "recipe_id": "recipe-1",
            "model_scale": "nano",
            "output_model_name": "classification-model",
            "max_epochs": 5,
            "display_name": "classification training",
            "created_by": "workflow-user",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = training_node._model_training_submit_handler(request)

    assert result["body"]["task_id"] == "task-training-1"
    assert captured["service_kwargs"] == {
        "task_type": "classification",
        "model_type": "yolo11",
    }
    assert isinstance(captured["request"], Yolo11ClassificationTrainingTaskRequest)
    assert captured["request"].display_name == "classification training"
    assert captured["request"].model_type == "yolo11"
    assert captured["created_by"] == "workflow-user"
    assert captured["submit_kwargs"] == {}


def test_training_service_node_uses_yolo11_segmentation_request(
    monkeypatch,
) -> None:
    """YOLO11 segmentation 训练节点应构造模型专属请求。"""

    captured: dict[str, object] = {}

    class _FakeTrainingService:
        def submit_training_task(self, request, *, created_by=None, **kwargs):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["submit_kwargs"] = kwargs
            return {"task_id": "task-segmentation-1", "status": "queued"}

    def _build_training_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeTrainingService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_training_task_service",
        _build_training_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="segmentation-training-node",
        node_definition=training_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "segmentation",
            "model_type": "yolo11",
            "project_id": "project-1",
            "dataset_export_id": "dataset-export-1",
            "recipe_id": "recipe-1",
            "model_scale": "nano",
            "output_model_name": "segmentation-model",
            "max_epochs": 5,
            "display_name": "segmentation training",
            "created_by": "workflow-user",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = training_node._model_training_submit_handler(request)

    assert result["body"]["task_id"] == "task-segmentation-1"
    assert captured["service_kwargs"] == {
        "task_type": "segmentation",
        "model_type": "yolo11",
    }
    assert isinstance(captured["request"], Yolo11SegmentationTrainingTaskRequest)
    assert captured["request"].display_name == "segmentation training"
    assert captured["request"].model_type == "yolo11"
    assert captured["created_by"] == "workflow-user"
    assert captured["submit_kwargs"] == {}


def test_training_service_node_uses_yolo11_pose_request(
    monkeypatch,
) -> None:
    """YOLO11 pose 训练节点应构造模型专属请求。"""

    captured: dict[str, object] = {}

    class _FakeTrainingService:
        def submit_training_task(self, request, *, created_by=None, **kwargs):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["submit_kwargs"] = kwargs
            return {"task_id": "task-pose-1", "status": "queued"}

    def _build_training_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeTrainingService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_training_task_service",
        _build_training_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="pose-training-node",
        node_definition=training_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "pose",
            "model_type": "yolo11",
            "project_id": "project-1",
            "dataset_export_id": "dataset-export-1",
            "recipe_id": "recipe-1",
            "model_scale": "nano",
            "output_model_name": "pose-model",
            "max_epochs": 5,
            "display_name": "pose training",
            "created_by": "workflow-user",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = training_node._model_training_submit_handler(request)

    assert result["body"]["task_id"] == "task-pose-1"
    assert captured["service_kwargs"] == {
        "task_type": "pose",
        "model_type": "yolo11",
    }
    assert isinstance(captured["request"], Yolo11PoseTrainingTaskRequest)
    assert captured["request"].display_name == "pose training"
    assert captured["request"].model_type == "yolo11"
    assert captured["created_by"] == "workflow-user"
    assert captured["submit_kwargs"] == {}


def test_training_service_node_uses_yolo11_obb_request(
    monkeypatch,
) -> None:
    """YOLO11 OBB 训练节点应构造模型专属请求。"""

    captured: dict[str, object] = {}

    class _FakeTrainingService:
        def submit_training_task(self, request, *, created_by=None, **kwargs):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["submit_kwargs"] = kwargs
            return {"task_id": "task-obb-1", "status": "queued"}

    def _build_training_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeTrainingService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_training_task_service",
        _build_training_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="obb-training-node",
        node_definition=training_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "obb",
            "model_type": "yolo11",
            "project_id": "project-1",
            "dataset_export_id": "dataset-export-1",
            "recipe_id": "recipe-1",
            "model_scale": "nano",
            "output_model_name": "obb-model",
            "max_epochs": 5,
            "display_name": "obb training",
            "created_by": "workflow-user",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = training_node._model_training_submit_handler(request)

    assert result["body"]["task_id"] == "task-obb-1"
    assert captured["service_kwargs"] == {
        "task_type": "obb",
        "model_type": "yolo11",
    }
    assert isinstance(captured["request"], Yolo11ObbTrainingTaskRequest)
    assert captured["request"].display_name == "obb training"
    assert captured["request"].model_type == "yolo11"
    assert captured["created_by"] == "workflow-user"
    assert captured["submit_kwargs"] == {}


def test_conversion_service_node_routes_to_platform_conversion_service(
    monkeypatch,
) -> None:
    """显式 task_type/model_type 时，转换节点应走平台 conversion service。"""

    captured: dict[str, object] = {}

    class _FakeConversionService:
        def submit_conversion_task(self, request, *, created_by=None, display_name=""):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["display_name"] = display_name
            return {"task_id": "task-conversion-1", "status": "queued"}

    def _build_conversion_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeConversionService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_conversion_task_service",
        _build_conversion_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="conversion-node",
        node_definition=conversion_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "segmentation",
            "model_type": "yolo26",
            "project_id": "project-1",
            "source_model_version_id": "model-version-1",
            "target_formats": ["onnx"],
            "display_name": "segmentation conversion",
            "created_by": "workflow-user",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = conversion_node._model_conversion_submit_handler(request)

    assert result["body"]["task_id"] == "task-conversion-1"
    assert captured["service_kwargs"] == {
        "task_type": "segmentation",
        "model_type": "yolo26",
    }
    assert isinstance(captured["request"], YoloConversionTaskRequest)
    assert captured["display_name"] == "segmentation conversion"


def test_training_service_node_routes_rfdetr_detection_to_platform_training_service(
    monkeypatch,
) -> None:
    """显式 rfdetr detection 时，训练节点应构造 RF-DETR 正式请求。"""

    captured: dict[str, object] = {}

    class _FakeTrainingService:
        def submit_training_task(self, request, *, created_by=None, **kwargs):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["submit_kwargs"] = kwargs
            return {"task_id": "task-rfdetr-training-1", "status": "queued"}

    def _build_training_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeTrainingService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_training_task_service",
        _build_training_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="training-node-rfdetr",
        node_definition=training_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "detection",
            "model_type": "rfdetr",
            "project_id": "project-1",
            "dataset_export_id": "dataset-export-1",
            "recipe_id": "recipe-1",
            "model_scale": "nano",
            "output_model_name": "rfdetr-model",
            "display_name": "rfdetr training",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = training_node._model_training_submit_handler(request)

    assert result["body"]["task_id"] == "task-rfdetr-training-1"
    assert captured["service_kwargs"] == {
        "task_type": "detection",
        "model_type": "rfdetr",
    }
    assert isinstance(captured["request"], RfdetrTrainingTaskRequest)
    assert captured["submit_kwargs"] == {"display_name": "rfdetr training"}


def test_conversion_service_node_routes_rfdetr_detection_to_platform_conversion_service(
    monkeypatch,
) -> None:
    """显式 rfdetr detection 时，转换节点应构造 RF-DETR 正式请求。"""

    captured: dict[str, object] = {}

    class _FakeConversionService:
        def submit_conversion_task(self, request, *, created_by=None, display_name=""):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["display_name"] = display_name
            return {"task_id": "task-rfdetr-conversion-1", "status": "queued"}

    def _build_conversion_task_service(self, *, task_type=None, model_type="yolox"):
        captured["service_kwargs"] = {"task_type": task_type, "model_type": model_type}
        return _FakeConversionService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_conversion_task_service",
        _build_conversion_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="conversion-node-rfdetr",
        node_definition=conversion_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "detection",
            "model_type": "rfdetr",
            "project_id": "project-1",
            "source_model_version_id": "model-version-1",
            "target_formats": ["onnx"],
            "display_name": "rfdetr conversion",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = conversion_node._model_conversion_submit_handler(request)

    assert result["body"]["task_id"] == "task-rfdetr-conversion-1"
    assert captured["service_kwargs"] == {
        "task_type": "detection",
        "model_type": "rfdetr",
    }
    assert isinstance(captured["request"], RfdetrConversionTaskRequest)
    assert captured["display_name"] == "rfdetr conversion"


def test_validation_service_node_routes_to_platform_validation_service(
    monkeypatch,
) -> None:
    """显式 task_type/model_type 时，validation 节点应走平台 validation service。"""

    captured: dict[str, object] = {}

    class _FakeValidationService:
        def create_session(self, request, *, created_by=None):
            captured["request"] = request
            captured["created_by"] = created_by
            return {"session_id": "validation-session-1"}

    def _build_validation_session_service(self, *, task_type=None):
        captured["service_kwargs"] = {"task_type": task_type}
        return _FakeValidationService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_validation_session_service",
        _build_validation_session_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="validation-node",
        node_definition=validation_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "pose",
            "model_type": "yolo26",
            "project_id": "project-1",
            "model_version_id": "model-version-1",
            "score_threshold": 0.4,
            "keypoint_confidence_threshold": 0.5,
            "created_by": "workflow-user",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = validation_node._model_validation_session_create_handler(request)

    assert result["body"]["session_id"] == "validation-session-1"
    assert captured["service_kwargs"] == {"task_type": "pose"}
    assert isinstance(captured["request"], PoseValidationSessionCreateRequest)
    assert captured["request"].model_type == "yolo26"
    assert captured["request"].keypoint_confidence_threshold == 0.5


def test_evaluation_service_node_routes_to_platform_evaluation_service(
    monkeypatch,
) -> None:
    """显式 task_type 时，评估节点应走平台 evaluation service。"""

    captured: dict[str, object] = {}

    class _FakeEvaluationService:
        def submit_evaluation_task(self, request, *, created_by=None, display_name=""):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["display_name"] = display_name
            return {"task_id": "task-evaluation-1", "status": "queued"}

    def _build_evaluation_task_service(self, *, task_type=None):
        captured["service_kwargs"] = {"task_type": task_type}
        return _FakeEvaluationService()

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_evaluation_task_service",
        _build_evaluation_task_service,
    )

    request = WorkflowNodeExecutionRequest(
        node_id="evaluation-node",
        node_definition=evaluation_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "classification",
            "model_type": "yolov8",
            "project_id": "project-1",
            "model_version_id": "model-version-1",
            "top_k": 3,
            "display_name": "classification evaluation",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = evaluation_node._model_evaluation_submit_handler(request)

    assert result["body"]["task_id"] == "task-evaluation-1"
    assert captured["service_kwargs"] == {"task_type": "classification"}
    assert isinstance(
        captured["request"], YoloPrimaryClassificationEvaluationTaskRequest
    )
    assert captured["request"].top_k == 3


def test_deployment_create_node_uses_task_native_request(
    monkeypatch,
) -> None:
    """deployment create 节点应按 task_type 构造正式创建请求。"""

    captured: dict[str, object] = {}

    class _FakeDeploymentService:
        def create_deployment_instance(self, request, *, created_by=None):
            captured["request"] = request
            captured["created_by"] = created_by
            return {"deployment_instance_id": "deployment-1"}

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self, *, task_type="detection": _FakeDeploymentService(),
    )

    request = WorkflowNodeExecutionRequest(
        node_id="deployment-node",
        node_definition=deployment_create_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "classification",
            "project_id": "project-1",
            "model_version_id": "model-version-1",
            "model_type": "yolo11",
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
        ),
    )

    result = deployment_create_node._model_deployment_create_handler(request)

    assert result["body"]["deployment_instance_id"] == "deployment-1"
    assert isinstance(
        captured["request"], ClassificationDeploymentInstanceCreateRequest
    )
    assert captured["request"].model_type == "yolo11"


def test_inference_submit_node_uses_task_native_request(
    monkeypatch,
) -> None:
    """inference submit 节点应按 task_type 构造正式推理请求。"""

    captured: dict[str, object] = {}

    class _FakeDeploymentService:
        def get_deployment_instance(self, deployment_instance_id: str):
            return SimpleNamespace(
                deployment_instance_id=deployment_instance_id,
                project_id="project-1",
            )

        def resolve_process_config(self, deployment_instance_id: str):
            return SimpleNamespace(deployment_instance_id=deployment_instance_id)

    class _FakeAsyncSupervisor:
        def ensure_deployment(self, process_config):
            captured["ensure_config"] = process_config

        def get_status(self, process_config):
            return SimpleNamespace(process_state="running")

    class _FakeInferenceService:
        def submit_inference_task(self, request, *, created_by=None, display_name=""):
            captured["request"] = request
            captured["created_by"] = created_by
            captured["display_name"] = display_name
            return SimpleNamespace(
                task_id="task-inference-1",
                status="queued",
                queue_name="detection-inferences",
                queue_task_id="queue-inference-1",
                deployment_instance_id=request.deployment_instance_id,
                input_uri=request.input_uri,
            )

    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_deployment_service",
        lambda self, *, task_type="detection": _FakeDeploymentService(),
    )
    monkeypatch.setattr(
        WorkflowServiceNodeRuntimeContext,
        "build_inference_task_service",
        lambda self, *, task_type="detection": _FakeInferenceService(),
    )

    request = WorkflowNodeExecutionRequest(
        node_id="inference-node",
        node_definition=inference_node.CORE_NODE_SPEC.node_definition,
        parameters={
            "task_type": "segmentation",
            "project_id": "project-1",
            "deployment_instance_id": "deployment-1",
            "model_type": "yolo11",
            "input_uri": "inputs/source.jpg",
            "mask_threshold": 0.45,
        },
        runtime_context=WorkflowServiceNodeRuntimeContext(
            session_factory=object(),
            dataset_storage=object(),
            segmentation_async_deployment_process_supervisor=_FakeAsyncSupervisor(),
            async_inference_service_id="workflow-service",
        ),
    )

    result = inference_node._model_inference_submit_handler(request)

    assert result["body"]["task_id"] == "task-inference-1"
    assert isinstance(captured["request"], SegmentationInferenceTaskRequest)
    assert captured["request"].model_type == "yolo11"
    assert captured["request"].mask_threshold == 0.45
