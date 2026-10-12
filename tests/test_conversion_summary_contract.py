"""转换结果的公开构建字段必须与实际已发布产物一致。"""

from types import SimpleNamespace

import pytest

from backend.service.api.rest.v1.routes.detection_conversion_tasks.responses import build_detection_conversion_task_summary
from backend.service.api.rest.v1.routes.task_conversion.responses import build_task_conversion_task_summary_response
from backend.service.application.conversions.yolo_conversion_task_service_base import YoloConversionBuildSummary, serialize_yolo_conversion_build_summary


@pytest.mark.parametrize("task_type", ("detection", "classification", "segmentation", "pose", "obb"))
@pytest.mark.parametrize(("build_format", "backend", "precision"), [("onnx", "onnxruntime", "fp32"), ("openvino-ir", "openvino", "fp16"), ("tensorrt-engine", "tensorrt", "fp16")])
def test_conversion_summary_keeps_registered_runtime_fields(task_type: str, build_format: str, backend: str, precision: str) -> None:
    """HTTP 响应不能丢弃前端需要的 runtime backend 和构建精度。"""

    build = YoloConversionBuildSummary(model_build_id="build-1", build_format=build_format, runtime_backend=backend, runtime_precision=precision, build_file_id="file-1", build_file_uri="model.output")
    task = SimpleNamespace(
        task_id="conversion-1", display_name="conversion", project_id="project-1", created_by=None, created_at="2026-10-12T00:00:00Z",
        worker_pool="conversion", state="succeeded", current_attempt_no=1, started_at=None, finished_at=None, progress={}, error_message=None,
        metadata={"model_type": "yolo11"}, task_spec={"source_model_version_id": "source-1", "target_formats": [build_format]}, result={"builds": [serialize_yolo_conversion_build_summary(build)]},
    )
    response = build_detection_conversion_task_summary(task) if task_type == "detection" else build_task_conversion_task_summary_response(task, task_type=task_type, model_type="yolo11")
    assert response.builds[0].runtime_backend == backend
    assert response.builds[0].runtime_precision == precision
