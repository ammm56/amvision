"""模型包导入检查、类别冲突、登记详情和记录清理。"""

from pathlib import Path
from struct import unpack_from
from zipfile import ZipFile

from filelock import FileLock

from backend.contracts.models.model_package import ModelPackage
from backend.service.application.deployments.transfer_service import (
    ModelDeploymentTransferService,
)
from backend.service.infrastructure.object_store.model_package_archive import (
    file_digest,
    write_package,
)
from tests.api_test_support import build_test_headers, create_api_test_context


def exercise_import_workflow(
    tmp_path: Path, source: tuple[Path, Path] | None = None
) -> dict:
    """通过真实 HTTP 路由与 Worker 导入两个类别顺序不同的 OpenVINO 包。"""
    if not source:
        xml, weights = tmp_path / "source.xml", tmp_path / "source.bin"
        xml.write_bytes(b"<net/>")
        weights.write_bytes(b"example weights")
        source = (xml, weights)
    paths = ("0/detector.xml", "0/detector.bin")

    def create_zip(name: str, categories: list[str]) -> Path:
        """用真实 ZIP 写入器生成两份结构相同、类别顺序不同的归档。"""
        entries = []
        for index, path in enumerate(source):
            digest, size = file_digest(path)
            entries.append(
                {
                    "key": f"file-{index}",
                    "owner": "build",
                    "path": paths[index],
                    "file_type": "openvino-ir" if index == 0 else "openvino-bin",
                    "logical_name": Path(paths[index]).name,
                    "sha256": digest,
                    "byte_size": size,
                }
            )
        model_package = ModelPackage.model_validate(
            {
                "package_id": f"package-{name}",
                "source_version": "0.1.8",
                "created_at": "2026-11-19T00:00:00Z",
                "model": {
                    "model_id": "source-model",
                    "model_name": "inspection-demo",
                    "model_type": "yolo11",
                    "task_type": "detection",
                    "model_scale": "s",
                },
                "model_version": {
                    "model_version_id": f"source-{name}",
                    "metadata": {
                        "category_names": categories,
                        "input_size": {"width": 320, "height": 224},
                    },
                },
                "builds": [
                    {
                        "model_build_id": "source-build",
                        "build_format": "openvino-ir",
                        "runtime_backend": "openvino",
                        "runtime_precision": "fp32",
                    }
                ],
                "files": entries,
            }
        )
        archive = tmp_path / f"{name}.zip"
        write_package(
            archive,
            model_package,
            {entry["key"]: path for entry, path in zip(entries, source)},
        )
        return archive

    first = create_zip("initial", ["normal", "bent", "missing", "other"])
    incoming = create_zip("incoming", ["normal", "missing", "bent"])
    broken = tmp_path / "crc-damaged.zip"
    broken.write_bytes(incoming.read_bytes())
    member = f"files/build/{paths[0]}"
    with ZipFile(broken) as archive:
        offset = archive.getinfo(member).header_offset
    with broken.open("r+b") as stream:
        stream.seek(offset)
        name_size, extra_size = unpack_from("<HH", stream.read(30), 26)
        pos = offset + 30 + name_size + extra_size
        stream.seek(pos)
        byte = stream.read(1)
        stream.seek(pos)
        stream.write(bytes([byte[0] ^ 1]))

    ctx = create_api_test_context(
        tmp_path,
        database_name="import-flow.db",
        enable_local_buffer_broker=False,
        enable_queue_outbox_dispatcher=False,
    )
    svc = ModelDeploymentTransferService(ctx.session_factory, ctx.dataset_storage)
    base = "/api/v1/projects/project-1/model-packages"
    headers = build_test_headers(scopes="models:read models:write")
    try:
        with ctx.client as client:

            def read(id_: str):
                """读回只含公开字段的导入记录。"""
                response = client.get(f"{base}/{id_}", headers=headers)
                assert response.status_code == 200, response.text
                return response.json()

            def upload(path: Path):
                """完整上传、验证活动记录不可删除、再执行检查。"""
                with path.open("rb") as stream:
                    response = client.post(
                        f"{base}/imports",
                        headers=headers,
                        files={"file": (path.name, stream, "application/zip")},
                    )
                assert response.status_code == 202, response.text
                id_ = response.json()["operation_id"]
                assert (
                    client.delete(f"{base}/imports/{id_}", headers=headers).status_code
                    == 400
                )
                assert svc.run(id_)
                return read(id_)

            def analyze(row: dict, options: dict):
                """以指定目标分析类索引与架构。"""
                id_ = row["operation_id"]
                response = client.post(
                    f"{base}/imports/{id_}/analyze", headers=headers, json=options
                )
                assert response.status_code == 202, response.text
                assert svc.run(id_)
                return read(id_)

            def submit(row: dict):
                """用对应分析回执提交导入。"""
                return client.post(
                    f"{base}/imports/{row['operation_id']}/commit",
                    headers=headers,
                    json={
                        "analysis_revision": row["analysis_revision"],
                        "idempotency_key": row["analysis_revision"],
                    },
                )

            rejected = upload(broken)
            assert (
                rejected["state"] == "failed"
                and rejected["import_check"]["code"] == "crc"
            )
            assert rejected["import_check"]["member"] == member
            assert "model" not in rejected and "result" not in rejected
            assert str(tmp_path) not in str(rejected)

            initial = upload(first)
            assert initial["state"] == "ready" and initial["input_size"] == {
                "width": 320,
                "height": 224,
            }
            assert initial["uploaded_at"]
            submitted = submit(initial)
            assert submitted.status_code == 202, submitted.text
            svc.run(initial["operation_id"])
            registered = read(initial["operation_id"])
            old = registered["result"]
            checked = upload(incoming)
            conflict = analyze(checked, {"target_model_id": old["model_id"]})
            assert (
                conflict["state"] == "needs_attention"
                and not conflict["plan"]["can_import"]
            )
            issue = conflict["plan"]["issues"][0]
            assert issue["code"] == "category_order"
            assert issue["expected"] == ["normal", "bent", "missing", "other"]
            assert issue["incoming"] == ["normal", "missing", "bent"]
            assert submit(conflict).status_code == 400
            renamed = analyze(conflict, {"model_name": "inspection-new"})
            assert renamed["state"] == "ready", renamed
            submitted = submit(renamed)
            assert submitted.status_code == 202, submitted.text
            svc.run(renamed["operation_id"])
            completed = read(renamed["operation_id"])
            assert completed["registered_at"] and completed["state"] == "completed"
            assert completed["result"]["model_id"] != old["model_id"]
            assert completed["source_version_id"] == "source-incoming"

            same_labels = analyze(upload(first), {"target_model_id": old["model_id"]})
            assert same_labels["state"] == "ready"
            submitted = submit(same_labels)
            assert submitted.status_code == 202, submitted.text
            assert svc.run(same_labels["operation_id"])
            appended = read(same_labels["operation_id"])["result"]
            assert appended["model_id"] == old["model_id"]
            assert appended["model_version_id"] != old["model_version_id"]

            id_ = completed["operation_id"]
            root = svc.root(svc.get(id_))
            ctx.dataset_storage.write_bytes(f"{root}/package.writing", b"residue")
            lock = ctx.dataset_storage.resolve(f"{root}/worker.lock")
            with FileLock(str(lock)):
                assert (
                    client.delete(f"{base}/imports/{id_}", headers=headers).status_code
                    == 409
                )
                assert read(id_)["state"] == "completed"
                assert ctx.dataset_storage.resolve(f"{root}/package.writing").is_file()
            assert (
                client.delete(f"{base}/imports/{id_}", headers=headers).status_code
                == 204
            )
            assert client.get(f"{base}/{id_}", headers=headers).status_code == 404
            assert id_ not in {
                item["operation_id"]
                for item in client.get(base, headers=headers).json()
            }
            assert not ctx.dataset_storage.resolve(f"{root}/package.writing").exists()
            with svc.unit() as unit:
                for row in (old, appended, completed["result"]):
                    version = unit.models.get_model_version(row["model_version_id"])
                    assert version
                    files = unit.model_files.list_model_files(
                        model_build_id=row["model_build_ids"][0]
                    )
                    assert len(files) == 2 and all(
                        ctx.dataset_storage.resolve(file.storage_uri).is_file()
                        for file in files
                    )
            return {
                "rejected": rejected,
                "checked": checked,
                "conflict": conflict,
                "renamed": renamed,
                "registered": registered,
                "completed": completed,
            }
    finally:
        ctx.session_factory.engine.dispose()


def test_import_keeps_label_contract_and_dismiss_preserves_artifacts(tmp_path: Path):
    """类别冲突阻止追加；独立登记和删除记录都不影响已有模型。"""
    exercise_import_workflow(tmp_path)
