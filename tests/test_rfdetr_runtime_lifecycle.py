"""RF-DETR runtime session 资源释放契约测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.service.application.runtime.predictors.rfdetr.detection.onnxruntime import (
    OnnxRuntimeRfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.detection.openvino import (
    OpenVINORfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.detection.pytorch import (
    PyTorchRfdetrRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.detection import (
    pytorch as detection_pytorch_module,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.onnxruntime import (
    OnnxRuntimeRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.openvino import (
    OpenVINORfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.pytorch import (
    PyTorchRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation import (
    pytorch as segmentation_pytorch_module,
)


@pytest.mark.parametrize(
    "session_type",
    (
        PyTorchRfdetrRuntimeSession,
        PyTorchRfdetrSegmentationRuntimeSession,
    ),
)
def test_rfdetr_pytorch_session_close_releases_gpu_model(session_type) -> None:
    """PyTorch session 必须先移回 CPU，再解除模型引用。"""

    session = object.__new__(session_type)
    model = Mock()
    session.model = model
    session.device_name = "cuda:0"
    session.postprocess_model = object()

    session.close()
    session.close()

    model.to.assert_called_once_with("cpu")
    assert session.model is None
    if hasattr(session, "postprocess_model"):
        assert session.postprocess_model is None


@pytest.mark.parametrize(
    ("module", "session_type"),
    (
        (detection_pytorch_module, PyTorchRfdetrRuntimeSession),
        (segmentation_pytorch_module, PyTorchRfdetrSegmentationRuntimeSession),
    ),
)
def test_rfdetr_pytorch_session_uses_strict_deployment_loader(
    tmp_path,
    monkeypatch,
    module,
    session_type,
) -> None:
    """PyTorch deployment 必须先建空模型，再走严格部署权重加载器。"""

    checkpoint_path = tmp_path / "best.pt"
    checkpoint_path.write_bytes(b"checkpoint")
    model = Mock()
    builder = Mock(return_value=model)
    strict_loader = Mock()
    builder_name = (
        "build_rfdetr_model"
        if session_type is PyTorchRfdetrRuntimeSession
        else "build_rfdetr_segmentation_model"
    )
    monkeypatch.setattr(module, builder_name, builder)
    monkeypatch.setattr(module, "load_rfdetr_deployment_weights", strict_loader)
    monkeypatch.setattr(
        module,
        "resolve_rfdetr_runtime_input_size",
        lambda **_: (64, 64),
    )
    if session_type is PyTorchRfdetrRuntimeSession:
        monkeypatch.setattr(
            module,
            "resolve_execution_device_name",
            lambda **_: "cpu",
        )
    runtime_target = SimpleNamespace(
        runtime_backend="pytorch",
        runtime_artifact_path=checkpoint_path,
        model_scale="nano",
        labels=("part", "defect"),
        device_name="cpu",
        runtime_precision="fp32",
        task_type=session_type.task_type,
        input_size=(64, 64),
    )

    session = session_type.load(
        dataset_storage=Mock(),
        runtime_target=runtime_target,
    )

    builder.assert_called_once_with(
        model_scale="nano",
        num_classes=2,
        pretrained_path=None,
    )
    strict_loader.assert_called_once_with(
        model=model,
        checkpoint_path=checkpoint_path,
    )
    model.to.assert_called_once_with("cpu")
    model.eval.assert_called_once_with()
    assert session.model is model


@pytest.mark.parametrize(
    "session_type",
    (
        OnnxRuntimeRfdetrRuntimeSession,
        OnnxRuntimeRfdetrSegmentationRuntimeSession,
        OpenVINORfdetrRuntimeSession,
        OpenVINORfdetrSegmentationRuntimeSession,
    ),
)
def test_rfdetr_compiled_session_close_releases_backend_references(session_type) -> None:
    """ONNX Runtime/OpenVINO session 关闭后不得继续持有 compiled model。"""

    session = object.__new__(session_type)
    session.session = object()
    session.postprocess_model = object()
    session.input_port = object()
    session.output_ports = (object(),)

    session.close()
    session.close()

    assert session.session is None
    assert session.postprocess_model is None
    if session_type is OpenVINORfdetrSegmentationRuntimeSession:
        assert session.input_port is None
        assert session.output_ports == ()


@pytest.mark.parametrize(
    (
        "module_name",
        "session_type_name",
    ),
    (
        (
            "backend.service.application.runtime.predictors.rfdetr.detection.tensorrt",
            "TensorRTRfdetrRuntimeSession",
        ),
        (
            "backend.service.application.runtime.predictors.rfdetr.segmentation.tensorrt",
            "TensorRTRfdetrSegmentationRuntimeSession",
        ),
    ),
)
def test_rfdetr_tensorrt_session_close_is_idempotent(
    monkeypatch,
    module_name: str,
    session_type_name: str,
) -> None:
    """TensorRT close 只销毁一次 CUDA event/stream，并清除 engine 引用。"""

    module = __import__(module_name, fromlist=[session_type_name])
    monkeypatch.setattr(module, "ensure_cuda_success", lambda *args, **kwargs: None)
    session_type = getattr(module, session_type_name)
    cudart = SimpleNamespace(
        cudaSetDevice=Mock(return_value=None),
        cudaEventDestroy=Mock(return_value=None),
        cudaStreamDestroy=Mock(return_value=None),
    )
    session = object.__new__(session_type)
    session.imports = SimpleNamespace(cudart=cudart)
    session.device_name = "cuda:0"
    session.execute_start_event = object()
    session.execute_end_event = object()
    session.stream = object()
    session.context = object()
    session.engine = object()
    session.runtime = object()
    session.postprocess_model = object()
    session._closed = False

    session.close()
    session.close()

    assert cudart.cudaEventDestroy.call_count == 2
    cudart.cudaStreamDestroy.assert_called_once()
    assert session.execute_start_event is None
    assert session.execute_end_event is None
    assert session.stream is None
    assert session.context is None
    assert session.engine is None
    assert session.runtime is None
