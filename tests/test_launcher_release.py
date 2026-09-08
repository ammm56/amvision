"""桌面启动器发行清单的完整性及路径边界测试。"""

import hashlib
import json
from pathlib import Path

import pytest

from backend.maintenance.launcher_release import copy_launcher_package, validate_launcher_package


def _package(root: Path) -> dict:
    """生成最小具备必需文件的发行清单夹具。"""
    entries = []
    for name in ("amvar.launcher.exe", "launcher/amvar.launcher.dll", "launcher/coreclr.dll", "launcher/launcher-build-info.json", "launcher/tools/webview2/win-x64/msedgewebview2.exe"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = b"MZ" + bytes(58) + (64).to_bytes(4, "little") + b"PE\x00\x00\x64\x86"
        path.write_bytes(data)
        entries.append({"path": name, "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {"format_id": "amvar.launcher-release.v2", "rid": "win-x64", "self_contained": True, "files": entries}
    (root / "launcher" / "launcher-release.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_launcher_package_copies_only_declared_files(tmp_path: Path) -> None:
    """发行组装不带入未声明的本地配置。"""
    source, target = tmp_path / "source", tmp_path / "target"
    _package(source)
    (source / "local-secret.txt").write_text("local")
    manifest = validate_launcher_package(source)
    copy_launcher_package(source, target, manifest)
    assert (target / "amvar.launcher.exe").is_file()
    assert not (target / "local-secret.txt").exists()


def test_launcher_package_rejects_tampered_asset(tmp_path: Path) -> None:
    """任一文件摘要变化即拒绝组装。"""
    _package(tmp_path)
    (tmp_path / "launcher/coreclr.dll").write_bytes(b"changed")
    with pytest.raises(ValueError, match="摘要"):
        validate_launcher_package(tmp_path)


def test_launcher_package_rejects_wrong_architecture_with_valid_hash(tmp_path: Path) -> None:
    """摘要正确仍需检查实际 PE 架构。"""
    manifest = _package(tmp_path)
    path = tmp_path / "launcher/coreclr.dll"
    data = path.read_bytes()[:-2] + b"\x64\xaa"
    path.write_bytes(data)
    next(entry for entry in manifest["files"] if entry["path"] == "launcher/coreclr.dll")["sha256"] = hashlib.sha256(data).hexdigest()
    (tmp_path / "launcher" / "launcher-release.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="Windows x64"):
        validate_launcher_package(tmp_path)


@pytest.mark.parametrize("manifest", [[], {"format_id": "amvar.launcher-release.v2", "rid": "win-x64", "self_contained": True, "files": [None]}])
def test_launcher_package_rejects_malformed_manifest(tmp_path: Path, manifest: object) -> None:
    """结构错误返回明确的发行校验错误。"""
    (tmp_path / "launcher").mkdir(exist_ok=True)
    (tmp_path / "launcher" / "launcher-release.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_launcher_package(tmp_path)


@pytest.mark.parametrize("path", ["../outside", "config/launcher.json", "data/local", "app/backend/x", "C:/outside", "tools/../../outside", "AMVAR.LAUNCHER.EXE", "launcher/../other.txt", "launcher/config/private.json", "launcher/data/private.json"])
def test_launcher_package_rejects_unsafe_or_duplicate_path(tmp_path: Path, path: str) -> None:
    """越界、配置混入和大小写重复不能成为发行文件。"""
    manifest = _package(tmp_path)
    manifest["files"].append({"path": path, "sha256": "unused"})
    (tmp_path / "launcher").mkdir(exist_ok=True)
    (tmp_path / "launcher" / "launcher-release.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        validate_launcher_package(tmp_path)
