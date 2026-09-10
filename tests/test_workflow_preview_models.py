"""Preview 复用部署网关协议，不能在 Worker 加载已部署模型。"""
from queue import Queue
from unittest.mock import Mock

import pytest

from backend.service.application.deployments.published_inference_gateway import (
    PublishedInferenceRequest, PublishedInferenceResult, PublishedInferenceBatchRequest,
    PublishedInferenceBatchResult, PublishedInferenceGatewayEventChannel,
    PublishedInferenceGatewayDispatcher,
)
from backend.service.application.workflows.worker.process import build_published_inference_gateway


@pytest.mark.parametrize("task", ["detection", "classification", "segmentation", "pose", "obb"])
def test_preview_client_calls_deployment_gateway_with_original_parameters(task):
    """真实 Client/Dispatcher 往返保留参数、部署身份和批次顺序。"""
    channel = PublishedInferenceGatewayEventChannel(Queue(), Queue(), 2)
    deployment = Mock()
    requests = tuple(PublishedInferenceRequest(task_type=task, deployment_instance_id="deployed",
        image_payload={"transport_kind": "buffer-ref", "buffer_ref": {"slot": i}},
        score_threshold=.37, top_k=3, mask_threshold=.41, keypoint_confidence_threshold=.29,
        auto_start_process=False, extra_options={"iou_threshold": .43}) for i in range(2))
    results = tuple(PublishedInferenceResult(task, "deployed", 1, 32 + i, 24) for i in range(2))
    deployment.infer.return_value = results[0]
    deployment.infer_batch.return_value = PublishedInferenceBatchResult(task, "deployed", "existing-instance", 2, results)
    dispatcher = PublishedInferenceGatewayDispatcher(channel=channel, gateway=deployment)
    dispatcher.start()
    client = build_published_inference_gateway(channel)
    try:
        assert client.infer(requests[0]).image_width == 32
        deployment.infer.assert_called_once_with(requests[0])
        result = client.infer_batch(PublishedInferenceBatchRequest(requests))
        assert result.instance_id == "existing-instance"
        assert [item.image_width for item in result.results] == [32, 33]
        deployment.infer_batch.assert_called_once_with(PublishedInferenceBatchRequest(requests))
    finally:
        client.close()
        dispatcher.stop()
