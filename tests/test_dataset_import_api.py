"""数据集 zip 导入 API 行为测试。"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from backend.service.api.app import create_app
from backend.service.infrastructure.db.session import DatabaseSettings, SessionFactory
from backend.service.infrastructure.db.unit_of_work import SqlAlchemyUnitOfWork
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)
from backend.service.infrastructure.persistence.base import Base


def test_import_dataset_zip_creates_coco_dataset_version(tmp_path: Path) -> None:
    """验证导入 COCO zip 会创建 DatasetImport、DatasetVersion 和本地目录。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["format_type"] == "coco"
        assert payload["status"] == "completed"
        assert payload["sample_count"] == 1
        assert payload["category_count"] == 1
        assert payload["split_names"] == ["train"]

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
            dataset_version_id=payload["dataset_version_id"],
        )

        assert dataset_import is not None
        assert dataset_import.status == "completed"
        assert dataset_import.format_type == "coco"
        assert dataset_import.detected_profile["format_type"] == "coco"
        assert dataset_version is not None
        assert dataset_version.metadata["source_import_id"] == payload["dataset_import_id"]
        assert dataset_version.samples[0].annotations[0].bbox_xywh == (1.0, 2.0, 3.0, 4.0)
        assert dataset_version.categories[0].category_id == 0

        assert dataset_storage.resolve(payload["package_path"]).is_file()
        assert dataset_storage.resolve(payload["staging_path"]).is_dir()
        assert dataset_storage.resolve(payload["version_path"]).is_dir()

        sample = dataset_version.samples[0]
        sample_manifest_path = dataset_storage.resolve(
            f"{payload['version_path']}/samples/train/{sample.sample_id}.json"
        )
        sample_manifest = json.loads(sample_manifest_path.read_text(encoding="utf-8"))
        assert sample_manifest["image_object_key"].endswith("images/train/train-1.jpg")
        assert sample_manifest["annotations"][0]["category_id"] == 0
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_creates_voc_dataset_version(tmp_path: Path) -> None:
    """验证导入 Pascal VOC zip 会完成 bbox 转换并写入版本目录。"""

    client, session_factory, dataset_storage = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-2",
                    "format_type": "voc",
                },
                files={
                    "package": ("voc-dataset.zip", _build_voc_zip_bytes(), "application/zip"),
                },
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["format_type"] == "voc"
        assert payload["status"] == "completed"
        assert payload["sample_count"] == 1
        assert payload["split_names"] == ["train"]

        dataset_import, dataset_version = _load_dataset_objects(
            session_factory=session_factory,
            dataset_import_id=payload["dataset_import_id"],
            dataset_version_id=payload["dataset_version_id"],
        )

        assert dataset_import is not None
        assert dataset_import.validation_report["format_type"] == "voc"
        assert dataset_version is not None
        assert dataset_version.samples[0].annotations[0].bbox_xywh == (10.0, 20.0, 20.0, 30.0)
        assert dataset_version.categories[0].name == "bolt"

        validation_report = json.loads(
            dataset_storage.resolve(
                f"projects/project-1/datasets/dataset-2/imports/{payload['dataset_import_id']}/logs/validation-report.json"
            ).read_text(encoding="utf-8")
        )
        assert validation_report["status"] == "ok"
    finally:
        session_factory.engine.dispose()


def test_import_dataset_zip_accepts_nested_voc_wrapper_dirs(tmp_path: Path) -> None:
    """验证导入器可以识别带多层包裹目录和非整数标记的 Pascal VOC zip。"""

    client, session_factory, _dataset_storage = _create_test_client(tmp_path)
    try:
        with client:
            response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-3",
                    "format_type": "voc",
                },
                files={
                    "package": (
                        "voc-nested.zip",
                        _build_voc_zip_bytes(
                            with_nested_wrappers=True,
                            use_unspecified_flags=True,
                        ),
                        "application/zip",
                    ),
                },
            )

        assert response.status_code == 201
        payload = response.json()
        assert payload["format_type"] == "voc"
        assert payload["status"] == "completed"
        assert payload["sample_count"] == 1
    finally:
        session_factory.engine.dispose()


def test_get_dataset_import_detail_returns_validation_report_and_version_relation(
    tmp_path: Path,
) -> None:
    """验证可以按导入记录 id 读取校验报告和关联版本摘要。"""

    client, session_factory, _dataset_storage = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 201
            dataset_import_id = create_response.json()["dataset_import_id"]

            detail_response = client.get(
                f"/api/v1/datasets/imports/{dataset_import_id}",
                headers=_build_dataset_read_headers(),
            )

        assert detail_response.status_code == 200
        payload = detail_response.json()
        assert payload["dataset_import_id"] == dataset_import_id
        assert payload["validation_report"]["status"] == "ok"
        assert payload["detected_profile"]["format_type"] == "coco"
        assert payload["dataset_version"]["dataset_version_id"] == payload["dataset_version_id"]
        assert payload["dataset_version"]["sample_count"] == 1
        assert payload["dataset_version"]["category_count"] == 1
        assert payload["dataset_version"]["split_names"] == ["train"]
        assert payload["dataset_version"]["metadata"]["source_import_id"] == dataset_import_id
    finally:
        session_factory.engine.dispose()


def test_list_dataset_imports_returns_dataset_import_summaries(tmp_path: Path) -> None:
    """验证可以按 Dataset id 列出导入记录摘要。"""

    client, session_factory, _dataset_storage = _create_test_client(tmp_path)
    try:
        with client:
            create_response = client.post(
                "/api/v1/datasets/imports",
                headers=_build_dataset_write_headers(),
                data={
                    "project_id": "project-1",
                    "dataset_id": "dataset-1",
                },
                files={
                    "package": ("coco-dataset.zip", _build_coco_zip_bytes(), "application/zip"),
                },
            )
            assert create_response.status_code == 201

            list_response = client.get(
                "/api/v1/datasets/dataset-1/imports",
                headers=_build_dataset_read_headers(),
            )

        assert list_response.status_code == 200
        payload = list_response.json()
        assert len(payload) == 1
        assert payload[0]["dataset_id"] == "dataset-1"
        assert payload[0]["status"] == "completed"
        assert payload[0]["validation_status"] == "ok"
        assert payload[0]["dataset_version_id"] is not None
    finally:
        session_factory.engine.dispose()


def _create_test_client(tmp_path: Path) -> tuple[TestClient, SessionFactory, LocalDatasetStorage]:
    """创建绑定内存 SQLite 和临时本地文件存储的测试客户端。

    参数：
    - tmp_path：当前测试使用的临时目录。

    返回：
    - TestClient、SessionFactory 和 LocalDatasetStorage。
    """

    database_path = tmp_path / "amvision-test.db"
    session_factory = SessionFactory(DatabaseSettings(url=f"sqlite:///{database_path.as_posix()}"))
    Base.metadata.create_all(session_factory.engine)
    dataset_storage = LocalDatasetStorage(
        DatasetStorageSettings(root_dir=str(tmp_path / "dataset-files"))
    )
    client = TestClient(
        create_app(session_factory=session_factory, dataset_storage=dataset_storage)
    )

    return client, session_factory, dataset_storage


def _load_dataset_objects(
    *,
    session_factory: SessionFactory,
    dataset_import_id: str,
    dataset_version_id: str,
) -> tuple[object | None, object | None]:
    """读取导入结果在数据库中的持久化对象。

    参数：
    - session_factory：数据库会话工厂。
    - dataset_import_id：导入记录 id。
    - dataset_version_id：版本 id。

    返回：
    - DatasetImport 和 DatasetVersion。
    """

    unit_of_work = SqlAlchemyUnitOfWork(session_factory.create_session())
    try:
        dataset_import = unit_of_work.dataset_imports.get_dataset_import(dataset_import_id)
        dataset_version = unit_of_work.datasets.get_dataset_version(dataset_version_id)
        return dataset_import, dataset_version
    finally:
        unit_of_work.close()


def _build_dataset_write_headers() -> dict[str, str]:
    """构建具备 datasets:write scope 的测试请求头。

    返回：
    - 测试请求头字典。
    """

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:write",
    }


def _build_dataset_read_headers() -> dict[str, str]:
    """构建具备 datasets:read scope 的测试请求头。

    返回：
    - 测试请求头字典。
    """

    return {
        "x-amvision-principal-id": "user-1",
        "x-amvision-project-ids": "project-1",
        "x-amvision-scopes": "datasets:read",
    }


def _build_coco_zip_bytes() -> bytes:
    """构建一个最小 COCO detection zip 数据集。"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as zip_file:
        coco_payload = {
            "images": [
                {
                    "id": 1,
                    "file_name": "train-1.jpg",
                    "width": 100,
                    "height": 80,
                }
            ],
            "annotations": [
                {
                    "id": 11,
                    "image_id": 1,
                    "category_id": 7,
                    "bbox": [1, 2, 3, 4],
                    "area": 12,
                }
            ],
            "categories": [{"id": 7, "name": "bolt"}],
        }
        zip_file.writestr(
            "dataset-root/annotations/instances_train.json",
            json.dumps(coco_payload),
        )
        zip_file.writestr("dataset-root/train/train-1.jpg", b"fake-image")

    return buffer.getvalue()


def _build_voc_zip_bytes(
        *,
        with_nested_wrappers: bool = False,
        use_unspecified_flags: bool = False,
) -> bytes:
        """构建一个最小 Pascal VOC detection zip 数据集。"""

        buffer = io.BytesIO()
        truncated_value = "Unspecified" if use_unspecified_flags else "0"
        difficult_value = "Unspecified" if use_unspecified_flags else "0"
        xml_payload = """<annotation>
<folder>JPEGImages</folder>
<filename>voc-1.jpg</filename>
<size><width>120</width><height>90</height><depth>3</depth></size>
<object>
    <name>bolt</name>
    <pose>Unspecified</pose>
    <truncated>{truncated_value}</truncated>
    <difficult>{difficult_value}</difficult>
    <bndbox>
        <xmin>10</xmin>
        <ymin>20</ymin>
        <xmax>30</xmax>
        <ymax>50</ymax>
    </bndbox>
</object>
</annotation>""".format(
                truncated_value=truncated_value,
                difficult_value=difficult_value,
        )
        with zipfile.ZipFile(buffer, mode="w") as zip_file:
                prefix = "dataset-root/VOC2007/" if with_nested_wrappers else ""
                zip_file.writestr(f"{prefix}JPEGImages/voc-1.jpg", b"fake-image")
                zip_file.writestr(f"{prefix}Annotations/voc-1.xml", xml_payload)
                zip_file.writestr(f"{prefix}ImageSets/Main/train.txt", "voc-1\n")

        return buffer.getvalue()