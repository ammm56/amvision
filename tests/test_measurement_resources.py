"""计量资源的版本隔离、项目归属、损坏和引用保护测试。"""

import hashlib
from io import BytesIO
from zipfile import ZipFile

import cv2
import numpy as np
import pytest

from backend.contracts.workflows.measurement_resources import MeasurementResourceContent
from backend.service.application.errors import (
    InvalidRequestError,
    ResourceConflictError,
    ResourceInUseError,
    ResourceNotFoundError,
)
from backend.service.application.workflows.documents.measurement_resources import (
    MeasurementResourceService,
    PreparedMeasurementResources,
    reference_key,
)
from backend.service.infrastructure.object_store.local_dataset_storage import (
    DatasetStorageSettings,
    LocalDatasetStorage,
)


@pytest.fixture
def service(tmp_path):
    """隔离存储，不改用户资源和工作流。"""
    return MeasurementResourceService(
        LocalDatasetStorage(DatasetStorageSettings(root_dir=str(tmp_path / "store")))
    )


def calibration():
    """固定平面孔距配置，通用资源不依赖连接器字段。"""
    return MeasurementResourceContent(
        kind="planar-calibration",
        calibration=dict(
            image_width=1280,
            image_height=800,
            model="similarity",
            world_from_image=((0.1, 0, 0), (0, 0.1, 0), (0, 0, 1)),
            unit="millimeter",
            plane_id="flat-plane",
            valid_polygon=((0, 0), (1279, 0), (1279, 799), (0, 799)),
            fit_rms=0.0,
            validation_max_error=0.01,
        ),
    )


def test_version_content_isolation_archive_and_tombstone(service):
    """资源旧版本不变；跨项目导入重建引用，删除后不复用版本号。"""
    first = service.save(project_id="test", name="Plane", content=calibration())
    second = service.save(
        project_id="test",
        name="Plane renamed",
        content=calibration(),
        resource_id=first.reference.resource_id,
    )
    assert (first.reference.version, second.reference.version) == (1, 2)
    assert service.read(first.reference, project_id="test") == first
    with pytest.raises(InvalidRequestError):
        service.read(first.reference, project_id="other")
    imported = service.import_archive(
        service.export(first.reference, project_id="test"),
        project_id="other",
        name="Imported",
    )
    assert imported.reference.project_id == "other"
    assert imported.reference.sha256 == first.reference.sha256
    service.delete(second.reference, project_id="test")
    with pytest.raises(ResourceNotFoundError):
        service.read(second.reference, project_id="test")
    third = service.save(
        project_id="test",
        name="Plane",
        content=calibration(),
        resource_id=first.reference.resource_id,
    )
    assert third.reference.version == 3
    assert len(service.list_versions(project_id="test")) == 2


def test_corruption_scope_lock_and_prepared_cache(service, monkeypatch):
    """一次准备后复用只读版本；内容损坏在新准备时失败，冲突不等待。"""
    document = service.save(project_id="test", name="Plane", content=calibration())
    cache = PreparedMeasurementResources(service.storage)
    result = cache.prepare((document.reference,), project_id="test")
    monkeypatch.setattr(
        cache.service, "read", lambda *a, **kw: pytest.fail("hot path must not read")
    )
    assert (
        cache.prepare((document.reference,), project_id="test")[
            reference_key(document.reference)
        ]
        is result[reference_key(document.reference)]
    )
    with pytest.raises(TypeError):
        result["bad"] = "mutable"
    with pytest.raises(InvalidRequestError):
        cache.prepare((document.reference,), project_id="wrong")
    with service.mutation("test"), pytest.raises(ResourceConflictError):
        service.save(project_id="test", name="Busy", content=calibration())
    path = service.storage.resolve(service.version_key(document.reference))
    path.write_bytes(path.read_bytes().replace(b"0.01", b"0.02"))
    with pytest.raises(InvalidRequestError):
        PreparedMeasurementResources(service.storage).prepare(
            (document.reference,), project_id="test"
        )


def test_template_binary_hash_decode_and_zip_validation(service):
    """参考图独立存储校验；非法归档不落地客户端路径。"""
    _, image = cv2.imencode(".png", np.arange(4096, dtype=np.uint8).reshape(64, 64))
    image = image.tobytes()
    content = MeasurementResourceContent(
        kind="localization-template",
        template=dict(
            reference_id="holes",
            image_width=64,
            image_height=64,
            template_roi=(8, 8, 32, 32),
            anchor=(24, 24),
            image_sha256=hashlib.sha256(image).hexdigest(),
        ),
    )
    document = service.save(
        project_id="test", name="Holes", content=content, image_bytes=image
    )
    assert (
        service.image_bytes(service.read(document.reference, project_id="test"))
        == image
    )
    cache = PreparedMeasurementResources(service.storage)
    matrix = cache.prepare((document.reference,), project_id="test")[
        reference_key(document.reference)
    ]["image"]
    assert matrix.shape == (64, 64) and not matrix.flags.writeable
    with pytest.raises(InvalidRequestError):
        service.save(
            project_id="test", name="Wrong", content=content, image_bytes=image + b"x"
        )
    restored = service.import_archive(
        service.export(document.reference, project_id="test"),
        project_id="other",
        name="Restored",
    )
    assert restored.reference.sha256 == document.reference.sha256
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("../resource.json", "{}")
    with pytest.raises(InvalidRequestError):
        service.import_archive(buffer.getvalue(), project_id="test", name="Bad")
    with pytest.raises(InvalidRequestError):
        service.import_archive(b"not a zip", project_id="test", name="Bad")


def test_saved_template_blocks_resource_deletion(service):
    """草稿、已发布快照采用相同显式引用检查；不忽略损坏文档。"""
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate

    document = service.save(project_id="test", name="Plane", content=calibration())
    template = WorkflowGraphTemplate(
        template_id="test",
        template_version="1",
        display_name="Test",
        nodes=[
            dict(
                node_id="measure",
                node_type_id="custom.connector.measure",
                parameters={
                    "items": [
                        dict(item_id="width", kind="width", pin_a="P1", section=10)
                    ],
                    "calibration_resource": document.reference.model_dump(mode="json"),
                    "unit": "millimeter",
                },
            )
        ],
    )
    # 本测试在参数 Schema 接入之前也验证引用保护，不绕过资源内容验证。
    service.storage.write_json(
        "workflows/projects/test/templates/test/versions/1/template.json",
        template.model_dump(mode="json"),
    )
    with pytest.raises(ResourceInUseError):
        service.delete(document.reference, project_id="test")
    assert service.read(document.reference, project_id="test") == document


def test_management_api_permissions_and_roundtrip(tmp_path):
    """通过真实 FastAPI 管理接口保存、读取、导出和删除隔离资源。"""
    from tests.api_test_support import build_test_headers
    from tests.test_workflow_runtime_invoke_api import _create_runtime_api_client

    client, factory, _ = _create_runtime_api_client(
        tmp_path, database_name="measurement-api.db", enable_local_buffer_broker=False
    )
    headers = build_test_headers(scopes="workflows:read,workflows:write")
    base = "/api/v1/workflows/projects/project-1/measurement-resources"
    try:
        with client:
            created = client.post(
                base,
                headers=headers,
                data={"name": "Plane", "content": calibration().model_dump_json()},
            )
            assert created.status_code == 201, created.text
            ref = created.json()["reference"]
            path = f"{base}/{ref['resource_id']}/versions/{ref['version']}"
            assert client.get(path, headers=headers).json() == created.json()
            assert len(client.get(base, headers=headers).json()) == 1
            from backend.service.api.deps.auth import (
                AuthenticatedPrincipal,
                get_optional_principal,
            )

            client.app.dependency_overrides[get_optional_principal] = lambda: (
                AuthenticatedPrincipal(
                    principal_id="test-reader",
                    principal_type="user",
                    scopes=("workflows:read",),
                    project_ids=("project-1",),
                )
            )
            try:
                assert client.delete(path, headers=headers).status_code == 403
            finally:
                client.app.dependency_overrides.pop(get_optional_principal)
            exported = client.get(path + "/export", headers=headers)
            assert exported.status_code == 200, exported.text
            imported = client.post(
                base + "/import",
                headers=headers,
                data={"name": "Imported"},
                files={
                    "archive": ("resource.zip", exported.content, "application/zip")
                },
            )
            assert imported.status_code == 201, imported.text
            assert imported.json()["reference"]["sha256"] == ref["sha256"]
            assert client.delete(path, headers=headers).status_code == 204
            assert client.get(path, headers=headers).status_code == 404
    finally:
        factory.engine.dispose()


def test_delete_unreferenced_resource_preserves_unrelated_template(service):
    """遍历引用不能覆盖删除目标变量；无关 Workflow 文件必须逐字保持原状。"""
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate

    saved = service.save(project_id="test", name="Plane", content=calibration())
    template = WorkflowGraphTemplate(
        template_id="unrelated",
        template_version="1",
        display_name="Unrelated",
        nodes=[{"node_id": "unrelated", "node_type_id": "core.value.create-object"}],
    )
    key = "workflows/projects/test/templates/unrelated/versions/1/template.json"
    service.storage.write_json(key, template.model_dump(mode="json"))
    before = service.storage.resolve(key).read_bytes()
    service.delete(saved.reference, project_id="test")
    assert service.storage.resolve(key).read_bytes() == before
    with pytest.raises(ResourceNotFoundError):
        service.get_version(
            project_id="test", resource_id=saved.reference.resource_id, version=1
        )
    next_version = service.save(
        project_id="test",
        resource_id=saved.reference.resource_id,
        name="Plane",
        content=calibration(),
    )
    assert next_version.reference.version == 2


def test_delete_recovers_after_file_sharing_violation(service, monkeypatch):
    """Windows 文件占用不会丢失待清理的版本身份；同一删除请求可继续完成。"""
    _, image = cv2.imencode(".png", np.arange(4096, dtype=np.uint8).reshape(64, 64))
    image = image.tobytes()
    content = MeasurementResourceContent(
        kind="localization-template",
        template=dict(
            reference_id="holes",
            image_width=64,
            image_height=64,
            template_roi=(8, 8, 32, 32),
            anchor=(24, 24),
            image_sha256=hashlib.sha256(image).hexdigest(),
        ),
    )
    saved = service.save(
        project_id="test", name="Holes", content=content, image_bytes=image
    )
    original = type(service.storage).delete_tree
    with monkeypatch.context() as patch:

        def denied(*args, **kwargs):
            raise PermissionError(5, "file is in use")

        patch.setattr(type(service.storage), "delete_tree", denied)
        from backend.service.application.errors import PersistenceOperationError

        with pytest.raises(PersistenceOperationError) as failure:
            service.delete(saved.reference, project_id="test")
        assert failure.value.details["errno"] == 5
    with pytest.raises(ResourceNotFoundError):
        service.get_version(
            project_id="test", resource_id=saved.reference.resource_id, version=1
        )
    pending = service.get_version(
        project_id="test",
        resource_id=saved.reference.resource_id,
        version=1,
        include_deleted=True,
    )
    assert pending.reference == saved.reference
    assert type(service.storage).delete_tree == original
    service.delete(pending.reference, project_id="test")
    assert not service.storage.resolve(saved.image_object_key).exists()


@pytest.mark.parametrize(
    "identifier", ["../other", "name:stream", "NUL", "COM1.txt", "trailing."]
)
def test_resource_paths_reject_windows_aliases(service, identifier):
    """路径 ID 不能逃出资源根、引用设备名称或 NTFS 附加数据流。"""
    with pytest.raises(InvalidRequestError):
        service.save(project_id=identifier, name="Invalid", content=calibration())
