"""核对单个模型产物删除的引用阻止、磁盘范围和历史保留。"""

from pathlib import Path

import pytest

from backend.service.domain.deployments.deployment_runtime_configuration import (
    DeploymentRuntimeConfiguration,
    serialize_deployment_runtime_configuration,
)
from backend.service.domain.tasks.task_records import TaskRecord
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.persistence.deployment_orm import (
    DeploymentInstanceRecord,
)
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.model_orm import (
    ModelBuildRecord,
    ModelRecord,
    ModelVersionRecord,
)
from backend.workers.resource_cleanup import ResourceCleanupWorker
from tests.api_test_support import build_test_headers, create_api_test_context


@pytest.mark.parametrize("linked", [False, True])
def test_delete_model_build_preserves_other_outputs_and_history(
    tmp_path: Path, linked: bool
):
    """部署预检之后仍需复查；清理仅处理目标 XML 和权重文件。"""
    context = create_api_test_context(
        tmp_path, database_name="build-delete.db", enable_local_buffer_broker=False
    )
    factory, storage = context.session_factory, context.dataset_storage
    root = "task-runs/conversion/conversion-1"
    xml = f"{root}/artifacts/builds/model.openvino.xml"
    weights = f"{root}/artifacts/builds/model.openvino.bin"
    onnx = f"{root}/artifacts/builds/model.onnx"
    report = f"{root}/artifacts/conversion-report.json"
    checkpoint = "task-runs/training/training-1/checkpoints/best.pt"
    headers = build_test_headers(scopes="models:read models:write tasks:read")
    try:
        with context.client as client:
            for key in (xml, weights, onnx, report, checkpoint):
                storage.write_bytes(key, key.encode())
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                session.add(
                    ModelRecord(
                        model_id="m1",
                        project_id="project-1",
                        owner_key="project-1",
                        scope_kind="project",
                        model_name="example",
                        model_type="yolo11",
                        task_type="detection",
                        model_scale="s",
                    )
                )
                unit.flush()
                session.add(
                    ModelVersionRecord(
                        model_version_id="v1",
                        model_id="m1",
                        source_kind="training-output",
                        version_number=1,
                        training_task_id="training-1",
                        file_ids_json=["file-pt"],
                    )
                )
                unit.flush()
                for artifact, format_, path, metadata in (
                    ("ir", "openvino-ir", xml, {"weights_object_uri": weights}),
                    ("onnx", "onnx", onnx, {}),
                ):
                    session.add(
                        ModelBuildRecord(
                            model_build_id=artifact,
                            model_id="m1",
                            source_model_version_id="v1",
                            build_format=format_,
                            runtime_backend=format_,
                            runtime_precision="fp32",
                            conversion_task_id="conversion-1",
                            file_ids_json=[f"file-{artifact}"],
                            metadata_json=metadata,
                        )
                    )
                    session.add(
                        ModelFileRecord(
                            file_id=f"file-{artifact}",
                            project_id="project-1",
                            scope_kind="project",
                            model_id="m1",
                            file_type=format_,
                            logical_name=f"model-{artifact}",
                            storage_uri=path,
                            model_build_id=artifact,
                        )
                    )
                session.add(
                    ModelFileRecord(
                        file_id="file-pt",
                        project_id="project-1",
                        scope_kind="project",
                        model_id="m1",
                        file_type="pytorch",
                        logical_name="best.pt",
                        storage_uri=checkpoint,
                        model_version_id="v1",
                    )
                )
                unit.tasks.save_task(
                    TaskRecord(
                        task_id="training-1",
                        project_id="project-1",
                        state="succeeded",
                        task_kind="detection-training",
                    )
                )
                unit.tasks.save_task(
                    TaskRecord(
                        task_id="conversion-1",
                        project_id="project-1",
                        state="succeeded",
                        task_kind="detection-conversion",
                    )
                )
                unit.commit()

            params = {
                "kind": "model-build",
                "resource_id": "ir",
                "project_id": "project-1",
            }
            url = "/api/v1/resource-deletions"
            preview = client.get(f"{url}/preview", params=params, headers=headers)
            assert preview.status_code == 200, preview.text
            assert preview.json()["deleted_models"] == [
                {"kind": "model-build", "resource_id": "ir"}
            ]
            assert client.post(url, headers=headers, json=params).status_code == 400

            with factory.create_session() as session:
                bindings = [("other-build", "onnx")]
                if linked:
                    bindings.append(("late-binding", "ir"))
                configuration = serialize_deployment_runtime_configuration(
                    DeploymentRuntimeConfiguration()
                )
                for deployment_id, build_id in bindings:
                    session.add(
                        DeploymentInstanceRecord(
                            deployment_instance_id=deployment_id,
                            model_build_id=build_id,
                            project_id="project-1",
                            model_id="m1",
                            model_version_id="v1",
                            runtime_backend="onnxruntime",
                            device_name="cpu",
                            runtime_configuration_json=configuration,
                            status="stopped",
                            display_name=deployment_id,
                            created_at="2026-01-01",
                            updated_at="2026-01-01",
                        )
                    )
                session.commit()
            references = client.get(
                "/api/v1/models/catalog/m1/versions/v1/references",
                params={"project_id": "project-1", "model_build_id": "ir"},
                headers=headers,
            )
            assert references.status_code == 200, references.text
            assert references.json()["total"] == int(linked)
            if linked:
                item = references.json()["items"][0]
                assert item["deployment_id"] == "late-binding" and item[
                    "runtime_states"
                ] == {"instance": "stopped"}
            result = client.post(
                url,
                headers=headers,
                json={**params, "expected_revision": preview.json()["revision"]},
            )
            assert result.status_code == (409 if linked else 202), result.text
            if linked:
                blocked = client.get(f"{url}/preview", params=params, headers=headers)
                assert blocked.json()["blocked"] and "late-binding" not in blocked.text
                assert "late-binding" not in result.text
            else:
                assert ResourceCleanupWorker(
                    session_factory=factory,
                    dataset_storage=storage,
                    queue_backend=context.queue_backend,
                    worker_id="build-delete-test",
                ).run_once()
                status = client.get(
                    f"{url}/{result.json()['operation_id']}", headers=headers
                )
                assert status.json()["state"] == "completed"
            assert storage.resolve(xml).exists() == linked
            assert storage.resolve(weights).exists() == linked
            for key in (onnx, report, checkpoint):
                assert storage.resolve(key).read_bytes() == key.encode()
            with factory.create_session() as session:
                unit = SqlAlchemyUnitOfWork(session)
                assert (session.get(ModelBuildRecord, "ir") is not None) == linked
                assert (session.get(ModelFileRecord, "file-ir") is not None) == linked
                assert session.get(ModelBuildRecord, "onnx") is not None
                assert session.get(ModelVersionRecord, "v1") is not None
                assert unit.tasks.get_task("conversion-1") is not None
                assert unit.tasks.get_task("training-1") is not None
    finally:
        factory.engine.dispose()
