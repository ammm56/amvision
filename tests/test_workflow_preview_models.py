"""Preview 网关保持 task-native 请求与批次次序；不将替身当作模型精度验收。"""
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from backend.service.application.deployments.published_inference_gateway import (
    PublishedInferenceRequest, PublishedInferenceBatchRequest, _build_prediction_request,
)
from backend.service.application.workflows.preview import models


@pytest.mark.parametrize("task", ["detection", "classification", "segmentation", "pose", "obb"])
def test_preview_preserves_native_prediction_parameters_and_batch_order(monkeypatch, task):
    """五任务共享现有请求构造；CPU/GPU/精度配置不在 Preview 中重写。"""
    native_pool = Mock()
    monkeypatch.setattr(models, "DeploymentRuntimePool", lambda **kwargs: native_pool)
    requested, effective = object(), object()
    config = SimpleNamespace(deployment_instance_id="deployment", runtime_target=SimpleNamespace(task_type=task),
        runtime_configuration=requested, effective_runtime_configuration=effective)
    resolver = Mock(return_value=config)
    monkeypatch.setattr(models, "build_deployment_service", lambda *args, **kwargs: SimpleNamespace(resolve_process_config=resolver))
    result_builder = Mock(side_effect=lambda **kwargs: kwargs["execution_result"])
    monkeypatch.setattr(models, "_build_published_inference_result", result_builder)
    gateway = models.PreviewModelGateway(SimpleNamespace(dataset_storage=None))
    requests = tuple(PublishedInferenceRequest(task_type=task, deployment_instance_id="deployment",
        image_payload={"transport_kind": "memory", "image_handle": f"image-{i}", "media_type": "image/png"},
        input_image_bytes=bytes([i]), score_threshold=.37, top_k=3, mask_threshold=.41,
        keypoint_confidence_threshold=.29, extra_options={"iou_threshold": .43}, trace_id="same-batch") for i in range(2))
    expected = tuple(_build_prediction_request(task_type=task, request=r, normalized_image_payload=r.image_payload) for r in requests)
    first, second = object(), object()
    native_pool.run_inference.return_value = SimpleNamespace(deployment_instance_id="deployment", instance_id="instance", execution_result=first)
    native_pool.run_inference_batch.return_value = SimpleNamespace(deployment_instance_id="deployment", instance_id="instance", execution_results=(first, second))
    try:
        assert gateway.infer(requests[0]) is first
        assert asdict(native_pool.run_inference.call_args.kwargs["request"]) == asdict(expected[0])
        result = gateway.infer_batch(PublishedInferenceBatchRequest(requests))
        assert result.results == (first, second)
        actual = native_pool.run_inference_batch.call_args.kwargs
        assert tuple(asdict(item) for item in actual["requests"]) == tuple(asdict(item) for item in expected)
        assert actual["config"].runtime_configuration is effective
        assert actual["config"].requested_runtime_configuration is requested
        assert resolver.call_count == 1
        gateway.begin_run()
        gateway.infer(requests[0])
        assert resolver.call_count == 2
    finally:
        gateway.close()
    native_pool.close_deployment.assert_called_once_with("deployment")
