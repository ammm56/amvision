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
from backend.service.application.runtime.predictors.rfdetr.segmentation.onnxruntime import (
    OnnxRuntimeRfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.openvino import (
    OpenVINORfdetrSegmentationRuntimeSession,
)
from backend.service.application.runtime.predictors.rfdetr.segmentation.pytorch import (
    PyTorchRfdetrSegmentationRuntimeSession,
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
