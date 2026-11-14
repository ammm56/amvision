"""双平台 CPU 发行边界；实际 bundled 运行另由完整发行验收覆盖。"""

import importlib.util
import json
from pathlib import Path

import pytest

from backend.maintenance import release_assembly as assembly
from backend.maintenance.metrology_release import validate_metrology_runtime
from backend.maintenance.metrology_release import copy_native_libraries
from tests.test_release_assembly import _patch_release_runtime_asset_sources
from tests.test_full_launcher_stop_contract import _module


def test_ubuntu_layout_and_explicit_dependency_lock(tmp_path, monkeypatch):
    """Ubuntu 只装配 POSIX 入口；版本来源与节点锁一致，复用 A11 工具。"""
    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    result = assembly.assemble_release(
        assembly.ReleaseAssemblyRequest(
            profile_id="full-ubuntu-x64-cpu",
            output_root=tmp_path / "out",
        )
    )
    root = result.release_dir
    manifest = json.loads(result.release_manifest_path.read_text("utf-8"))
    assert manifest["target"]["os"] == "ubuntu"
    assert manifest["stack"]["posix_launcher"] == "start-amvision-full.sh"
    assert "windows_launcher" not in manifest["stack"]
    assert (root / "tools/ffmpeg/linux-x64/ffmpeg").is_file()
    assert (root / "launchers/client/invoke_point_cloud.py").is_file()
    assert not (root / "start-amvision-full.bat").exists()
    assert not (root / "tools/ffmpeg/windows-x64").exists()
    for name in (
        "start-amvision-full.sh",
        "stop-amvision-full.sh",
        "launchers/maintenance/invoke-backend-maintenance.sh",
    ):
        assert b"\r" not in (root / name).read_bytes()
        assert "PYTHON_EXE=python3" not in (root / name).read_text()
    requirements = (root / "app/requirements.txt").read_text("utf-8")
    for locked in manifest["metrology_dependencies"]["requirements"]:
        assert locked in requirements
    assert len(manifest["metrology_dependencies"]["wheels"]) == 3
    launcher = _module(
        "a12_full_start", "runtimes/launchers/full/start_amvision_full.py"
    )
    launcher._validate_required_files(root, manifest, manifest["workers"])
    assert not (root / "launchers/enable_windows_long_paths.py").exists()


def test_release_does_not_copy_development_configuration(tmp_path, monkeypatch):
    """现场配置显式写入，不携带开发端口、凭据和数据路径。"""
    _patch_release_runtime_asset_sources(monkeypatch, tmp_path)
    config = tmp_path / "source-config"
    config.mkdir()
    (config / "backend-service.json").write_text("{}")
    (config / "backend-service.local.json").write_text('{"secret":"not-for-release"}')
    monkeypatch.setattr(assembly, "SOURCE_CONFIG_DIR", config)
    result = assembly.assemble_release(
        assembly.ReleaseAssemblyRequest(
            profile_id="full-windows-x64-cpu",
            output_root=tmp_path / "out",
        )
    )
    assert (result.release_dir / "config/backend-service.json").is_file()
    assert not (result.release_dir / "config/backend-service.local.json").exists()


def test_release_module_environment_excludes_external_python(tmp_path, monkeypatch):
    """源码开发环境不变；发行入口不继承外部 Python 搜索路径。"""
    spec = importlib.util.spec_from_file_location(
        "a12_common", Path("runtimes/launchers/common.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "release"
    (root / "manifests/release-profiles").mkdir(parents=True)
    (root / "app/backend").mkdir(parents=True)
    monkeypatch.setenv("PYTHONPATH", "external-source")
    monkeypatch.setenv("PYTHONHOME", "external-home")
    monkeypatch.setenv("PYTHONUSERBASE", "external-site")
    env = module.build_python_module_environment(root)
    assert env["PYTHONPATH"] == str(root / "app")
    assert env["PYTHONNOUSERSITE"] == "1"
    assert "PYTHONHOME" not in env and "PYTHONUSERBASE" not in env


@pytest.mark.parametrize("descriptor", [None, {}, {"requirements": []}])
def test_metrology_validation_fails_closed_without_pack_lock(tmp_path, descriptor):
    """缺失发行锁明确失败，不根据开发环境已安装依赖猜测可运行。"""
    manifest = tmp_path / "custom_nodes/metrology3d_nodes/manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "version": "0.1.20",
                "compatibility": {"pythonDistributions": ["numpy==2.4.4"]},
            }
        )
    )
    result = validate_metrology_runtime(
        tmp_path, {"metrology_dependencies": descriptor}
    )
    assert result["valid"] is False
    assert result["issues"]


def test_native_assets_reject_tampered_payload(tmp_path):
    """本地资产内容不符合已登记摘要时，不能产出假完整的离线包。"""
    source = tmp_path / "source"
    manifest = source / "runtimes/manifests/native-libraries/ubuntu-x64.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"files": {"libusb-1.0.so.0": "0" * 64}}))
    library = source / "runtimes/third_party/native/ubuntu-x64/libusb-1.0.so.0"
    library.parent.mkdir(parents=True)
    library.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="摘要不匹配"):
        copy_native_libraries(source, tmp_path / "target", "ubuntu-x64")


def test_linux_module_environment_uses_bundled_native_libraries(tmp_path, monkeypatch):
    """从统一 launcher 注入随包 native 路径，不要求 shell 或系统提前配置。"""
    module = _module("a12_common_native", "runtimes/launchers/common.py")
    monkeypatch.setattr(module.sys, "platform", "linux")
    root = tmp_path / "release"
    native = root / "tools/native/lib"
    native.mkdir(parents=True)
    (root / "app/backend").mkdir(parents=True)
    environment = {}
    module._prepare_local_runtime_paths(root, environment)
    assert environment["LD_LIBRARY_PATH"] == str(native.resolve())
