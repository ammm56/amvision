"""检测训练 API 与 Worker/core 之间的设备参数契约。"""

from types import SimpleNamespace

import pytest

from backend.service.api.rest.v1.routes.detection_training_tasks import create
from backend.service.api.rest.v1.routes.detection_training_tasks.schemas import (
    DetectionTrainingTaskCreateRequestBody,
)
from backend.service.application.errors import InvalidRequestError
from backend.service.application.models.yolox_core.training.execution import (
    _resolve_training_runtime,
)


@pytest.mark.parametrize("model_type", ["yolox", "yolov8", "yolo11", "yolo26", "rfdetr"])
@pytest.mark.parametrize("device", ["auto", "cpu", "cuda:0"])
def test_detection_create_does_not_invent_gpu_requirement(monkeypatch, model_type, device):
    """共享路由保留用户设备意图，真实模型 DTO 均允许 Worker 决定 GPU 数量。"""
    _, request_cls = create._resolve_detection_training_service_and_request(model_type)
    received = []

    class Service:
        """替换持久化副作用，只核对路由构造的真实模型请求。"""

        def __init__(self, **kwargs):
            """接受正式路由依赖。"""

        def submit_training_task(self, request, **kwargs):
            """记录请求并返回正式提交响应需要的字段。"""
            received.append(request)
            return SimpleNamespace(
                task_id="task-test", status="queued", queue_name="training",
                queue_task_id="queue-test", dataset_export_id="export-test",
                dataset_export_manifest_key="manifest.json", dataset_version_id="version-test",
                format_id="coco-detection",
            )

    monkeypatch.setattr(create, "_resolve_detection_training_service_and_request",
                        lambda _: (Service, request_cls))
    body = DetectionTrainingTaskCreateRequestBody.model_validate({
        "project_id": "project-1", "model_type": model_type,
        "dataset_export_id": "export-test", "model_scale": "s",
        "output_model_name": "device-contract",
        "parameters": {"runtime": {"device": device}},
    })
    response = create.create_detection_training_task(
        body, SimpleNamespace(project_ids=("project-1",), principal_id="test"), None, None,
    )
    assert response.status == "queued"
    assert len(received) == 1
    assert received[0].gpu_count is None
    assert received[0].extra_options["device"] == device


@pytest.mark.parametrize("device,available,count,expected", [
    ("cpu", False, None, "cpu"), ("cpu", True, None, "cpu"),
    ("auto", False, None, "cpu"), ("auto", True, None, "cuda:0"),
    ("cuda:0", True, None, "cuda:0"), ("cuda:0", True, 1, "cuda:0"),
])
def test_yolox_core_resolves_actual_device(device, available, count, expected):
    """无需实际 CUDA 即可覆盖 CPU/自动/显式单卡的设备解析。"""
    imports = SimpleNamespace(torch=SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: available, device_count=lambda: int(available),
    )))
    result = _resolve_training_runtime(
        imports=imports, requested_gpu_count=count, extra_options={"device": device},
    )
    assert result.device == expected
    assert result.gpu_count == (0 if expected == "cpu" else 1)


@pytest.mark.parametrize("device,available,count,message", [
    ("cpu", True, 1, "CPU 训练不能同时指定"),
    ("auto", False, 1, "没有可用 GPU"),
    ("cuda", False, None, "没有可用 GPU"),
    ("cuda:0", False, None, "没有可用 GPU"),
    ("cuda:1", True, None, "超出了本机可用 GPU"),
    ("cuda:0", True, 2, "只支持单 GPU"),
])
def test_yolox_core_rejects_conflicting_device_request(device, available, count, message):
    """不通过忽略显式 CUDA/GPU 要求来修复自动 CPU 回退。"""
    imports = SimpleNamespace(torch=SimpleNamespace(cuda=SimpleNamespace(
        is_available=lambda: available, device_count=lambda: int(available),
    )))
    with pytest.raises(InvalidRequestError, match=message):
        _resolve_training_runtime(
            imports=imports, requested_gpu_count=count, extra_options={"device": device},
        )
