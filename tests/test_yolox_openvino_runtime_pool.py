"""YOLOX runtime pool 的真实 OpenVINO 集成测试。"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def test_runtime_pool_runs_openvino_ir_build_with_openvino(tmp_path: Path) -> None:
    """验证 runtime pool 可以在隔离子进程中消费 openvino-ir ModelBuild 并完成一次真实推理。

    参数：
    - tmp_path：pytest 提供的临时目录。

    返回：
    - 无。
    """

    if importlib.util.find_spec("onnx") is None:
        pytest.skip("当前环境缺少 onnx，跳过 OpenVINO runtime pool 测试")
    if importlib.util.find_spec("openvino") is None:
        pytest.skip("当前环境缺少 openvino，跳过 OpenVINO runtime pool 测试")

    probe_root = tmp_path / "openvino-runtime-probe"
    probe_root.mkdir(parents=True, exist_ok=True)
    probe_script_path = probe_root / "openvino_runtime_probe.py"
    probe_script_path.write_text(_build_openvino_runtime_probe_script(), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(probe_script_path), str(probe_root)],
        cwd=str(_project_root()),
        capture_output=True,
        text=True,
        check=False,
        env={
            **os.environ,
            "PYTHONPATH": str(_project_root()),
        },
    )

    assert completed.returncode == 0, (
        f"openvino runtime probe 失败\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])

    assert payload["runtime_backend"] == "openvino"
    assert payload["runtime_precision"] == "fp32"
    assert payload["healthy_instance_count"] == 1
    assert payload["warmed_instance_count"] == 1
    assert payload["session_backend_name"] == "openvino"
    assert payload["session_device_name"] == "cpu"
    assert payload["runtime_execution_mode"] == "openvino:fp32:cpu"
    assert payload["detection_count"] >= 1


def _project_root() -> Path:
    """返回当前测试文件所在仓库根目录。

    参数：
    - 无。

    返回：
    - Path：仓库根目录。
    """

    return Path(__file__).resolve().parents[1]


def _build_openvino_runtime_probe_script() -> str:
    """构造 OpenVINO runtime probe 脚本文本。

    参数：
    - 无。

    返回：
    - str：可直接交给子进程执行的 Python 脚本。
    """

    return textwrap.dedent(
        '''
        from __future__ import annotations

        import base64
        import json
        import sys
        from pathlib import Path

        import onnx
        from onnx import TensorProto, helper
        from openvino import convert_model, save_model

        from backend.service.application.models.yolox_model_service import (
            SqlAlchemyYoloXModelService,
            YoloXBuildRegistration,
            YoloXTrainingOutputRegistration,
        )
        from backend.service.application.runtime.yolox_inference_runtime_pool import (
            YoloXDeploymentRuntimePool,
            YoloXDeploymentRuntimePoolConfig,
        )
        from backend.service.application.runtime.yolox_predictor import YoloXPredictionRequest
        from backend.service.application.runtime.yolox_runtime_target import (
            RuntimeTargetResolveRequest,
            SqlAlchemyYoloXRuntimeTargetResolver,
        )
        from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
        from backend.service.infrastructure.object_store.local_dataset_storage import (
            DatasetStorageSettings,
            LocalDatasetStorage,
        )
        from backend.service.infrastructure.persistence.base import Base


        def _create_test_runtime(root_dir: Path) -> tuple[SessionFactory, LocalDatasetStorage]:
            database_path = root_dir / "amvision-yolox-openvino-runtime.db"
            session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
            Base.metadata.create_all(session_factory.engine)
            dataset_storage = LocalDatasetStorage(
                DatasetStorageSettings(root_dir=str(root_dir / "dataset-files"))
            )
            return session_factory, dataset_storage


        def _seed_source_model_version(*, session_factory: SessionFactory, dataset_storage: LocalDatasetStorage) -> str:
            checkpoint_uri = "projects/project-1/models/openvino-runtime-source-1/artifacts/checkpoints/best_ckpt.pth"
            labels_uri = "projects/project-1/models/openvino-runtime-source-1/artifacts/labels.txt"
            dataset_storage.write_bytes(checkpoint_uri, b"placeholder-checkpoint")
            dataset_storage.write_text(labels_uri, "bolt\\n")

            service = SqlAlchemyYoloXModelService(session_factory=session_factory)
            return service.register_training_output(
                YoloXTrainingOutputRegistration(
                    project_id="project-1",
                    training_task_id="training-openvino-runtime-source-1",
                    model_name="yolox-nano-openvino-runtime",
                    model_scale="nano",
                    dataset_version_id="dataset-version-openvino-runtime-source-1",
                    checkpoint_file_id="checkpoint-file-openvino-runtime-1",
                    checkpoint_file_uri=checkpoint_uri,
                    labels_file_id="labels-file-openvino-runtime-1",
                    labels_file_uri=labels_uri,
                    metadata={
                        "category_names": ["bolt"],
                        "input_size": [64, 64],
                        "training_config": {"input_size": [64, 64]},
                    },
                )
            )


        def _write_openvino_ir(*, dataset_storage: LocalDatasetStorage, build_uri: str) -> None:
            onnx_path = dataset_storage.resolve(
                "projects/project-1/models/openvino-runtime-build-1/artifacts/builds/constant-model.onnx"
            )
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
                "constant-openvino-detection",
                [input_info],
                [output_info],
            )
            model = helper.make_model(
                graph,
                producer_name="amvision-openvino-runtime-test",
                opset_imports=[helper.make_opsetid("", 17)],
            )
            onnx.checker.check_model(model)
            onnx.save(model, str(onnx_path))

            ir_path = dataset_storage.resolve(build_uri)
            ir_path.parent.mkdir(parents=True, exist_ok=True)
            openvino_model = convert_model(str(onnx_path))
            save_model(openvino_model, str(ir_path), compress_to_fp16=False)


        def main() -> None:
            probe_root = Path(sys.argv[1]).resolve()
            session_factory, dataset_storage = _create_test_runtime(probe_root)
            source_model_version_id = _seed_source_model_version(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
            )

            build_uri = "projects/project-1/models/openvino-runtime-build-1/artifacts/builds/constant-model.xml"
            _write_openvino_ir(dataset_storage=dataset_storage, build_uri=build_uri)

            model_service = SqlAlchemyYoloXModelService(session_factory=session_factory)
            model_build_id = model_service.register_build(
                YoloXBuildRegistration(
                    project_id="project-1",
                    source_model_version_id=source_model_version_id,
                    build_format="openvino-ir",
                    build_file_id="build-file-openvino-runtime-1",
                    build_file_uri=build_uri,
                    conversion_task_id="conversion-openvino-runtime-1",
                )
            )
            runtime_target = SqlAlchemyYoloXRuntimeTargetResolver(
                session_factory=session_factory,
                dataset_storage=dataset_storage,
            ).resolve_target(
                RuntimeTargetResolveRequest(
                    project_id="project-1",
                    model_build_id=model_build_id,
                    device_name="cpu",
                )
            )

            pool = YoloXDeploymentRuntimePool(dataset_storage=dataset_storage)
            config = YoloXDeploymentRuntimePoolConfig(
                deployment_instance_id="deployment-instance-openvino-runtime-pool-1",
                runtime_target=runtime_target,
                instance_count=1,
            )
            warmup_status = pool.warmup_deployment(config)
            execution = pool.run_inference(
                config=config,
                request=YoloXPredictionRequest(
                    score_threshold=0.1,
                    save_result_image=False,
                    input_image_bytes=base64.b64decode(
                        "iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAE0lEQVQIHWNk+M8ABIwM/xmAAAAREgIB9FemLQAAAABJRU5ErkJggg=="
                    ),
                ),
            )

            print(
                json.dumps(
                    {
                        "runtime_backend": runtime_target.runtime_backend,
                        "runtime_precision": runtime_target.runtime_precision,
                        "healthy_instance_count": warmup_status.healthy_instance_count,
                        "warmed_instance_count": warmup_status.warmed_instance_count,
                        "session_backend_name": execution.execution_result.runtime_session_info.backend_name,
                        "session_device_name": execution.execution_result.runtime_session_info.device_name,
                        "runtime_execution_mode": execution.execution_result.runtime_session_info.metadata[
                            "runtime_execution_mode"
                        ],
                        "detection_count": len(execution.execution_result.detections),
                    }
                )
            )


        if __name__ == "__main__":
            main()
        '''
    ).strip() + "\n"