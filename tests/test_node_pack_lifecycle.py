"""本地 node pack 安装、升级、回滚与审计测试。"""

from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import stat
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import pytest

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_pack_lifecycle import LocalNodePackLifecycleManager
from backend.service.application.errors import InvalidRequestError


def test_lifecycle_installs_upgrades_and_rolls_back_immutable_versions(tmp_path: Path) -> None:
    """验证两个版本完整安装后可回滚，且版本库和审计记录保持完整。"""

    loader, manager = _build_manager(tmp_path)

    first = manager.install_archive(
        BytesIO(_build_node_pack_zip(version="1.0.0", marker="first")),
        source_file_name="demo-1.0.0.zip",
        actor_id="user-admin",
    )
    second = manager.install_archive(
        BytesIO(_build_node_pack_zip(version="2.0.0", marker="second")),
        source_file_name="demo-2.0.0.zip",
        actor_id="user-admin",
    )
    rollback = manager.rollback(
        "demo.nodes",
        "1.0.0",
        actor_id="user-admin",
    )

    assert first.manifest.version == "1.0.0"
    assert second.manifest.version == "2.0.0"
    assert rollback.manifest.version == "1.0.0"
    assert (loader.custom_nodes_root_dir / "demo_nodes" / "marker.txt").read_text(
        encoding="utf-8"
    ) == "first"
    versions = manager.list_versions("demo.nodes")
    assert {item.version for item in versions} == {"1.0.0", "2.0.0"}
    assert [item.version for item in versions if item.active] == ["1.0.0"]
    assert all(len(item.content_sha256) == 64 for item in versions)
    audits = manager.list_audit_records(node_pack_id="demo.nodes")
    assert [item.action for item in audits] == ["rollback", "upgrade", "install"]
    assert all(item.status == "succeeded" for item in audits)
    assert loader.get_node_pack_status_snapshot().items[0].version == "1.0.0"


def test_lifecycle_rejects_same_version_with_different_content_and_preserves_active(
    tmp_path: Path,
) -> None:
    """验证同版本不同内容不能覆盖不可变版本，当前激活内容不受影响。"""

    loader, manager = _build_manager(tmp_path)
    manager.install_archive(
        BytesIO(_build_node_pack_zip(version="1.0.0", marker="first")),
        source_file_name="demo-1.0.0.zip",
        actor_id="user-admin",
    )

    with pytest.raises(InvalidRequestError, match="内容哈希不同"):
        manager.install_archive(
            BytesIO(_build_node_pack_zip(version="1.0.0", marker="tampered")),
            source_file_name="demo-tampered.zip",
            actor_id="user-admin",
        )

    assert (loader.custom_nodes_root_dir / "demo_nodes" / "marker.txt").read_text(
        encoding="utf-8"
    ) == "first"
    assert [item.version for item in manager.list_versions("demo.nodes")] == ["1.0.0"]
    assert manager.list_audit_records(node_pack_id="demo.nodes")[0].status == "failed"


def test_lifecycle_rolls_back_directory_when_runtime_refresh_fails(tmp_path: Path) -> None:
    """验证后置 runtime 刷新失败时目录切换和状态指针一起回退。"""

    loader, manager = _build_manager(tmp_path)
    manager.install_archive(
        BytesIO(_build_node_pack_zip(version="1.0.0", marker="first")),
        source_file_name="demo-1.0.0.zip",
        actor_id="user-admin",
    )

    def fail_refresh() -> None:
        raise RuntimeError("runtime refresh failed")

    with pytest.raises(RuntimeError, match="runtime refresh failed"):
        manager.install_archive(
            BytesIO(_build_node_pack_zip(version="2.0.0", marker="second")),
            source_file_name="demo-2.0.0.zip",
            actor_id="user-admin",
            post_activate=fail_refresh,
        )

    assert (loader.custom_nodes_root_dir / "demo_nodes" / "marker.txt").read_text(
        encoding="utf-8"
    ) == "first"
    assert [item.version for item in manager.list_versions("demo.nodes") if item.active] == [
        "1.0.0"
    ]
    assert not manager.journal_path.exists()


def test_lifecycle_rolls_back_directory_when_state_commit_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证状态文件提交失败时不会留下新激活目录。"""

    loader, manager = _build_manager(tmp_path)
    manager.install_archive(
        BytesIO(_build_node_pack_zip(version="1.0.0", marker="first")),
        source_file_name="demo-1.0.0.zip",
        actor_id="user-admin",
    )

    def fail_state_write(_state: dict[str, object]) -> None:
        raise OSError("state disk full")

    monkeypatch.setattr(manager, "_write_state", fail_state_write)
    with pytest.raises(OSError, match="state disk full"):
        manager.install_archive(
            BytesIO(_build_node_pack_zip(version="2.0.0", marker="second")),
            source_file_name="demo-2.0.0.zip",
            actor_id="user-admin",
        )

    assert (loader.custom_nodes_root_dir / "demo_nodes" / "marker.txt").read_text(
        encoding="utf-8"
    ) == "first"
    assert not manager.journal_path.exists()


def test_lifecycle_rejects_zip_path_traversal_and_records_failed_audit(tmp_path: Path) -> None:
    """验证 ZIP Slip 在写出边界外文件前被拒绝。"""

    _, manager = _build_manager(tmp_path)
    archive_stream = BytesIO()
    with ZipFile(archive_stream, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("../escaped.txt", "unsafe")
    archive_stream.seek(0)

    with pytest.raises(InvalidRequestError, match="路径穿越"):
        manager.install_archive(
            archive_stream,
            source_file_name="unsafe.zip",
            actor_id="user-admin",
        )

    assert not (tmp_path / "escaped.txt").exists()
    audit = manager.list_audit_records()[0]
    assert audit.action == "install"
    assert audit.status == "failed"


def test_lifecycle_rejects_zip_symbolic_link(tmp_path: Path) -> None:
    """验证 ZIP 中的 Unix symbolic link 不会进入 staging。"""

    _, manager = _build_manager(tmp_path)
    archive_stream = BytesIO()
    link = ZipInfo("demo_nodes/link.py")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with ZipFile(archive_stream, mode="w") as archive:
        archive.writestr(link, "../../outside.py")
    archive_stream.seek(0)

    with pytest.raises(InvalidRequestError, match="符号链接"):
        manager.install_archive(
            archive_stream,
            source_file_name="symlink.zip",
            actor_id="user-admin",
        )


def test_lifecycle_rejects_incompatible_package_before_activation(tmp_path: Path) -> None:
    """验证平台不兼容版本不会写入激活目录或版本状态。"""

    loader, manager = _build_manager(tmp_path)

    with pytest.raises(InvalidRequestError, match="不兼容"):
        manager.install_archive(
            BytesIO(
                _build_node_pack_zip(
                    version="1.0.0",
                    marker="future",
                    compatibility={"api": ">=99.0", "runtime": ">=99.0"},
                )
            ),
            source_file_name="future.zip",
            actor_id="user-admin",
        )

    assert not (loader.custom_nodes_root_dir / "demo_nodes").exists()
    assert manager.list_versions("demo.nodes") == ()


def test_lifecycle_rejects_invalid_entrypoint_before_activation(
    tmp_path: Path,
) -> None:
    """验证入口属性缺失会在隔离 staging 验证中失败，不会污染激活目录。"""

    loader, manager = _build_manager(tmp_path)

    with pytest.raises(InvalidRequestError, match="运行时代码验证失败"):
        manager.install_archive(
            BytesIO(
                _build_node_pack_zip(
                    version="1.0.0",
                    marker="invalid-entrypoint",
                    entrypoint_source="def not_register(context):\n    return None\n",
                )
            ),
            source_file_name="invalid-entrypoint.zip",
            actor_id="user-admin",
        )

    assert not (loader.custom_nodes_root_dir / "demo_nodes").exists()
    assert manager.list_versions("demo.nodes") == ()
    assert manager.list_audit_records(node_pack_id="demo.nodes")[0].status == "failed"


def _build_manager(tmp_path: Path) -> tuple[LocalNodePackLoader, LocalNodePackLifecycleManager]:
    """构造使用临时 custom_nodes 根目录的生命周期管理器。"""

    loader = LocalNodePackLoader(tmp_path / "custom_nodes")
    loader.reload()
    return loader, LocalNodePackLifecycleManager(loader)


def _build_node_pack_zip(
    *,
    version: str,
    marker: str,
    compatibility: dict[str, object] | None = None,
    entrypoint_source: str | None = None,
) -> bytes:
    """构造包含可执行 custom node 的规范 ZIP。"""

    manifest = {
        "format_id": "amvision.node-pack-manifest.v1",
        "id": "demo.nodes",
        "version": version,
        "displayName": "Demo Nodes",
        "category": "test",
        "categoryRoot": "test.demo",
        "capabilities": ["test.compute"],
        "permissionScopes": [],
        "entrypoints": {"backend": "custom_nodes.demo_nodes.backend.entry:register"},
        "compatibility": compatibility or {"api": ">=0.1,<1.0", "runtime": ">=3.12"},
        "timeout": {"defaultSeconds": 10, "maxSeconds": 30, "killGraceSeconds": 1},
        "execution": {
            "isolation": "workflow-process",
            "timeoutAction": "terminate-workflow-process",
        },
        "enabledByDefault": True,
        "customNodeCatalogPath": "workflow/catalog.json",
    }
    catalog = {
        "format_id": "amvision.custom-node-catalog.v1",
        "payload_contracts": [],
        "node_definitions": [
            {
                "format_id": "amvision.node-definition.v1",
                "node_type_id": "custom.demo.noop",
                "display_name": "Demo Noop",
                "category": "test.demo.compute",
                "implementation_kind": "custom-node",
                "runtime_kind": "python-callable",
                "version": version,
                "node_pack_id": "demo.nodes",
                "node_pack_version": version,
            }
        ],
    }
    entrypoint = entrypoint_source or (
        "def _handler(request):\n"
        "    return {'result': {'node_id': request.node_id}}\n\n"
        "def register(context):\n"
        "    context.register_python_callable('custom.demo.noop', _handler)\n"
    )
    archive_stream = BytesIO()
    with ZipFile(archive_stream, mode="w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("demo_nodes/__init__.py", "")
        archive.writestr("demo_nodes/backend/__init__.py", "")
        archive.writestr("demo_nodes/backend/entry.py", entrypoint)
        archive.writestr(
            "demo_nodes/manifest.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
        archive.writestr(
            "demo_nodes/workflow/catalog.json",
            json.dumps(catalog, ensure_ascii=False, indent=2),
        )
        archive.writestr("demo_nodes/marker.txt", marker)
    return archive_stream.getvalue()
