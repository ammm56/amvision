"""同步推理显式保存记录、数据集样本 file-ref 与批量异步推理任务回归测试。"""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from alembic import command
from alembic.config import Config
import sqlalchemy as sa

from backend.service.application.errors import InvalidRequestError, ServiceError
from backend.service.application.models.inference.batch_inference_task_service import (
    SqlAlchemyBatchInferenceTaskService,
)
from backend.service.application.models.registry.yolo11_model_service import (
    SqlAlchemyYolo11ModelService,
    Yolo11TrainingOutputRegistration,
)
from backend.service.infrastructure.db.session import SessionFactory
from backend.service.infrastructure.object_store.local_dataset_storage import (
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.dataset_orm import (
    DatasetCategoryRecord,
    DatasetRecord,
    DatasetSampleRecord,
    DatasetVersionRecord,
)
from tests.api_test_support import build_test_headers, create_api_test_context
from tests.yolox_test_support import FakeDeploymentProcessSupervisor


def _make_png_bytes(width: int = 32, height: int = 32) -> bytes:
    """构造最小可解码 PNG 图片字节。"""

    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :] = (40, 120, 220)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def _seed_detection_model_version(
    *,
    session_factory: SessionFactory,
    dataset_storage: LocalDatasetStorage,
) -> str:
    """写入一份可用的 detection 模型版本供部署与批量推理测试使用。"""

    dataset_storage.write_bytes("models/det/best.pt", b"weights")
    dataset_storage.write_text("models/det/labels.txt", "bolt\nnut\n")
    model_service = SqlAlchemyYolo11ModelService(
        session_factory=session_factory,
    )
    return model_service.register_training_output(
        Yolo11TrainingOutputRegistration(
            project_id="project-1",
            model_name="det-test-model",
            model_scale="nano",
            task_type="detection",
            training_task_id="train-det-1",
            dataset_version_id="dataset-version-1",
            checkpoint_file_id="ckpt-det-1",
            checkpoint_file_uri="models/det/best.pt",
            labels_file_id="labels-det-1",
            labels_file_uri="models/det/labels.txt",
            metadata={
                "category_names": ["bolt", "nut"],
                "input_size": {"width": 64, "height": 64},
            },
        )
    )


def _create_detection_deployment(client, model_version_id: str) -> str:
    """通过 REST API 创建一条 detection deployment instance。"""

    response = client.post(
        "/api/v1/models/detection/deployment-instances",
        headers=build_test_headers(scopes="models:read,models:write"),
        json={
            "project_id": "project-1",
            "model_type": "yolo11",
            "model_version_id": model_version_id,
            "runtime_backend": "pytorch",
            "device_name": "cpu",
            "runtime_precision": "fp32",
            "display_name": "test-det-deploy",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["deployment_instance_id"]


def test_alembic_migration_upgrade_and_downgrade(tmp_path: Path) -> None:
    """验证 Alembic 迁移能够纯净建表并支持回滚。"""

    db_path = tmp_path / "migration-test.db"
    alembic_cfg = Config(str(Path("backend/alembic.ini").resolve()))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(alembic_cfg, "head")
    engine = sa.create_engine(f"sqlite:///{db_path.as_posix()}")
    inspector = sa.inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "direct_inference_records",
        "batch_inference_tasks",
        "batch_inference_task_items",
    }.issubset(tables)

    command.downgrade(alembic_cfg, "1c92ab5f486e")
    inspector = sa.inspect(engine)
    tables_after = set(inspector.get_table_names())
    assert "direct_inference_records" not in tables_after
    assert "batch_inference_tasks" not in tables_after
    assert "batch_inference_task_items" not in tables_after
    engine.dispose()


def test_direct_inference_records_save_lookup_and_cleanup(tmp_path: Path) -> None:
    """验证同步显式保存记录的幂等去重、request_id 反查、读图、清理失败回滚和删除。"""

    ctx = create_api_test_context(tmp_path, database_name="records.db")
    png_bytes = _make_png_bytes()
    preview_b64 = base64.b64encode(png_bytes).decode("ascii")
    payload = {
        "project_id": "project-1",
        "request_id": "req-sync-001",
        "task_type": "detection",
        "deployment_instance_id": "deploy-001",
        "input_label": "sample.png",
        "input_image_base64": f"data:image/png;base64,{preview_b64}",
        "parameters": {"score_threshold": 0.35},
        "result_payload": {
            "request_id": "req-sync-001",
            "deployment_instance_id": "deploy-001",
            "model_version_id": "mv-1",
            "input_uri": "memory://runtime/sample.png",
            "input_source_kind": "multipart",
            "score_threshold": 0.35,
            "save_result_image": True,
            "return_preview_image_base64": False,
            "image_width": 32,
            "image_height": 32,
            "detection_count": 1,
            "latency_ms": 14.2,
            "labels": ["bolt"],
            "detections": [
                {"bbox_xyxy": [2.0, 3.0, 20.0, 24.0], "score": 0.91, "class_id": 0, "class_name": "bolt"}
            ],
            "runtime_session_info": {"backend": "onnxruntime"},
            "preview_image_base64": preview_b64,
        },
    }

    with ctx.client as client:
        headers = build_test_headers(scopes="models:read")
        created = client.post("/api/v1/inference-records", headers=headers, json=payload)
        assert created.status_code == 201, created.text
        created_data = created.json()
        assert created_data["item_count"] == 1
        assert created_data["has_input_image"] is True
        assert created_data["has_preview_image"] is True
        record_id = created_data["record_id"]

        # 重试保存相同 request_id 应幂等返回同一条记录
        retried = client.post("/api/v1/inference-records", headers=headers, json=payload)
        assert retried.status_code == 201
        assert retried.json()["record_id"] == record_id

        # 超时场景按 request_id 反查
        listed = client.get(
            "/api/v1/inference-records",
            headers=headers,
            params={"project_id": "project-1", "request_id": "req-sync-001"},
        )
        assert listed.status_code == 200
        assert listed.headers.get("X-Total-Count") == "1"
        assert listed.json()[0]["record_id"] == record_id

        # 读取详情与图片
        detail = client.get(f"/api/v1/inference-records/{record_id}", headers=headers)
        assert detail.status_code == 200
        detail_json = detail.json()
        assert detail_json["file_status"] == "ready"
        assert detail_json["result_payload"]["detections"][0]["class_name"] == "bolt"

        img_resp = client.get(
            f"/api/v1/inference-records/{record_id}/image",
            headers=headers,
            params={"kind": "input"},
        )
        assert img_resp.status_code == 200
        assert img_resp.content == png_bytes

        # 当磁盘目录删除遇到 OSError 时，数据库记录必须保留
        with patch.object(
            LocalDatasetStorage,
            "delete_tree",
            side_effect=OSError("file locked"),
        ):
            failed_delete = client.delete(f"/api/v1/inference-records/{record_id}", headers=headers)
            assert failed_delete.status_code >= 500
        still_there = client.get(f"/api/v1/inference-records/{record_id}", headers=headers)
        assert still_there.status_code == 200

        # 恢复正常后删除成功且文件清理干净
        deleted = client.delete(f"/api/v1/inference-records/{record_id}", headers=headers)
        assert deleted.status_code == 204
        gone = client.get(f"/api/v1/inference-records/{record_id}", headers=headers)
        assert gone.status_code == 404


def test_dataset_sample_file_ref_returns_valid_public_file_id(tmp_path: Path) -> None:
    """验证数据集版本样本 file-ref 接口能返回合法的公开 Project file_id。"""

    ctx = create_api_test_context(tmp_path, database_name="records.db")
    img_bytes = _make_png_bytes(40, 24)
    version_id = "dv-test-1"
    dataset_id = "ds-1"
    image_key = f"projects/project-1/datasets/{dataset_id}/versions/{version_id}/images/train/sample-1/part_01.png"
    ctx.dataset_storage.write_bytes(image_key, img_bytes)

    with ctx.session_factory.create_session() as session:
        session.add(
            DatasetRecord(
                project_id="project-1",
                dataset_id=dataset_id,
                display_name="紧固件",
                description="",
                task_type="detection",
                created_at="2026-11-27T00:00:00Z",
                updated_at="2026-11-27T00:00:00Z",
                revision="rev1",
                version_sequence=1,
            )
        )
        session.add(
            DatasetVersionRecord(
                dataset_version_id=version_id,
                dataset_id=dataset_id,
                project_id="project-1",
                task_type="detection",
                version_number=1,
                metadata_json={"created_at": "2026-11-27T00:00:00Z"},
            )
        )
        session.flush()
        session.add(
            DatasetCategoryRecord(
                dataset_version_id=version_id,
                category_id=0,
                name="bolt",
            )
        )
        session.add(
            DatasetSampleRecord(
                sample_id="sample-1",
                dataset_version_id=version_id,
                image_id=1,
                file_name="part_01.png",
                width=40,
                height=24,
                split="train",
                metadata_json={
                    "image_object_key": "images/train/sample-1/part_01.png"
                },
            )
        )
        session.commit()

    with ctx.client as client:
        headers = build_test_headers(scopes="datasets:read")
        resp = client.get(
            f"/api/v1/datasets/{dataset_id}/versions/{version_id}/samples/sample-1/file-ref",
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["file_id"].startswith("public-project-file-v1_")
        assert data["sample_id"] == "sample-1"
        assert ctx.dataset_storage.resolve(data["object_key"]).is_file()


def test_batch_inference_lifecycle_enforces_async_mode_and_isolates_failures(
    tmp_path: Path,
) -> None:
    """验证未启动任何通道时拒绝创建，启动 async 后逐图执行、隔离失败与删除边界。"""

    ctx = create_api_test_context(tmp_path, database_name="records.db")
    sync_supervisor = FakeDeploymentProcessSupervisor(
        runtime_mode="sync",
        dataset_storage_root_dir=ctx.dataset_storage.root_dir,
    )
    async_supervisor = FakeDeploymentProcessSupervisor(
        runtime_mode="async",
        dataset_storage_root_dir=ctx.dataset_storage.root_dir,
    )
    ctx.client.app.state.detection_sync_deployment_process_supervisor = sync_supervisor
    ctx.client.app.state.detection_async_deployment_process_supervisor = async_supervisor

    model_version_id = _seed_detection_model_version(
        session_factory=ctx.session_factory,
        dataset_storage=ctx.dataset_storage,
    )
    png_bytes = _make_png_bytes(64, 64)

    class _FakeAsyncExecutor:
        def __init__(self) -> None:
            self.calls = 0

        def execute_inference(self, *, process_config, request, owner_id):
            self.calls += 1
            if "bad" in (request.input_uri or ""):
                raise InvalidRequestError("图像推理模拟失败")
            return {
                "instance_id": "inst-async-1",
                "execution_result": {
                    "detections": [
                        {
                            "bbox_xyxy": [4.0, 4.0, 30.0, 30.0],
                            "score": 0.88,
                            "class_id": 0,
                            "class_name": "bolt",
                        }
                    ],
                    "latency_ms": 12.5,
                    "image_width": 64,
                    "image_height": 64,
                    "runtime_session_info": {"backend": "pytorch"},
                    "preview_image_object_key": None,
                },
            }

    with ctx.client as client:
        deployment_id = _create_detection_deployment(client, model_version_id)
        inf_headers = build_test_headers(scopes="models:read,tasks:write")
        read_headers = build_test_headers(scopes="tasks:read")

        # 1. async 进程未启动时应拒绝创建批量任务
        rejected = client.post(
            "/api/v1/inference-batches",
            headers=inf_headers,
            data={
                "project_id": "project-1",
                "task_type": "detection",
                "deployment_instance_id": deployment_id,
                "display_name": "unready-batch",
            },
            files=[("input_images", ("good.png", png_bytes, "image/png"))],
        )
        assert rejected.status_code == 400

        # 2. 启动 async 进程后创建批量任务，并关闭自动后台线程改由同步触发以确定性断言进度
        start_resp = client.post(
            f"/api/v1/models/detection/deployment-instances/{deployment_id}/async/start",
            headers=build_test_headers(scopes="models:read,models:write"),
        )
        assert start_resp.status_code == 200, start_resp.text
        assert start_resp.json()["process_state"] == "running"

        # 创建包含 1 张正常 + 1 张触发模拟失败的批量任务
        orig_init = SqlAlchemyBatchInferenceTaskService.__init__
        fake_exec = _FakeAsyncExecutor()

        def _patched_init(self, **kwargs):
            kwargs["async_executor"] = fake_exec
            kwargs["spawn_background"] = False
            orig_init(self, **kwargs)

        with patch.object(SqlAlchemyBatchInferenceTaskService, "__init__", _patched_init):
            created = client.post(
                "/api/v1/inference-batches",
                headers=inf_headers,
                data={
                    "project_id": "project-1",
                    "task_type": "detection",
                    "deployment_instance_id": deployment_id,
                    "display_name": "mixed-batch",
                    "score_threshold": "0.25",
                },
                files=[
                    ("input_images", ("good.png", png_bytes, "image/png")),
                    ("input_images", ("bad.png", png_bytes, "image/png")),
                ],
            )
            assert created.status_code == 202, created.text
            batch_id = created.json()["batch_task_id"]

            # 运行前排队态不能删除
            conflict_del = client.delete(f"/api/v1/inference-batches/{batch_id}", headers=inf_headers)
            assert conflict_del.status_code == 409

            runner = SqlAlchemyBatchInferenceTaskService(
                session_factory=ctx.session_factory,
                dataset_storage=ctx.dataset_storage,
                queue_backend=ctx.queue_backend,
                async_executor=fake_exec,
                spawn_background=False,
            )
            finished = runner.process_batch_task(batch_id)
            assert finished.state == "partial_failed"
            assert finished.succeeded_items == 1
            assert finished.failed_items == 1

        items_resp = client.get(f"/api/v1/inference-batches/{batch_id}/items", headers=read_headers)
        assert items_resp.status_code == 200
        items = items_resp.json()
        assert len(items) == 2
        good_item = next(item for item in items if item["input_label"] == "good.png")
        bad_item = next(item for item in items if item["input_label"] == "bad.png")
        assert good_item["state"] == "succeeded"
        assert good_item["item_count"] == 1
        assert bad_item["state"] == "failed"

        item_result = client.get(
            f"/api/v1/inference-batches/{batch_id}/items/{good_item['item_id']}/result",
            headers=read_headers,
        )
        assert item_result.status_code == 200
        assert item_result.json()["file_status"] == "ready"
        assert item_result.json()["payload"]["detections"][0]["class_name"] == "bolt"

        item_img = client.get(
            f"/api/v1/inference-batches/{batch_id}/items/{good_item['item_id']}/image",
            headers=read_headers,
            params={"kind": "input"},
        )
        assert item_img.status_code == 200
        assert item_img.content == png_bytes

        # 终态删除清理
        deleted = client.delete(f"/api/v1/inference-batches/{batch_id}", headers=inf_headers)
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/inference-batches/{batch_id}", headers=read_headers).status_code == 404


def test_batch_inference_supports_sync_channel_without_retry_on_busy(
    tmp_path: Path,
) -> None:
    """验证仅 sync 通道启动时支持批量推理，且遇 deployment_inference_busy 零自动重试直接记失败。"""

    ctx = create_api_test_context(tmp_path, database_name="records.db")
    sync_supervisor = FakeDeploymentProcessSupervisor(
        runtime_mode="sync",
        dataset_storage_root_dir=ctx.dataset_storage.root_dir,
    )
    async_supervisor = FakeDeploymentProcessSupervisor(
        runtime_mode="async",
        dataset_storage_root_dir=ctx.dataset_storage.root_dir,
    )
    ctx.client.app.state.detection_sync_deployment_process_supervisor = sync_supervisor
    ctx.client.app.state.detection_async_deployment_process_supervisor = async_supervisor

    model_version_id = _seed_detection_model_version(
        session_factory=ctx.session_factory,
        dataset_storage=ctx.dataset_storage,
    )
    png_bytes = _make_png_bytes(64, 64)

    class _BusyOnceSyncSupervisor(FakeDeploymentProcessSupervisor):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.call_uris: list[str] = []

        def run_inference(self, *, config, request):
            uri = str(getattr(request, "input_uri", "") or "")
            self.call_uris.append(uri)
            if "busy" in uri:
                raise ServiceError(
                    code="deployment_inference_busy",
                    message="当前同步推理实例均繁忙",
                    status_code=503,
                )
            return super().run_inference(config=config, request=request)

    busy_sync = _BusyOnceSyncSupervisor(
        runtime_mode="sync",
        dataset_storage_root_dir=ctx.dataset_storage.root_dir,
    )
    ctx.client.app.state.detection_sync_deployment_process_supervisor = busy_sync

    with ctx.client as client:
        deployment_id = _create_detection_deployment(client, model_version_id)
        inf_headers = build_test_headers(scopes="models:read,tasks:write")
        read_headers = build_test_headers(scopes="tasks:read")

        # 仅启动 sync 通道，async 保持 stopped
        start_sync = client.post(
            f"/api/v1/models/detection/deployment-instances/{deployment_id}/sync/start",
            headers=build_test_headers(scopes="models:read,models:write"),
        )
        assert start_sync.status_code == 200, start_sync.text
        assert start_sync.json()["process_state"] == "running"

        # 显式指定未启动的 async 通道时必须明确拒绝
        rejected_async = client.post(
            "/api/v1/inference-batches",
            headers=inf_headers,
            data={
                "project_id": "project-1",
                "task_type": "detection",
                "deployment_instance_id": deployment_id,
                "runtime_mode": "async",
                "display_name": "explicit-async-rejected",
            },
            files=[("input_images", ("ok.png", png_bytes, "image/png"))],
        )
        assert rejected_async.status_code == 400

        # 默认 runtime_mode="auto" 应自动选用已运行的 sync 通道
        orig_init = SqlAlchemyBatchInferenceTaskService.__init__

        def _patched_init(self, **kwargs):
            kwargs["spawn_background"] = False
            orig_init(self, **kwargs)

        with patch.object(SqlAlchemyBatchInferenceTaskService, "__init__", _patched_init):
            created = client.post(
                "/api/v1/inference-batches",
                headers=inf_headers,
                data={
                    "project_id": "project-1",
                    "task_type": "detection",
                    "deployment_instance_id": deployment_id,
                    "runtime_mode": "auto",
                    "display_name": "sync-batch",
                },
                files=[
                    ("input_images", ("ok.png", png_bytes, "image/png")),
                    ("input_images", ("busy.png", png_bytes, "image/png")),
                ],
            )
            assert created.status_code == 202, created.text
            created_json = created.json()
            assert created_json["parameters"]["execution_runtime_mode"] == "sync"
            batch_id = created_json["batch_task_id"]

        runner = SqlAlchemyBatchInferenceTaskService(
            session_factory=ctx.session_factory,
            dataset_storage=ctx.dataset_storage,
            queue_backend=ctx.queue_backend,
            sync_supervisor=busy_sync,
            spawn_background=False,
        )
        finished = runner.process_batch_task(batch_id)
        assert finished.state == "partial_failed"
        assert finished.succeeded_items == 1
        assert finished.failed_items == 1
        # 每张图严格仅调用 1 次 sync_supervisor.run_inference（零自动重试）
        assert len(busy_sync.call_uris) == 2

        items = client.get(f"/api/v1/inference-batches/{batch_id}/items", headers=read_headers).json()
        ok_item = next(it for it in items if it["input_label"] == "ok.png")
        busy_item = next(it for it in items if it["input_label"] == "busy.png")
        assert ok_item["state"] == "succeeded"
        assert busy_item["state"] == "failed"
        assert busy_item["error_code"] == "deployment_inference_busy"

        result_resp = client.get(
            f"/api/v1/inference-batches/{batch_id}/items/{ok_item['item_id']}/result",
            headers=read_headers,
        )
        assert result_resp.status_code == 200
        assert result_resp.json()["file_status"] == "ready"
        assert len(result_resp.json()["payload"]["detections"]) >= 1
