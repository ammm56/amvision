"""三维配方资源闭包、跨项目映射与现有 bundle 恢复的组合回归。"""

from dataclasses import replace
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

import numpy as np
import pytest

from backend.contracts.workflows.cloud_package import WorkflowAppDocument
from backend.contracts.workflows.point_cloud_runtime import FilterCloudValid
from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import (
    InvalidRequestError,
    WorkflowRecoveryRequiredError,
    ResourceConflictError,
)
from backend.service.application.workflows.cloud_package import (
    CloudPackageImport,
    export_cloud_package,
    retarget_cloud_document,
)
from backend.service.application.workflows.documents.measurement_resources import (
    collect_measurement_references,
    reference_key,
)
from backend.service.application.workflows.workflow_service import (
    LocalWorkflowJsonService,
)
from custom_nodes.metrology3d_nodes.shared.cloud_assets import save_cloud, read_asset
from custom_nodes.metrology3d_nodes.shared.filter_valid import filter_valid
from tests.metrology3d_transport_support import cloud_documents
from tests.point_cloud_support import create_resource_service, options
from tests.test_metrology3d_preprocess import make_cloud
from tests.test_point_cloud_details import detail_policy


ROOT = Path(__file__).resolve().parents[1]


def workflow_service(resources):
    """使用已实现节点目录，不替换文档、资源或执行校验。"""
    loader = LocalNodePackLoader(ROOT / "custom_nodes")
    loader.refresh()
    registry = NodeCatalogRegistry(node_pack_loader=loader)
    return LocalWorkflowJsonService(
        dataset_storage=resources.storage,
        node_catalog_registry=registry,
        point_cloud_policy=detail_policy(),
    )


@pytest.fixture
def source(tmp_path):
    """原始 float64/uint64 字段、过滤子集与父依赖均通过正式资源服务保存。"""
    resources = create_resource_service(tmp_path / "source")
    scope, runtime, cloud = make_cloud(
        coordinates=np.array([[1, 2, 3], [np.nan, 2, 3], [7, 8, 9]], dtype="<f8"),
        attributes=[("serial", np.array([2**64 - 1, 2**63 + 1, 7], dtype="<u8"), None)],
    )
    policy = replace(detail_policy().assets(), max_archive_bytes=1_000_000)
    try:
        parent = save_cloud(
            runtime,
            cloud,
            service=resources,
            project_id="test",
            name="Original",
            mode="original",
            write_identity="a" * 64,
            policy=policy,
            cancel=lambda: None,
        )
        cloud = read_asset(
            runtime,
            parent,
            service=resources,
            project_id="test",
            policy=policy,
            cancel=lambda: None,
        )
        filtered, _ = filter_valid(
            runtime,
            cloud,
            FilterCloudValid(finite_fields=("positions",), sentinels=()),
            cancel=lambda: None,
        )
        child = save_cloud(
            runtime,
            filtered,
            service=resources,
            project_id="test",
            name="Subset",
            mode="derived",
            write_identity="b" * 64,
            policy=policy,
            cancel=lambda: None,
        )
        template, application = cloud_documents(options().model_dump(mode="json"))
        template = template.model_dump(mode="json")
        application = application.model_dump(mode="json")
        template["nodes"][0]["parameters"] = dict(
            source=dict(kind="asset", reference=child.model_dump(mode="json"))
        )
        template["template_inputs"] = []
        application["bindings"] = [
            binding
            for binding in application["bindings"]
            if binding["direction"] == "output"
        ]
        document = WorkflowAppDocument(
            format_id="amvision.workflow-app-document.v1",
            application=application,
            template=template,
        )
        stream = BytesIO()
        export_cloud_package(
            workflow_service(resources),
            document,
            project_id="test",
            stream=stream,
            policy=policy,
            cancel=lambda: None,
        )
        yield resources, policy, stream.getvalue(), parent, child
    finally:
        assert not scope.close()
        assert runtime.budget.used == 0


def import_package(
    resources, policy, data, *, cancel=lambda: None, operation="import-one"
):
    """用现有事务导入新草稿；正式 API 另测权限和生命周期 claim。"""
    with ZipFile(BytesIO(data)) as archive:
        imported = CloudPackageImport(archive, policy=policy, cancel=cancel)
        document = retarget_cloud_document(
            imported.manifest.document,
            project_id="target",
            application_id="imported-app",
            template_id="imported-template",
        )
        service = workflow_service(resources)
        result = service.save_application_bundle(
            project_id="target",
            application=document.application,
            template=document.template,
            operation_id=operation,
            resource_import=imported,
        )
        return result, imported.mapping


def assert_empty(resources):
    """失败后没有权威草稿、数据块或活动 journal。"""
    assert resources.list_versions(project_id="target") == []
    root = resources.storage.root_dir
    assert not list(root.rglob("template.json"))
    assert not list(root.rglob("application.json"))
    assert not list(root.rglob("content.bin"))
    journals = root / "runtime/workflow-application-bundle-journals"
    assert not journals.exists() or not list(journals.iterdir())


def rewrite_package(data, mutate):
    """只用于构造损坏包，生产仍使用成熟 ZipFile 与原资产解析。"""
    with ZipFile(BytesIO(data)) as source:
        entries = {name: source.read(name) for name in source.namelist()}
    mutate(entries)
    result = BytesIO()
    with ZipFile(result, "w", compression=ZIP_STORED) as target:
        for name, content in entries.items():
            target.writestr(name, content)
    return result.getvalue()


def test_empty_target_roundtrip_preserves_parent_fields_and_sources(source, tmp_path):
    original, policy, data, parent, child = source
    target = create_resource_service(tmp_path / "target")
    result, mapping = import_package(target, policy, data)
    assert len(mapping) == 2
    new_parent, new_child = (
        mapping[reference_key(parent)],
        mapping[reference_key(child)],
    )
    assert new_child.project_id == "target" and new_child.sha256 != child.sha256
    assert new_parent.sha256 == parent.sha256
    content = target.read(new_child, project_id="target").content.point_cloud
    assert content.parent_assets == (new_parent,)
    assert content.provenance.parents[0].reference == new_parent
    assert content.provenance.parents[0].content_sha256 == new_parent.sha256
    assert content.indices.source_point_count == 3
    assert collect_measurement_references(result.template_document.template) == (
        new_child,
    )
    from backend.service.application.workflows.documents.cloud_resource_blobs import (
        cloud_blob_key,
    )

    for old, new in ((parent, new_parent), (child, new_child)):
        before = original.read(old, project_id="test")
        after = target.read(new, project_id="target")
        assert before.content.point_cloud.fields == after.content.point_cloud.fields
        for blob in before.content.point_cloud.blobs:
            assert (
                original.storage.resolve(
                    cloud_blob_key(original, old, blob)
                ).read_bytes()
                == target.storage.resolve(
                    cloud_blob_key(target, new, blob)
                ).read_bytes()
            )
    with pytest.raises(ResourceConflictError):
        import_package(target, policy, data, operation="again")
    assert len(target.list_versions(project_id="target")) == 2


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "unknown",
        "hash",
        "extra",
        "order",
        "external",
        "runtime",
        "cross-project",
        "duplicate",
    ],
)
def test_bad_package_never_leaves_resources(source, tmp_path, fault):
    _, policy, data, *_ = source

    def damage(entries):
        manifest = json.loads(entries["package.json"])
        if fault == "missing":
            entries.pop("resources/0.zip")
        elif fault == "unknown":
            entries["../escape"] = b"bad"
        elif fault == "hash":
            manifest["resources"][0]["sha256"] = "0" * 64
        elif fault == "extra":
            manifest["document"]["template"]["nodes"][0]["parameters"]["source"][
                "reference"
            ] = manifest["resources"][0]["reference"]
        elif fault == "external":
            manifest["document"]["application"]["metadata"]["model_version_id"] = (
                "outside"
            )
        elif fault == "runtime":
            manifest["document"]["application"]["metadata"]["object_key"] = (
                "outside/file.ply"
            )
        elif fault == "cross-project":
            manifest["resources"][0]["reference"]["project_id"] = "other"
        elif fault == "duplicate":
            manifest["resources"][1]["reference"] = manifest["resources"][0][
                "reference"
            ]
        else:
            manifest["resources"].reverse()
            entries["resources/0.zip"], entries["resources/1.zip"] = (
                entries["resources/1.zip"],
                entries["resources/0.zip"],
            )
        entries["package.json"] = json.dumps(manifest).encode()

    target = create_resource_service(tmp_path / fault)
    with pytest.raises(InvalidRequestError):
        import_package(target, policy, rewrite_package(data, damage))
    assert_empty(target)


def test_closure_deduplicates_and_enforces_total_archive_budget(source, tmp_path):
    """重复节点引用不复制父项，整体预算独立于每个资产包的预算。"""
    from backend.service.application.workflows.cloud_package import (
        cloud_dependency_closure,
    )

    resources, policy, data, *_ = source
    with ZipFile(BytesIO(data)) as archive:
        manifest = CloudPackageImport(
            archive, policy=policy, cancel=lambda: None
        ).manifest
    graph = manifest.document.template.model_dump(mode="json")
    graph["nodes"].append({**graph["nodes"][0], "node_id": "read-copy"})
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate

    closure = cloud_dependency_closure(
        resources,
        WorkflowGraphTemplate.model_validate(graph),
        project_id="test",
        cancel=lambda: None,
    )
    assert len(closure) == 2
    limited = replace(policy, max_archive_bytes=500)
    with pytest.raises(InvalidRequestError):
        export_cloud_package(
            workflow_service(resources),
            manifest.document,
            project_id="test",
            stream=BytesIO(),
            policy=limited,
            cancel=lambda: None,
        )
    target = create_resource_service(tmp_path / "limited")
    with pytest.raises(InvalidRequestError):
        import_package(target, limited, data)
    assert_empty(target)


@pytest.mark.parametrize("failure", ["move", "template", "application", "commit"])
def test_transaction_rolls_back_each_commit_boundary(
    source, tmp_path, monkeypatch, failure
):
    _, policy, data, *_ = source
    target = create_resource_service(tmp_path / failure)
    method = (
        "move_tree"
        if failure == "move"
        else "write_json"
        if failure in {"template", "application"}
        else "write_bytes"
    )
    original = getattr(target.storage, method)

    def fail(*args, **kwargs):
        key = str(args[0])
        if (
            (failure == "move" and "/staging/" in key)
            or (failure == "template" and key.endswith("/template.json"))
            or (failure == "application" and key.endswith("/application.json"))
            or (failure == "commit" and key.endswith("/committed.json"))
        ):
            if failure == "move":
                original(*args, **kwargs)
            raise OSError("injected failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(target.storage, method, fail)
    from backend.service.application.errors import PersistenceOperationError

    with pytest.raises(PersistenceOperationError):
        import_package(target, policy, data)
    assert_empty(target)


def test_cancel_after_resource_install_rolls_back(source, tmp_path, monkeypatch):
    _, policy, data, *_ = source
    target = create_resource_service(tmp_path / "cancel")
    installed = False
    original = target.storage.move_tree

    def move(*args):
        nonlocal installed
        result = original(*args)
        installed = True
        return result

    monkeypatch.setattr(target.storage, "move_tree", move)

    def cancel():
        if installed:
            raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        import_package(target, policy, data, cancel=cancel)
    assert_empty(target)


def test_recovery_preserves_journal_until_resource_cleanup_succeeds(
    source, tmp_path, monkeypatch
):
    _, policy, data, *_ = source
    target = create_resource_service(tmp_path / "recovery")
    original_move, original_delete = (
        target.storage.move_tree,
        target.storage.delete_tree,
    )

    def move(*args):
        original_move(*args)
        raise RuntimeError("after install")

    def delete(key):
        if key.startswith("workflows/projects/target/measurement-resources"):
            raise OSError("locked")
        return original_delete(key)

    monkeypatch.setattr(target.storage, "move_tree", move)
    monkeypatch.setattr(target.storage, "delete_tree", delete)
    with pytest.raises(WorkflowRecoveryRequiredError):
        import_package(target, policy, data)
    monkeypatch.undo()
    recovered = workflow_service(
        target
    ).application_bundle_journals.recover_interrupted_journals()
    assert recovered.rolled_back_journals == 1
    assert_empty(target)


def crash_import(root, package_path, policy, phase):
    """独立进程在权威提交边界硬退出，不执行 finally，验证持久恢复。"""
    import os
    from backend.service.application.workflows.application_bundle_journal import (
        WorkflowApplicationBundleJournalService,
    )

    if phase == "before-marker":
        WorkflowApplicationBundleJournalService.commit = lambda *_: os._exit(77)
    else:
        WorkflowApplicationBundleJournalService._finalize_committed_journal = (
            lambda *_: os._exit(77)
        )
    import_package(
        create_resource_service(Path(root)), policy, Path(package_path).read_bytes()
    )


@pytest.mark.parametrize("phase", ["active", "completed"])
def test_interrupt_after_commit_does_not_roll_back(
    source, tmp_path, monkeypatch, phase
):
    """已提交清理阶段中断，无论 journal 是否移动都必须保留 App 和完整资产。"""
    from backend.service.application.workflows.application_bundle_journal import (
        WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT,
        WorkflowApplicationBundleJournalService,
    )

    _, policy, data, *_ = source
    target = create_resource_service(tmp_path / phase)
    original = WorkflowApplicationBundleJournalService._finalize_committed_journal
    interrupted = False

    def interrupt_once(journals, operation_id):
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            if phase == "completed":
                journals.dataset_storage.move_tree(
                    journals._journal_root_key(operation_id),
                    journals._completed_journal_root_key(operation_id),
                )
            raise KeyboardInterrupt("after commit")
        return original(journals, operation_id)

    monkeypatch.setattr(
        WorkflowApplicationBundleJournalService,
        "_finalize_committed_journal",
        interrupt_once,
    )
    with pytest.raises(KeyboardInterrupt, match="after commit"):
        import_package(target, policy, data)
    assert len(target.list_versions(project_id="target")) == 2
    assert (
        workflow_service(target)
        .get_application(project_id="target", application_id="imported-app")
        .application.application_id
        == "imported-app"
    )
    assert not list(
        target.storage.resolve(WORKFLOW_APPLICATION_BUNDLE_JOURNAL_ROOT).glob(
            "*/manifest.json"
        )
    )


@pytest.mark.parametrize("phase", ["before-marker", "after-marker"])
def test_process_crash_recovers_atomic_resource_bundle(source, tmp_path, phase):
    """标记前回滚全部，标记后保留全部；沿跨平台 spawn，不依赖快照回收。"""
    import multiprocessing

    _, policy, data, *_ = source
    package = tmp_path / "source.zip"
    package.write_bytes(data)
    target_root = tmp_path / "crash-target"
    process = multiprocessing.get_context("spawn").Process(
        target=crash_import, args=(str(target_root), str(package), policy, phase)
    )
    process.start()
    try:
        process.join(45)
        assert not process.is_alive(), "import child did not reach crash boundary"
        assert process.exitcode == 77
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)
        process.close()
    resources = create_resource_service(target_root)
    service = workflow_service(resources)
    recovered = service.application_bundle_journals.recover_interrupted_journals()
    if phase == "before-marker":
        assert recovered.rolled_back_journals == 1
        assert_empty(resources)
    else:
        assert recovered.finalized_journals == 1
        assert len(resources.list_versions(project_id="target")) == 2
        app = service.get_application(
            project_id="target", application_id="imported-app"
        )
        assert app.application.application_id == "imported-app"
