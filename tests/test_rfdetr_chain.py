"""RF-DETR 内部链烟雾验证。"""

from __future__ import annotations

import torch


def test_rfdetr_model_can_build():
    """验证 RF-DETR 模型可以构建。"""

    from backend.service.application.models.rfdetr_core.detection import build_rfdetr_model

    model = build_rfdetr_model(model_scale="nano", num_classes=91)
    assert model is not None
    assert isinstance(model.backbone, torch.nn.Module)
    assert isinstance(model.transformer.decoder, torch.nn.Module)
    assert isinstance(model.class_embed, torch.nn.Module)


def test_rfdetr_backend_registration():
    """验证 RF-DETR 已登记到 detection backend registry。"""

    from backend.service.application.detection_backend_registry import get_detection_backend_registration

    reg = get_detection_backend_registration("rfdetr")
    assert reg is not None
    assert reg.display_name == "RF-DETR"
    assert reg.features.training is True
    assert reg.features.conversion is True
    assert reg.features.inference is True
    assert reg.features.deployment is True


def test_rfdetr_segmentation_backend_registration():
    """验证 RF-DETR segmentation 已登记为正式后端。"""

    from backend.service.application.segmentation_backend_registry import (
        get_segmentation_backend_registration,
    )

    reg = get_segmentation_backend_registration("rfdetr")
    assert reg is not None
    assert reg.display_name == "RF-DETR Segmentation"
    assert reg.features.training is True
    assert reg.features.conversion is True
    assert reg.features.inference is True
    assert reg.features.deployment is True


def test_rfdetr_segmentation_model_can_forward():
    """验证 RF-DETR segmentation 模型可以构建并完成一次前向。"""

    from backend.service.application.models.rfdetr_core.segmentation import (
        build_rfdetr_segmentation_model,
    )

    model = build_rfdetr_segmentation_model(model_scale="nano", num_classes=4)
    model.eval()
    with torch.no_grad():
        outputs = model(torch.randn(1, 3, 72, 72))
    assert outputs["pred_logits"].shape[0] == 1
    assert outputs["pred_boxes"].shape[0] == 1
    assert outputs["pred_masks"].shape[0] == 1


def test_rfdetr_imports():
    """验证所有 RF-DETR 模块可以被导入。"""
    from backend.service.application.models.rfdetr_core.detection import (
        RfdetrPostProcess,
        build_rfdetr_model,
    )
    from backend.service.application.models.catalog.rfdetr import SqlAlchemyRfdetrModelService
    from backend.service.application.models.rfdetr_core.segmentation import (
        RfdetrSegmentationPostProcess,
        build_rfdetr_segmentation_model,
    )
    from backend.service.application.models.training.rfdetr_segmentation import run_rfdetr_segmentation_training
    from backend.service.application.models.yolo_primary_segmentation_training_service import SqlAlchemyYoloPrimarySegmentationTrainingTaskService
    from backend.service.application.models.training.rfdetr_detection_task_service import SqlAlchemyRfdetrTrainingTaskService
    from backend.service.application.conversions.rfdetr_conversion_task_service import SqlAlchemyRfdetrConversionTaskService
    from backend.service.application.runtime.predictors.rfdetr import PyTorchRfdetrRuntimeSession
    from backend.service.application.runtime.predictors.rfdetr_segmentation import (
        PyTorchRfdetrSegmentationRuntimeSession,
    )
    from backend.service.application.runtime.targets.rfdetr import SqlAlchemyRfdetrRuntimeTargetResolver
    from backend.service.application.conversions.rfdetr_conversion_planner import DefaultRfdetrConversionPlanner
    from backend.service.domain.models.rfdetr_model_spec import RFDETR_DETECTION_SCALES

    assert all(
        item is not None
        for item in (
            RfdetrPostProcess,
            build_rfdetr_model,
            SqlAlchemyRfdetrModelService,
            RfdetrSegmentationPostProcess,
            build_rfdetr_segmentation_model,
            run_rfdetr_segmentation_training,
            SqlAlchemyYoloPrimarySegmentationTrainingTaskService,
            SqlAlchemyRfdetrTrainingTaskService,
            SqlAlchemyRfdetrConversionTaskService,
            PyTorchRfdetrRuntimeSession,
            PyTorchRfdetrSegmentationRuntimeSession,
            SqlAlchemyRfdetrRuntimeTargetResolver,
            DefaultRfdetrConversionPlanner,
            RFDETR_DETECTION_SCALES,
        )
    )


def test_rfdetr_postprocess_uses_flattened_query_class_topk() -> None:
    """验证 RF-DETR 后处理按 query × class 取 top-k。"""

    from backend.service.application.models.rfdetr_core.detection import RfdetrPostProcess

    postprocess = RfdetrPostProcess(num_select=3)
    processed = postprocess(
        {
            "pred_logits": torch.tensor(
                [[[1.0, 5.0, 0.0], [4.0, 0.5, 3.0]]],
                dtype=torch.float32,
            ),
            "pred_boxes": torch.tensor(
                [[[0.5, 0.5, 0.2, 0.2], [0.25, 0.25, 0.1, 0.1]]],
                dtype=torch.float32,
            ),
        },
        torch.tensor([[100.0, 200.0]], dtype=torch.float32),
    )

    assert processed["labels"].tolist() == [[1, 0, 2]]
    assert processed["boxes_xyxy"].shape == (1, 3, 4)


def test_rfdetr_detection_builder_skips_background_class() -> None:
    """验证 RF-DETR runtime 不把 background/no-object 输出为检测结果。"""

    from backend.service.application.runtime.predictors.rfdetr import _build_detections

    detections = _build_detections(
        processed={
            "scores": torch.tensor([[0.95, 0.93, 0.9]], dtype=torch.float32),
            "labels": torch.tensor([[0, 2, 1]], dtype=torch.long),
            "boxes_xyxy": torch.tensor(
                [[[0.0, 0.0, 10.0, 10.0], [1.0, 1.0, 9.0, 9.0], [2.0, 2.0, 8.0, 8.0]]],
                dtype=torch.float32,
            ),
        },
        labels=("defect", "part"),
        score_threshold=0.5,
    )

    assert len(detections) == 2
    assert tuple(item.class_id for item in detections) == (0, 1)
    assert tuple(item.class_name for item in detections) == ("defect", "part")


def test_rfdetr_public_scale_support_matches_task_specific_core() -> None:
    """验证 RF-DETR 公开 scale 不把 detection 和 segmentation 混在一起。"""

    from backend.service.domain.models.model_task_types import (
        DETECTION_TASK_TYPE,
        SEGMENTATION_TASK_TYPE,
    )
    from backend.service.domain.models.rfdetr_model_spec import (
        RFDETR_DETECTION_SCALES,
        RFDETR_SEGMENTATION_SCALES,
        resolve_rfdetr_scales_for_task,
    )

    assert RFDETR_DETECTION_SCALES == ("nano", "s", "m", "l")
    assert RFDETR_SEGMENTATION_SCALES == ("nano", "s", "m", "l", "x")
    assert resolve_rfdetr_scales_for_task(DETECTION_TASK_TYPE) == RFDETR_DETECTION_SCALES
    assert resolve_rfdetr_scales_for_task(SEGMENTATION_TASK_TYPE) == RFDETR_SEGMENTATION_SCALES


def test_rfdetr_tensorrt_runtime_load_uses_cuda_python(monkeypatch, tmp_path):
    """验证 RF-DETR TensorRT detection runtime 通过 cuda-python 辅助层加载。"""

    import numpy as np

    from backend.service.application.runtime.predictors import rfdetr as predictor_module
    from backend.service.application.runtime.runtime_target import RuntimeTargetSnapshot
    from backend.service.infrastructure.object_store.local_dataset_storage import (
        DatasetStorageSettings,
        LocalDatasetStorage,
    )

    artifact_path = tmp_path / "model.engine"
    artifact_path.write_bytes(b"fake-rfdetr-engine")
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-storage"))
    )

    class _FakeCudaRuntime:
        class cudaMemcpyKind:
            cudaMemcpyHostToDevice = 1
            cudaMemcpyDeviceToHost = 2

        def cudaSetDevice(self, index):
            return (0,)

        def cudaStreamCreate(self):
            return (0, object())

        def cudaEventCreate(self):
            return (0, object())

    class _FakeLogger:
        WARNING = 1

        def __init__(self, severity):
            self.severity = severity

    class _FakeTensorIOMode:
        INPUT = "input"
        OUTPUT = "output"

    class _FakeEngine:
        num_io_tensors = 3

        def create_execution_context(self):
            return object()

        def get_tensor_name(self, index):
            return ("images", "pred_logits", "pred_boxes")[index]

        def get_tensor_mode(self, name):
            if name == "images":
                return _FakeTensorIOMode.INPUT
            return _FakeTensorIOMode.OUTPUT

        def get_tensor_dtype(self, name):
            return _FakeTensorRT.float32

    class _FakeRuntime:
        def __init__(self, logger):
            self.logger = logger

        def deserialize_cuda_engine(self, payload):
            assert payload == b"fake-rfdetr-engine"
            return _FakeEngine()

    class _FakeTensorRT:
        Logger = _FakeLogger
        Runtime = _FakeRuntime
        TensorIOMode = _FakeTensorIOMode
        float32 = "float32"
        float16 = "float16"
        int32 = "int32"

    fake_cudart = _FakeCudaRuntime()
    fake_cuda_imports = type(
        "_FakeCudaImports",
        (),
        {"cv2": object(), "np": np, "cudart": fake_cudart},
    )()

    monkeypatch.setattr(
        predictor_module,
        "require_cuda_inference_imports",
        lambda: fake_cuda_imports,
    )
    monkeypatch.setattr(
        predictor_module,
        "import_tensorrt_module",
        lambda: _FakeTensorRT,
    )
    monkeypatch.setattr(
        predictor_module,
        "get_tensorrt_logger",
        lambda **kwargs: _FakeLogger(_FakeLogger.WARNING),
    )
    monkeypatch.setattr(
        predictor_module,
        "resolve_cuda_runtime_device_name",
        lambda **kwargs: "cuda:0",
    )
    monkeypatch.setattr(
        predictor_module,
        "build_rfdetr_runtime_postprocess_model",
        lambda *, task_type: object(),
    )

    session = predictor_module.TensorRTRfdetrRuntimeSession.load(
        dataset_storage=dataset_storage,
        runtime_target=RuntimeTargetSnapshot(
            project_id="project-1",
            model_id="model-rfdetr-1",
            model_version_id="model-version-rfdetr-1",
            model_build_id="model-build-rfdetr-1",
            model_name="rfdetr",
            model_scale="nano",
            task_type="detection",
            source_kind="training-output",
            runtime_profile_id=None,
            runtime_backend="tensorrt",
            device_name="cuda:0",
            runtime_precision="fp32",
            input_size=(64, 64),
            labels=("a", "b"),
            runtime_artifact_file_id="artifact-file-rfdetr-1",
            runtime_artifact_storage_uri="artifacts/model.engine",
            runtime_artifact_path=artifact_path,
            runtime_artifact_file_type="tensorrt-engine",
            checkpoint_file_id="checkpoint-file-rfdetr-1",
            checkpoint_storage_uri="artifacts/checkpoint.pt",
            checkpoint_path=artifact_path,
            labels_storage_uri="artifacts/labels.txt",
            model_type="rfdetr",
        ),
    )

    assert session.imports.cudart is fake_cudart
    assert session.device_name == "cuda:0"
    assert session.input_name == "images"
    assert session.output_names == ("pred_logits", "pred_boxes")


def test_rfdetr_detection_result_uses_detection_session_info_contract() -> None:
    """验证 RF-DETR detection 多输出不会写入 detection contract 不支持的字段。"""

    import numpy as np

    from backend.service.application.runtime.detection_runtime_contracts import (
        DetectionRuntimeTensorSpec,
    )
    from backend.service.application.runtime.predictors.rfdetr import (
        _build_prediction_result,
    )

    fake_session = type(
        "_FakeRfdetrSession",
        (),
        {
            "runtime_target": type(
                "_FakeRuntimeTarget",
                (),
                {
                    "runtime_backend": "tensorrt",
                    "runtime_artifact_storage_uri": "artifacts/rfdetr.engine",
                },
            )(),
            "device_name": "cuda:0",
            "input_size": (64, 64),
            "input_dtype_name": "float32",
            "imports": type("_FakeImports", (), {"cv2": object()})(),
        },
    )()
    request = type(
        "_FakeRequest",
        (),
        {"save_result_image": False},
    )()

    result = _build_prediction_result(
        session_obj=fake_session,
        image=np.zeros((32, 32, 3), dtype=np.uint8),
        detections=(),
        request=request,
        decode_ms=1.0,
        preprocess_ms=2.0,
        infer_ms=3.0,
        postprocess_ms=4.0,
        input_name="image",
        output_specs=(
            DetectionRuntimeTensorSpec(
                name="pred_logits",
                shape=(1, 300, 91),
                dtype="float32",
            ),
            DetectionRuntimeTensorSpec(
                name="pred_boxes",
                shape=(1, 300, 4),
                dtype="float32",
            ),
        ),
        metadata={"model_type": "rfdetr"},
    )

    assert result.runtime_session_info.output_spec.name == "pred_logits"
    assert result.runtime_session_info.metadata["output_specs"] == [
        {"name": "pred_logits", "shape": [1, 300, 91], "dtype": "float32"},
        {"name": "pred_boxes", "shape": [1, 300, 4], "dtype": "float32"},
    ]
