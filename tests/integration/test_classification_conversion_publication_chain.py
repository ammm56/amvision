"""真实分类训练产物的转换发布、常驻部署和 workflow 验收。

通过 AMVISION_CLASSIFICATION_SMOKE_MODEL_VERSION_ID 显式指定现有训练版本。
原数据库和输出文件只读；整条运行链在 pytest 临时目录内独立启动和回收。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.service.application.models.registry.model_service import (
    TrainingOutputRegistration,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
)
from backend.service.application.runtime.targets.runtime_target import (
    RuntimeTargetResolveRequest,
)
from backend.service.application.runtime.targets.yolo11 import (
    SqlAlchemyYolo11RuntimeTargetResolver,
)
from backend.service.infrastructure.db.schema import initialize_database_schema
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from tests.integration import yolo_model_full_chain_smoke as smoke


@pytest.mark.parametrize(
    ("target_format", "precision"),
    [
        ("openvino-ir", "fp32"),
        ("openvino-ir", "fp16"),
        ("tensorrt-engine", "fp32"),
        ("tensorrt-engine", "fp16"),
    ],
)
def test_classification_conversion_publication_chain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_format: str, precision: str
) -> None:
    """使用正式 API/worker/daemon 检查转换到 workflow 的完整输出链。"""

    version_id = os.environ.get("AMVISION_CLASSIFICATION_SMOKE_MODEL_VERSION_ID")
    if not version_id:
        pytest.skip("需要显式指定真实 YOLO11 classification 训练版本")
    run_dir = tmp_path / "runtime-chain"
    run_dir.mkdir()
    storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(run_dir / "files"))
    )
    database_path = run_dir / "runtime" / "amvision.db"
    destination = SessionFactory(
        DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}")
    )
    initialize_database_schema(destination)
    try:
        source_id, labels, input_size = _copy_training_version(
            destination, storage, version_id
        )
    finally:
        destination.engine.dispose()
    port = smoke.find_free_port(5760, 5799)
    original_environment = smoke.build_e2e_process_environment

    def environment(*, run_dir: Path, port: int) -> dict[str, str]:
        """替换测试对象存储和项目配置，不复用现场控制面或 IPC。"""

        values = original_environment(run_dir=run_dir, port=port)
        values["AMVISION_DATASET_STORAGE__ROOT_DIR"] = str(storage.root_dir)
        values["AMVISION_WORKER_DATASET_STORAGE__ROOT_DIR"] = str(storage.root_dir)
        values["AMVISION_PROJECTS__ITEMS"] = json.dumps(
            [{"project_id": "project-1", "display_name": "classification smoke"}]
        )
        return values

    monkeypatch.setattr(smoke, "build_e2e_process_environment", environment)
    case = smoke.YoloModelTaskCase(
        task_type="classification",
        dataset_dir=None,
        export_format="imagenet-classification-v1",
        input_size=input_size,
        conversion_route="/models/classification/conversion-tasks",
        deployment_route="/models/classification/deployment-instances",
        inference_route="/models/classification",
    )
    # 输入来自现场调试数据集；所有上传文件仍只进入本轮隔离对象存储。
    sample = next(
        path
        for path in (smoke.PROJECT_ROOT / "data" / "files" / "datasets").rglob("*")
        if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    )
    processes = smoke.start_service_processes(
        run_dir=run_dir, port=port, service_timeout_seconds=90
    )
    client = smoke.SmokeApiClient(
        base_url=f"http://127.0.0.1:{port}",
        token=smoke.DEFAULT_TOKEN,
        timeout_seconds=180,
    )
    deployment_id: str | None = None
    try:
        submission = client.post(
            case.conversion_route,
            json={
                "project_id": "project-1",
                "model_type": "yolo11",
                "source_model_version_id": source_id,
                "target_formats": [target_format],
                "extra_options": {
                    "openvino_ir_precision"
                    if target_format == "openvino-ir"
                    else "tensorrt_engine_precision": precision
                },
                "display_name": f"classification publication {target_format} {precision}",
            },
        )
        task_id = submission["task_id"]
        detail = smoke.poll_conversion_task(
            client=client,
            case=case,
            task_id=task_id,
            label="classification conversion publication",
            timeout_seconds=600,
        )
        assert detail["state"] == "succeeded"
        result = client.get(f"{case.conversion_route}/{task_id}/result")
        assert result["file_status"] == "ready"
        models_response = client.client.get("/models/deployment-sources", params={"project_id": "project-1", "task_type": "classification"})
        assert models_response.status_code == 200
        model = next(item for item in models_response.json() if any(version["model_version_id"] == source_id for version in item["available_versions"]))
        registered = client.get(f"/models/deployment-sources/{model['model_id']}", params={"project_id": "project-1"})
        builds = registered["builds"]
        reported_builds = {item["model_build_id"]: item for item in detail["builds"]}
        for item in builds:
            assert reported_builds[item["model_build_id"]]["runtime_backend"] == item["runtime_backend"]
            assert reported_builds[item["model_build_id"]]["runtime_precision"] == item["runtime_precision"]
        assert {build["model_build_id"] for build in builds} == {build["model_build_id"] for build in detail["builds"]}
        assert {build["build_format"] for build in builds} >= {
            "onnx",
            "onnx-optimized",
            target_format,
        }
        for build in builds:
            assert build["source_model_version_id"] == source_id
            deployment = client.post(
                case.deployment_route,
                json={
                    "project_id": "project-1",
                    "model_type": "yolo11",
                    "model_build_id": build["model_build_id"],
                    "runtime_backend": build["runtime_backend"],
                    "runtime_precision": build["runtime_precision"],
                    "device_name": "cuda:0"
                    if build["runtime_backend"] == "tensorrt"
                    else "cpu",
                    "display_name": f"publication {build['build_format']} {precision}",
                },
            )
            deployment_id = deployment["deployment_instance_id"]
            assert deployment["labels"] == list(labels)
            assert deployment["input_size"] == {
                "width": input_size[1],
                "height": input_size[0],
            }
            sync_start = client.post(
                f"{case.deployment_route}/{deployment_id}/sync/start"
            )
            assert sync_start["process_state"] == "running"
            assert sync_start["process_id"] is not None
            prediction = smoke.submit_direct_inference(
                client=client,
                case=case,
                deployment_id=deployment_id,
                model_type="yolo11",
                sample_image_path=sample,
            )
            _assert_categories(prediction, labels)
            workflow = smoke.run_workflow_app_runtime_smoke(
                client=client,
                case=case,
                project_id="project-1",
                model_type="yolo11",
                deployment_id=deployment_id,
                sample_image_path=sample,
                timeout_seconds=120,
            )
            assert workflow["run"]["state"] == "succeeded"
            client.post(f"{case.deployment_route}/{deployment_id}/sync/reset")
            stopped = client.post(f"{case.deployment_route}/{deployment_id}/sync/stop")
            assert stopped["process_state"] == "stopped"
            client.post(f"{case.deployment_route}/{deployment_id}/async/start")
            inference = smoke.submit_async_inference(
                client=client,
                case=case,
                project_id="project-1",
                deployment_id=deployment_id,
                model_type="yolo11",
                sample_image_path=sample,
            )
            smoke.poll_inference_task(
                client=client,
                case=case,
                task_id=inference["task_id"],
                label="classification asynchronous inference",
                timeout_seconds=180,
            )
            payload = client.get(
                f"{case.inference_route}/inference-tasks/{inference['task_id']}/result"
            )["payload"]
            _assert_categories(payload, labels)
            assert (
                payload["top_category"]["class_name"]
                == prediction["top_category"]["class_name"]
            )
            client.post(f"{case.deployment_route}/{deployment_id}/async/reset")
            stopped = client.post(f"{case.deployment_route}/{deployment_id}/async/stop")
            assert stopped["process_state"] == "stopped"
            print(
                f"verified {build['build_format']} {build['runtime_precision']}: published build, labels, sync/async process, inference, workflow, reset/stop",
                flush=True,
            )
            deployment_id = None
    finally:
        if deployment_id is not None:
            smoke.safe_stop_deployment(
                client=client, case=case, deployment_id=deployment_id
            )
        client.close()
        smoke.stop_managed_processes(processes)


def _copy_training_version(
    destination: SessionFactory, storage: LocalDatasetStorage, version_id: str
) -> tuple[str, tuple[str, ...], tuple[int, int]]:
    """只读源模型并复制其真实 checkpoint、labels 和输入契约。"""

    config = json.loads(
        (smoke.PROJECT_ROOT / "config" / "backend-service.json").read_text(
            encoding="utf-8"
        )
    )
    source = SessionFactory(DatabaseSettings(**config["database"]))
    source_storage = LocalDatasetStorage(
        DatasetStorageSettings(**config["dataset_storage"])
    )
    try:
        service = SqlAlchemyYolo11ModelService(session_factory=source)
        version = service.get_model_version(version_id)
        assert version is not None and version.source_kind == "training-output"
        model = service.get_model(version.model_id)
        assert (
            model is not None
            and model.model_type == "yolo11"
            and model.task_type == "classification"
        )
        target = SqlAlchemyYolo11RuntimeTargetResolver(
            session_factory=source, dataset_storage=source_storage
        ).resolve_target(
            RuntimeTargetResolveRequest(
                project_id=model.project_id,
                model_version_id=version_id,
                runtime_backend="pytorch",
                device_name="cpu",
            )
        )
        assert target.checkpoint_path is not None
        with target.checkpoint_path.open("rb") as checkpoint:
            storage.write_stream("source/best.pt", checkpoint)
        storage.write_text("source/labels.txt", "\n".join(target.labels) + "\n")
        copied = SqlAlchemyYolo11ModelService(
            session_factory=destination
        ).register_training_output(
            TrainingOutputRegistration(
                project_id="project-1",
                training_task_id="source-training",
                model_name=model.model_name,
                model_scale=model.model_scale,
                task_type="classification",
                dataset_version_id=version.dataset_version_id,
                checkpoint_file_id="source-checkpoint",
                checkpoint_file_uri="source/best.pt",
                labels_file_id="source-labels",
                labels_file_uri="source/labels.txt",
                metadata=dict(version.metadata),
            )
        )
        return copied, target.labels, target.input_size
    finally:
        source.engine.dispose()


def _assert_categories(payload: dict, labels: tuple[str, ...]) -> None:
    """推理结果只能使用 checkpoint 同版类别映射，并保留每个 class id。"""

    assert payload["top_category"]["class_name"] in labels
    assert len(payload["categories"]) == len(labels)
    for category in payload["categories"]:
        assert category["class_name"] == labels[category["class_id"]]
