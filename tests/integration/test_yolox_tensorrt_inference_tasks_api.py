"""YOLOX TensorRT inference-tasks API 真链路集成测试。"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient
from onnx import TensorProto, helper
import pytest

from backend.queue import LocalFileQueueBackend, LocalFileQueueSettings
from backend.service.api.app import create_app
from backend.service.application.models.yolox_model_service import (
    SqlAlchemyYoloXModelService,
    YoloXBuildRegistration,
    YoloXTrainingOutputRegistration,
)
from backend.service.application.tasks.task_service import SqlAlchemyTaskService
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import DatasetStorageSettings, LocalDatasetStorage
from backend.service.infrastructure.persistence.base import Base
from backend.service.settings import BackendServiceSettings, BackendServiceTaskManagerConfig
from backend.workers.inference.yolox_inference_queue_worker import YoloXInferenceQueueWorker


pytest.importorskip("onnx")


_VALID_TEST_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVQIHWNk+M8ABIwM/xmAAAAREgIB9FemLQAAAABJRU5ErkJggg=="


@pytest.mark.parametrize("runtime_precision", ["fp32", "fp16"])
def test_tensorrt_inference_task_runs_through_real_async_deployment_process(
    tmp_path: Path,
    runtime_precision: str,
) -> None:
    """验证 TensorRT inference-tasks 会通过真实 async deployment 子进程完成闭环。

    参数：
    - tmp_path：测试临时目录。
    - runtime_precision：当前测试使用的 TensorRT precision。
    """

    if not _can_run_tensorrt_runtime_probe():
        pytest.skip("当前环境缺少可执行的 TensorRT CUDA 运行条件，跳过 TensorRT inference-tasks API 测试")

    client, session_factory, dataset_storage, queue_backend = _create_real_test_client(tmp_path)
    model_version_id = _seed_model_version(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
    )
    model_build_id = _seed_tensorrt_model_build(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        model_version_id=model_version_id,
        runtime_precision=runtime_precision,
    )
    dataset_storage.write_bytes("runtime-inputs/inference-image.png", _build_valid_test_image_bytes())
    worker = YoloXInferenceQueueWorker(
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
        deployment_process_supervisor=client.app.state.yolox_async_deployment_process_supervisor,
        worker_id=f"test-yolox-tensorrt-inference-worker-{runtime_precision}",
    )

    try:
        with client:
            deployment_response = client.post(
                "/api/v1/models/yolox/deployment-instances",
                headers=_build_model_headers(),
                json={
                    "project_id": "project-1",
                    "model_build_id": model_build_id,
                    "runtime_backend": "tensorrt",
                    "runtime_precision": runtime_precision,
                    "device_name": "cuda",
                    "display_name": f"yolox tensorrt {runtime_precision} inference deployment",
                },
            )
            assert deployment_response.status_code == 201
            deployment_payload = deployment_response.json()
            deployment_instance_id = deployment_payload["deployment_instance_id"]
            assert deployment_payload["model_version_id"] == model_version_id
            assert deployment_payload["model_build_id"] == model_build_id
            assert deployment_payload["runtime_backend"] == "tensorrt"
            assert deployment_payload["runtime_precision"] == runtime_precision
            assert deployment_payload["device_name"] == "cuda:0"
            assert deployment_payload["runtime_execution_mode"] == f"tensorrt:{runtime_precision}:cuda:0"

            async_start_response = client.post(
                f"/api/v1/models/yolox/deployment-instances/{deployment_instance_id}/async/start",
                headers=_build_model_headers(),
            )
            assert async_start_response.status_code == 200
            assert async_start_response.json()["process_state"] == "running"

            create_response = client.post(
                "/api/v1/models/yolox/inference-tasks",
                headers=_build_inference_headers(),
                json={
                    "project_id": "project-1",
                    "deployment_instance_id": deployment_instance_id,
                    "input_uri": "runtime-inputs/inference-image.png",
                    "score_threshold": 0.1,
                    "save_result_image": False,
                    "return_preview_image_base64": False,
                },
            )
            assert create_response.status_code == 202
            submission = create_response.json()
            task_id = submission["task_id"]
            assert submission["input_source_kind"] == "input_uri"

            task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=False)
            runtime_target_snapshot = task_detail.task.task_spec.get("runtime_target_snapshot")
            assert isinstance(runtime_target_snapshot, dict)
            assert runtime_target_snapshot["model_version_id"] == model_version_id
            assert runtime_target_snapshot["model_build_id"] == model_build_id
            assert runtime_target_snapshot["runtime_backend"] == "tensorrt"
            assert runtime_target_snapshot["runtime_precision"] == runtime_precision
            assert runtime_target_snapshot["device_name"] == "cuda:0"
            assert runtime_target_snapshot["runtime_artifact_storage_uri"].endswith("constant-model.engine")

            pending_result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert pending_result_response.status_code == 200
            assert pending_result_response.json()["file_status"] == "pending"

            assert worker.run_once() is True

            detail_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}",
                headers=_build_task_headers(),
            )
            assert detail_response.status_code == 200
            detail_payload = detail_response.json()
            assert detail_payload["state"] == "succeeded"
            assert detail_payload["deployment_instance_id"] == deployment_instance_id
            assert detail_payload["model_version_id"] == model_version_id
            assert detail_payload["model_build_id"] == model_build_id
            assert detail_payload["detection_count"] >= 1
            assert detail_payload["latency_ms"] is not None

            result_response = client.get(
                f"/api/v1/models/yolox/inference-tasks/{task_id}/result",
                headers=_build_task_headers(),
            )
            assert result_response.status_code == 200
            result_payload = result_response.json()
            assert result_payload["file_status"] == "ready"
            payload = result_payload["payload"]
            assert payload["request_id"] == task_id
            assert payload["deployment_instance_id"] == deployment_instance_id
            assert payload["input_source_kind"] == "input_uri"
            assert payload["detections"]
            assert payload["detections"][0]["class_name"] == "bolt"
            assert payload["preview_image_uri"] is None
            assert payload["preview_image_base64"] is None
            assert payload["runtime_session_info"]["backend_name"] == "tensorrt"
            assert payload["runtime_session_info"]["device_name"] == "cuda:0"
            assert payload["runtime_session_info"]["input_spec"]["dtype"] == "float32"
            assert payload["runtime_session_info"]["output_spec"]["dtype"] in {"float32", "float16"}
            assert payload["runtime_session_info"]["metadata"]["model_build_id"] == model_build_id
            assert payload["runtime_session_info"]["metadata"]["runtime_execution_mode"] == (
                f"tensorrt:{runtime_precision}:cuda:0"
            )
            assert payload["runtime_session_info"]["metadata"]["compiled_runtime_precision"] == runtime_precision

        task_detail = SqlAlchemyTaskService(session_factory).get_task(task_id, include_events=True)
        assert any(event.message == "yolox inference completed" for event in task_detail.events)
    finally:
        session_factory.engine.dispose()


def _create_real_test_client(
    tmp_path: Path,
) -> tuple[TestClient, SessionFactory, LocalDatasetStorage, LocalFileQueueBackend]:
    """创建启用真实 deployment supervisor 的 API 客户端。

    参数：
    - tmp_path：测试临时目录。

    返回：
    - TestClient、SessionFactory、LocalDatasetStorage 和 LocalFileQueueBackend。
    """

    database_path = tmp_path / "amvision-tensorrt-inference-api.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    queue_backend = LocalFileQueueBackend(
        LocalFileQueueSettings(root_dir=str(tmp_path / "queue-files"))
    )
    settings = BackendServiceSettings(
        task_manager=BackendServiceTaskManagerConfig(
            enabled=False,
            max_concurrent_tasks=2,
            poll_interval_seconds=0.05,
        )
    )
    application = create_app(
        settings=settings,
        session_factory=session_factory,
        dataset_storage=dataset_storage,
        queue_backend=queue_backend,
    )
    client = TestClient(application)
    return client, session_factory, dataset_storage, queue_backend


def _seed_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一个带 checkpoint 和 labels 的最小训练输出 ModelVersion。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储。

    返回：
    - 新建的 ModelVersion id。
    """

    checkpoint_uri = "projects/project-1/models/tensorrt-inference-source-1/artifacts/checkpoints/best_ckpt.pth"
    labels_uri = "projects/project-1/models/tensorrt-inference-source-1/artifacts/labels.txt"
    dataset_storage.write_bytes(checkpoint_uri, b"placeholder-checkpoint")
    dataset_storage.write_text(labels_uri, "bolt\n")

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_training_output(
        YoloXTrainingOutputRegistration(
            project_id="project-1",
            training_task_id="training-tensorrt-inference-source-1",
            model_name="yolox-nano-tensorrt-inference",
            model_scale="nano",
            dataset_version_id="dataset-version-tensorrt-inference-source-1",
            checkpoint_file_id="checkpoint-file-tensorrt-inference-1",
            checkpoint_file_uri=checkpoint_uri,
            labels_file_id="labels-file-tensorrt-inference-1",
            labels_file_uri=labels_uri,
            metadata={
                "category_names": ["bolt"],
                "input_size": [64, 64],
                "training_config": {"input_size": [64, 64]},
            },
        )
    )


def _seed_tensorrt_model_build(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
    model_version_id: str,
    runtime_precision: str,
) -> str:
    """写入与 ModelVersion 绑定的最小 TensorRT engine ModelBuild。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_storage：本地文件存储。
    - model_version_id：来源 ModelVersion id。
    - runtime_precision：目标 TensorRT precision。

    返回：
    - 新建的 ModelBuild id。
    """

    onnx_uri = (
        f"projects/project-1/models/tensorrt-inference-build-{runtime_precision}/artifacts/builds/constant-model.onnx"
    )
    engine_uri = (
        f"projects/project-1/models/tensorrt-inference-build-{runtime_precision}/artifacts/builds/constant-model.engine"
    )
    _write_constant_onnx(dataset_storage=dataset_storage, onnx_uri=onnx_uri)
    _build_tensorrt_engine(
        dataset_storage=dataset_storage,
        onnx_uri=onnx_uri,
        engine_uri=engine_uri,
        runtime_precision=runtime_precision,
    )

    service = SqlAlchemyYoloXModelService(session_factory=session_factory)
    return service.register_build(
        YoloXBuildRegistration(
            project_id="project-1",
            source_model_version_id=model_version_id,
            build_format="tensorrt-engine",
            build_file_id=f"build-file-tensorrt-engine-{runtime_precision}-1",
            build_file_uri=engine_uri,
            conversion_task_id=f"conversion-task-tensorrt-inference-{runtime_precision}-1",
            metadata={
                "build_precision": runtime_precision,
                "tensorrt_version": _read_tensorrt_version(),
            },
        )
    )


def _write_constant_onnx(*, dataset_storage: LocalDatasetStorage, onnx_uri: str) -> None:
    """写出一个固定检测输出的最小 ONNX 模型。

    参数：
    - dataset_storage：本地文件存储。
    - onnx_uri：目标 ONNX object key。
    """

    import onnx

    onnx_path = dataset_storage.resolve(onnx_uri)
    onnx_path.parent.mkdir(parents=True, exist_ok=True)

    input_info = helper.make_tensor_value_info("images", TensorProto.FLOAT, [1, 3, 64, 64])
    output_info = helper.make_tensor_value_info("predictions", TensorProto.FLOAT, [1, 1, 6])
    reduce_node = helper.make_node(
        "ReduceMean",
        inputs=["images"],
        outputs=["pooled"],
        axes=[1, 2, 3],
        keepdims=0,
    )
    zero_tensor = helper.make_tensor("zero_scalar", TensorProto.FLOAT, [1], [0.0])
    prediction_tensor = helper.make_tensor(
        "constant_predictions",
        TensorProto.FLOAT,
        [1, 1, 6],
        [32.0, 32.0, 16.0, 16.0, 0.95, 0.99],
    )
    reshape_shape = helper.make_tensor("reshape_shape", TensorProto.INT64, [3], [1, 1, 1])
    zero_node = helper.make_node("Constant", inputs=[], outputs=["zero_value"], value=zero_tensor)
    prediction_node = helper.make_node(
        "Constant",
        inputs=[],
        outputs=["prediction_value"],
        value=prediction_tensor,
    )
    reshape_shape_node = helper.make_node(
        "Constant",
        inputs=[],
        outputs=["reshape_value"],
        value=reshape_shape,
    )
    mul_node = helper.make_node("Mul", inputs=["pooled", "zero_value"], outputs=["zeroed"])
    reshape_node = helper.make_node(
        "Reshape",
        inputs=["zeroed", "reshape_value"],
        outputs=["zeroed_reshaped"],
    )
    add_node = helper.make_node(
        "Add",
        inputs=["zeroed_reshaped", "prediction_value"],
        outputs=["predictions"],
    )
    graph = helper.make_graph(
        [
            reduce_node,
            zero_node,
            prediction_node,
            reshape_shape_node,
            mul_node,
            reshape_node,
            add_node,
        ],
        "constant-tensorrt-inference-detection",
        [input_info],
        [output_info],
    )
    model = helper.make_model(
        graph,
        producer_name="amvision-tensorrt-inference-api-test",
        opset_imports=[helper.make_opsetid("", 17)],
    )
    onnx.checker.check_model(model)
    onnx.save(model, str(onnx_path))


def _build_tensorrt_engine(
    *,
    dataset_storage: LocalDatasetStorage,
    onnx_uri: str,
    engine_uri: str,
    runtime_precision: str,
) -> None:
    """使用 TensorRT Python API 从 ONNX 构建 engine。

    参数：
    - dataset_storage：本地文件存储。
    - onnx_uri：来源 ONNX object key。
    - engine_uri：目标 TensorRT engine object key。
    - runtime_precision：当前构建使用的 TensorRT precision。
    """

    import tensorrt as trt

    onnx_path = dataset_storage.resolve(onnx_uri)
    engine_path = dataset_storage.resolve(engine_uri)
    engine_path.parent.mkdir(parents=True, exist_ok=True)

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    network_flags = 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    network = builder.create_network(network_flags)
    parser = trt.OnnxParser(network, logger)
    with onnx_path.open("rb") as handle:
        parsed = parser.parse(handle.read())
    if not parsed:
        parser_errors = [str(parser.get_error(index)) for index in range(parser.num_errors)]
        raise AssertionError("TensorRT 解析 ONNX 失败: " + " | ".join(parser_errors))

    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 1 << 30)
    if runtime_precision == "fp16":
        if not builder.platform_has_fast_fp16:
            pytest.skip("当前 TensorRT 平台不支持 fast fp16，跳过 fp16 inference-tasks API 测试")
        config.set_flag(trt.BuilderFlag.FP16)

    serialized_engine = builder.build_serialized_network(network, config)
    if serialized_engine is None:
        raise AssertionError("TensorRT build_serialized_network 返回空结果")
    engine_path.write_bytes(bytes(serialized_engine))


def _read_tensorrt_version() -> str:
    """返回当前 TensorRT 版本号。

    返回：
    - 当前可导入的 TensorRT 版本字符串。
    """

    import tensorrt as trt

    return str(trt.__version__)


def _can_run_tensorrt_runtime_probe() -> bool:
    """返回当前环境是否具备 TensorRT inference-tasks 真链路测试条件。

    返回：
    - 当前环境是否可执行 TensorRT + CUDA 推理。
    """

    if importlib.util.find_spec("tensorrt") is None:
        return False
    if importlib.util.find_spec("cuda") is None:
        return False
    try:
        from cuda.bindings import runtime
    except Exception:
        return False
    try:
        status, device_count = runtime.cudaGetDeviceCount()
    except Exception:
        return False
    return int(status) == 0 and int(device_count) > 0


def _build_valid_test_image_bytes() -> bytes:
    """返回可被 OpenCV 正常读取的最小 PNG 图片字节。

    返回：
    - 最小有效 PNG 图片字节。
    """

    return base64.b64decode(_VALID_TEST_IMAGE_BASE64)


def _build_model_headers() -> dict[str, str]:
    """构建 deployment API 所需请求头。

    返回：
    - 具备 models:read 和 models:write scope 的请求头。
    """

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,models:write",
    }


def _build_inference_headers() -> dict[str, str]:
    """构建 inference create 接口请求头。

    返回：
    - 具备 models:read 和 tasks:write scope 的请求头。
    """

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "models:read,tasks:write",
    }


def _build_task_headers() -> dict[str, str]:
    """构建 task 读取接口请求头。

    返回：
    - 具备 tasks:read scope 的请求头。
    """

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "tasks:read",
    }