"""显式运行该集成套件时，禁止悄悄换用上游原版或跳过缺失依赖。"""

import hashlib
from importlib.metadata import distribution, version
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def require_controlled_versions():
    """测试解释器必须安装当前受控 wheel。"""
    assert version("trimesh") == "5.1.1+amvision.2"
    assert version("pypcd4") == "1.5.1+amvision.2"
    assert version("numpy") == "2.4.4"
    root = Path(__file__).resolve().parents[3] / "runtimes" / "python_patches"
    specs = json.loads((root / "manifest.json").read_text("utf-8"))["packages"]
    for name, spec in specs.items():
        package = distribution(name)
        files = {
            key: root / name / key
            for key in [*spec["original_files"], *spec.get("added_files", [])]
            if key.endswith(".py")
        }
        files[spec["shared_target"]] = root / "shared" / "_strict_records.py"
        for relative, expected in files.items():
            actual = Path(package.locate_file(relative.removeprefix("src/")))
            assert (
                hashlib.sha256(actual.read_bytes()).digest()
                == hashlib.sha256(expected.read_bytes()).digest()
            ), relative
