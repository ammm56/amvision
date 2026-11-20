"""验证模型包生成事实、ZIP 可用性及原选项重新生成。"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.service.application.deployments.transfer_service import (
    ModelDeploymentTransferService,
)
from backend.service.infrastructure.persistence.model_file_orm import ModelFileRecord
from backend.service.infrastructure.persistence.model_orm import (
    ModelBuildRecord,
    ModelRecord,
    ModelVersionRecord,
)
from tests.api_test_support import build_test_headers, create_api_test_context


def exercise_model_package_export(
    tmp_path: Path, source: tuple[Path, Path] | None = None
):
    """运行真实独立导出和清理服务；可使用实际转换得到的 XML 和 BIN。"""
    ctx = create_api_test_context(
        tmp_path,
        database_name="export.db",
        enable_local_buffer_broker=False,
        enable_queue_outbox_dispatcher=False,
    )
    svc = ModelDeploymentTransferService(ctx.session_factory, ctx.dataset_storage)
    headers = build_test_headers(scopes="models:read models:write")
    base = "/api/v1/projects/project-1/model-packages"
    xml = "task-runs/conversion/c1/artifacts/builds/compiled.openvino.xml"
    bin_ = xml.removesuffix(".xml") + ".bin"
    options = {
        "model_version_id": "v1",
        "include_checkpoint": False,
        "build_ids": ["build-ir"],
        "file_name": "inspection-worker.zip",
    }
    try:
        with ctx.client as client:
            ctx.dataset_storage.write_bytes(
                xml, source[0].read_bytes() if source else b"<net/>"
            )
            weights = source[1].read_bytes() if source else b"example weights"
            ctx.dataset_storage.write_bytes(bin_, weights)
            with svc.unit() as unit:
                unit.session.add(
                    ModelRecord(
                        model_id="m1",
                        project_id="project-1",
                        owner_key="project-1",
                        scope_kind="project",
                        model_name="inspection-worker",
                        model_type="yolo11",
                        task_type="detection",
                        model_scale="s",
                    )
                )
                unit.flush()
                unit.session.add(
                    ModelVersionRecord(
                        model_version_id="v1",
                        model_id="m1",
                        source_kind="training-output",
                        version_number=1,
                        file_ids_json=[],
                        metadata_json={"category_names": ["component"]},
                    )
                )
                unit.flush()
                unit.session.add(
                    ModelBuildRecord(
                        model_build_id="build-ir",
                        model_id="m1",
                        source_model_version_id="v1",
                        build_format="openvino-ir",
                        runtime_backend="openvino",
                        runtime_precision="fp32",
                        conversion_task_id="c1",
                        file_ids_json=["file-ir"],
                        metadata_json={"weights_object_uri": bin_},
                    )
                )
                unit.session.add(
                    ModelFileRecord(
                        file_id="file-ir",
                        model_id="m1",
                        project_id="project-1",
                        scope_kind="project",
                        model_build_id="build-ir",
                        file_type="openvino-ir",
                        logical_name="compiled.openvino.xml",
                        storage_uri=xml,
                    )
                )
                unit.commit()

            def export():
                response = client.post(f"{base}/exports", headers=headers, json=options)
                assert response.status_code == 202, response.text
                row = response.json()
                assert row["state"] == "pending_export" and "file_state" not in row
                assert row["export_options"] == options
                svc.run(row["operation_id"])
                return row["operation_id"]

            def read(op_id: str):
                response = client.get(f"{base}/{op_id}", headers=headers)
                assert response.status_code == 200, response.text
                return response.json()

            def download(op_id: str):
                return client.get(f"{base}/exports/{op_id}/download", headers=headers)

            op_id = export()
            done = read(op_id)
            assert done["state"] == "completed" and done["file_state"] == "available", (
                done
            )
            assert {entry["path"] for entry in done["files"]} == {
                "0/compiled.openvino.xml",
                "0/compiled.openvino.bin",
            }
            response = download(op_id)
            assert (
                response.status_code == 200
                and len(response.content) == done["total_bytes"]
            )

            archive = ctx.dataset_storage.resolve(
                f"{svc.root(svc.get(op_id))}/package.zip"
            )
            archive.write_bytes(b"truncated")
            assert read(op_id)["file_state"] == "unavailable"
            assert download(op_id).status_code == 404
            archive.unlink()
            missing = read(op_id)
            assert (
                missing["state"] == "completed" and missing["file_state"] == "missing"
            )
            assert download(op_id).status_code == 404

            archive.write_bytes(response.content)
            finished = datetime.now(timezone.utc) - timedelta(days=2)
            generated = finished.isoformat()
            with svc.unit() as unit:
                unit.model_transfers.get(op_id).created_at = (
                    finished - timedelta(minutes=1)
                ).isoformat()
                unit.commit()
            svc.update(op_id, export_completed_at=generated)
            svc.maintenance()
            cleaned = read(op_id)
            assert not archive.exists()
            assert svc.get(op_id)["state"] == "completed"
            assert (
                cleaned["state"] == "completed" and cleaned["file_state"] == "cleaned"
            )
            assert (
                cleaned["completed_at"] == generated
                and cleaned["total_bytes"] == done["total_bytes"]
            )
            assert (
                cleaned["files"] == done["files"]
                and cleaned["export_options"] == options
            )
            rows = client.get(base, headers=headers).json()
            assert (
                rows[0]["file_state"] == "cleaned" and rows[0]["state"] == "completed"
            )
            updated_at = cleaned["updated_at"]
            svc.maintenance()
            assert read(op_id)["updated_at"] == updated_at

            new_id = export()
            assert new_id != op_id and read(new_id)["file_state"] == "available"
            assert read(op_id)["file_state"] == "cleaned"
            ctx.dataset_storage.resolve(bin_).unlink()
            failed = read(export())
            assert (
                failed["state"] == "failed"
                and "compiled.openvino.bin" in failed["error"]
            )
            assert failed["export_failure_code"] == "source_invalid"
            assert "file_state" not in failed
            svc.update(
                failed["operation_id"],
                export_failure_code=None,
                error="private-path-marker",
            )
            assert "private-path-marker" not in read(failed["operation_id"])["error"]
            ctx.dataset_storage.write_bytes(bin_, weights)

            # 兼容由旧 Worker 标记为 expired 的、可证明已完成的记录。
            svc.update(op_id, "expired", file_cleaned_at=None, export_completed_at=None)
            old = read(op_id)
            assert old["state"] == "completed" and old["file_state"] == "cleaned"
            assert "completed_at" not in old
            assert (
                ctx.dataset_storage.resolve(xml).is_file()
                and ctx.dataset_storage.resolve(bin_).is_file()
            )
            with svc.unit() as unit:
                assert (
                    unit.models.get_model_version("v1") is not None
                    and unit.models.get_model_build("build-ir") is not None
                )
            return done, cleaned, failed, read(new_id)
    finally:
        ctx.session_factory.engine.dispose()


def test_export_separates_completion_and_file_availability(tmp_path: Path):
    """读回和下载响应遵循真实文件；清理不重写任务终态。"""
    exercise_model_package_export(tmp_path)
