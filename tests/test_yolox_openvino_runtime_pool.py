"""YOLOX OpenVINO runtime pool 逻辑测试。"""

from __future__ import annotations

from pathlib import Path

from backend.service.application.runtime.yolox_inference_runtime_pool import (
    YoloXDeploymentRuntimePool,
    YoloXDeploymentRuntimePoolConfig,
)
from backend.service.application.runtime.yolox_predictor import (
    YoloXPredictionRequest,
)
from backend.service.domain.files.yolox_file_types import YOLOX_OPENVINO_IR_FILE
from tests.runtime_pool_test_support import (
    FakePredictionSession,
    build_recording_model_runtime,
    build_test_execution_result,
    build_test_runtime_target,
    create_test_dataset_storage,
)


def test_runtime_pool_loads_openvino_session_once_and_reuses_warmed_instance(
    tmp_path: Path,
) -> None:
    """验证 runtime pool 会选择 OpenVINO session，并在 warmup 后复用已加载实例。"""

    dataset_storage = create_test_dataset_storage(tmp_path)
    runtime_target = build_test_runtime_target(
        dataset_storage=dataset_storage,
        runtime_backend="openvino",
        device_name="gpu",
        runtime_precision="fp16",
        runtime_artifact_file_name="fake-model.xml",
        runtime_artifact_file_type=YOLOX_OPENVINO_IR_FILE,
    )
    config = YoloXDeploymentRuntimePoolConfig(
        deployment_instance_id="deployment-instance-openvino-runtime-pool-1",
        runtime_target=runtime_target,
        instance_count=1,
    )
    request = YoloXPredictionRequest(
        score_threshold=0.1,
        save_result_image=False,
        input_image_bytes=b"fake-image-bytes",
    )
    fake_session = FakePredictionSession(
        execution_result=build_test_execution_result(runtime_target=runtime_target)
    )
    load_requests: list[tuple[object, object, object, object]] = []
    pool = YoloXDeploymentRuntimePool(
        dataset_storage=dataset_storage,
        model_runtime=build_recording_model_runtime(
            load_requests=load_requests,
            session=fake_session,
        ),
    )
    warmup_status = pool.warmup_deployment(config)
    execution = pool.run_inference(config=config, request=request)
    health = pool.get_health(config)

    assert len(load_requests) == 1
    assert load_requests[0] == (dataset_storage, runtime_target, None, None)
    assert warmup_status.healthy_instance_count == 1
    assert warmup_status.warmed_instance_count == 1
    assert health.healthy_instance_count == 1
    assert health.warmed_instance_count == 1
    assert health.instances[0].busy is False
    assert fake_session.requests == [request]
    assert execution.instance_id == "deployment-instance-openvino-runtime-pool-1:instance-0"
    assert execution.execution_result.runtime_session_info.backend_name == "openvino"
    assert execution.execution_result.runtime_session_info.device_name == "gpu"
    assert execution.execution_result.runtime_session_info.metadata["runtime_execution_mode"] == (
        "openvino:fp16:gpu"
    )
    assert execution.execution_result.runtime_session_info.metadata["compiled_runtime_precision"] == "fp16"
