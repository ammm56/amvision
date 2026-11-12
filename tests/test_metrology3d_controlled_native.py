"""受控原生库身份、平台装配及版本拒绝，不接受仅版本号的假加载。"""

from pathlib import Path
from types import SimpleNamespace
import json

import pytest

from backend.service.application.errors import ServiceConfigurationError
from backend.maintenance.metrology_release import copy_metrology_dependencies
from backend.maintenance.metrology_release import _verify_native_identity
from custom_nodes.metrology3d_nodes.shared import native_geometry


@pytest.mark.parametrize(
    "key",
    [
        "version",
        "source_commit",
        "source_sha256",
        "patches",
        "patched_files",
        "support_files",
        "cmake_options",
        "distribution",
    ],
)
def test_release_rejects_mismatched_build_identity(key):
    """同版本但补丁遗漏或构建能力不同的包不能提升为受控发行。"""
    root = Path(__file__).resolve().parents[1]
    spec = json.loads(
        (root / "runtimes/python_patches/open3d/manifest.json").read_text("utf-8")
    )
    identity = dict(spec, distribution="open3d")
    _verify_native_identity(identity, spec, "open3d")
    identity[key] = None
    with pytest.raises(ValueError, match="构建身份"):
        _verify_native_identity(identity, spec, "open3d")


@pytest.mark.parametrize("actual", ["0.20.0", "0.20.0+amvision.1", "wrong"])
def test_runtime_module_version_must_match_distribution(monkeypatch, actual):
    """模块缓存或路径遮蔽不能借正确发行元数据绕过准入。"""
    monkeypatch.setattr(
        native_geometry, "require_controlled_distribution", lambda name, expected: None
    )
    monkeypatch.setattr(
        native_geometry.importlib,
        "import_module",
        lambda name: SimpleNamespace(__version__=actual),
    )
    if actual == "0.20.0+amvision.1":
        assert native_geometry.require_open3d().__version__ == actual
    else:
        with pytest.raises(ServiceConfigurationError, match="不一致"):
            native_geometry.require_open3d()


def test_native_loader_failure_remains_configuration_error(monkeypatch):
    monkeypatch.setattr(
        native_geometry, "require_controlled_distribution", lambda name, expected: None
    )

    def failed(name):
        raise OSError("missing DLL")

    monkeypatch.setattr(native_geometry.importlib, "import_module", failed)
    with pytest.raises(ServiceConfigurationError, match="原生库无法加载"):
        native_geometry.require_open3d()


@pytest.mark.parametrize(
    "target_os,distribution", [("windows", "open3d"), ("ubuntu", "open3d-cpu")]
)
def test_release_copies_actual_controlled_native_for_target(
    tmp_path, target_os, distribution
):
    """在任意宿主装配明确目标的本地 wheel；不安装、不修改既有发行包。"""
    root = Path(__file__).resolve().parents[1]
    native = (
        root
        / "runtimes/third_party/python-geometry/open3d-candidates/0.20.0+amvision.1"
    )
    if not native.exists():
        pytest.skip("本地受控 wheel 需显式准备")
    (tmp_path / "app").mkdir()
    (tmp_path / "app/requirements.txt").write_text("", encoding="utf-8")
    result = copy_metrology_dependencies(root, tmp_path, target_os=target_os)
    assert len(result["wheels"]) == 3
    assert f"{distribution}==0.20.0+amvision.1" in result["requirements"]
    for item in result["wheels"]:
        wheel = tmp_path / item["path"]
        assert wheel.is_file()
        assert (
            json.loads(wheel.with_suffix(".build.json").read_text("utf-8"))[
                "wheel_sha256"
            ]
            == item["sha256"]
        )
