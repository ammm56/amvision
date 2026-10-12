"""各模型族 OpenVINO IR 存储精度与设备计算精度的共享规则。"""

from importlib import import_module
from types import SimpleNamespace

import pytest

from backend.service.application.runtime.targets.runtime_target import resolve_runtime_precision


_OPENVINO_SESSIONS = ["yolox.openvino"] + [f"{model}.{task}.openvino" for model in ("yolov8", "yolo11", "yolo26") for task in ("detection", "classification", "segmentation", "pose", "obb")] + [f"rfdetr.{task}.openvino" for task in ("detection", "segmentation")]
_MODULE_PREFIX = "backend.service.application.runtime.predictors."


@pytest.mark.parametrize("session_module", _OPENVINO_SESSIONS)
@pytest.mark.parametrize("device_name", ("cpu", "auto", "gpu", "npu"))
def test_all_openvino_sessions_allow_compressed_fp16_ir(session_module: str, device_name: str) -> None:
    """全部 18 个模型任务组合均不能把 FP16 IR 当成仅支持 GPU 的计算类型。"""

    module = import_module(_MODULE_PREFIX + session_module)
    builders = [value for name, value in vars(module).items() if name.startswith("build_") and "openvino_compile_properties" in name]
    assert len(builders) == 1
    fake_openvino = SimpleNamespace(properties=SimpleNamespace(hint=SimpleNamespace(inference_precision="INFERENCE_PRECISION_HINT")), Type=SimpleNamespace(f16="f16"))
    properties = builders[0](openvino_module=fake_openvino, runtime_precision="fp16", requested_device_name=device_name)
    assert properties == ({"INFERENCE_PRECISION_HINT": "f16"} if device_name in {"gpu", "npu"} else {})
    assert resolve_runtime_precision(runtime_precision="fp16", runtime_backend="openvino", device_name=device_name) == "fp16"


@pytest.mark.parametrize(("module_name", "resolver_name"), [
    ("yolox.backend", "resolve_yolox_openvino_compiled_runtime_precision"),
    ("common.yolo_runtime_backend", "resolve_yolo_runtime_openvino_compiled_runtime_precision"),
    ("yolov8.detection.backend", "resolve_yolov8_detection_openvino_compiled_runtime_precision"),
    ("yolov8.segmentation.backend", "resolve_yolov8_segmentation_openvino_compiled_runtime_precision"),
    ("yolo11.segmentation.backend", "resolve_yolo11_segmentation_openvino_compiled_runtime_precision"),
    ("yolo26.segmentation.backend", "resolve_yolo26_segmentation_openvino_compiled_runtime_precision"),
    ("yolo26.classification.backend", "resolve_yolo26_classification_openvino_compiled_runtime_precision"),
])
def test_bf16_effective_precision_is_not_misreported_as_ir_precision(module_name: str, resolver_name: str) -> None:
    """CPU plugin 实际采用 BF16 时不得显示为权重文件的 FP16。"""

    resolver = getattr(import_module(_MODULE_PREFIX + module_name), resolver_name)
    session = SimpleNamespace(get_property=lambda name: "bf16")
    assert resolver(session=session, fallback_precision="fp16") == "bf16"
