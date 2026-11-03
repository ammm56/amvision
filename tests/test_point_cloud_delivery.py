"""发行工具的实际入口、搬移与完整性，不把占位 Python 当离线发行验收。"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from backend.maintenance.point_cloud_delivery import (
    APPLICATION_FILES,
    LAUNCHER_FILE,
    copy_point_cloud_delivery,
    validate_point_cloud_delivery,
)
from scripts.metrology_workpiece import app_document


ROOT = Path(__file__).resolve().parents[1]


def isolated_environment() -> dict[str, str]:
    """不继承开发源码搜索路径、用户 site 或业务环境覆盖。"""
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AMVISION_") and key not in {"PYTHONPATH", "PYTHONHOME"}
    }
    env.update(PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    return env


@pytest.fixture(scope="module")
def delivered_tools(tmp_path_factory):
    """同一份源码装配后改目录；子进程不能从 tests 或开发目录导入。"""
    temporary = tmp_path_factory.mktemp("point-cloud-delivery")
    stage = temporary / "staging"
    manifest = copy_point_cloud_delivery(ROOT, stage)
    shutil.copytree(
        ROOT / "backend",
        stage / "app/backend",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    shutil.copy2(ROOT / "runtimes/launchers/common.py", stage / "launchers/common.py")
    (stage / "config").mkdir()
    (stage / "manifests/release-profiles").mkdir(parents=True)
    destination = temporary / "relocated tools"
    stage.rename(destination)
    assert not stage.exists()
    assert validate_point_cloud_delivery(destination, manifest) == []
    return destination


def invoke_tools(root: Path, tool: str, args: list[str], *, cwd: Path):
    """测试显式用当前环境解释器；不声称这是 bundled Python 原生依赖验收。"""
    return subprocess.run(
        [
            sys.executable,
            str(root / LAUNCHER_FILE),
            "--python-executable",
            sys.executable,
            tool,
            "--",
            *args,
        ],
        cwd=cwd,
        env=isolated_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )


def test_delivery_manifest_is_exact_and_detects_damage(tmp_path):
    """固定白名单不带缓存；损坏、缺项、重复及任意路径不能被接受。"""
    manifest = copy_point_cloud_delivery(ROOT, tmp_path)
    expected = {f"app/{name}" for name in APPLICATION_FILES} | {LAUNCHER_FILE}
    assert {
        p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file()
    } == expected
    assert validate_point_cloud_delivery(tmp_path, manifest) == []
    file = tmp_path / manifest["files"][0]["path"]
    file.write_bytes(file.read_bytes() + b"\n")
    assert "摘要不一致" in validate_point_cloud_delivery(tmp_path, manifest)[0]
    file.unlink()
    assert "文件无效" in validate_point_cloud_delivery(tmp_path, manifest)[0]
    for invalid in (
        None,
        {},
        {**manifest, "files": manifest["files"][:-1]},
        {**manifest, "files": [manifest["files"][0]] * len(expected)},
        {**manifest, "files": [{"path": "../outside"}] * len(expected)},
    ):
        assert validate_point_cloud_delivery(tmp_path, invalid)


def test_missing_source_fails_before_copy(tmp_path):
    """源文件缺失时不制造貌似存在的空客户端目录。"""
    with pytest.raises(FileNotFoundError, match="缺少发行文件"):
        copy_point_cloud_delivery(tmp_path / "source", tmp_path / "release")
    assert not (tmp_path / "release").exists()


def test_runtime_validation_includes_tool_inventory(tmp_path, monkeypatch):
    """正式 validate-layout 的运行时校验不能绕过新工具清单。"""
    from backend.maintenance import release_runtime_validation as validation

    monkeypatch.setattr(validation, "_validate_installed_requirements", lambda path: [])
    monkeypatch.setattr(validation, "_validate_accelerator", lambda **kwargs: {"issues": []})
    result = validation.validate_release_runtime(app_root=tmp_path, release_manifest={})
    assert any("点云调用工具发行清单缺失" in issue for issue in result["issues"])
    assert not result["valid"]


@pytest.mark.parametrize("input_kind", ["file", "array"])
@pytest.mark.parametrize("view", ["full", "numeric"])
def test_relocated_recipe_entrypoint(delivered_tools, tmp_path, input_kind, view):
    """四种正式配方与源图完全一致，覆盖空白外部工作目录和带空格路径。"""
    output = tmp_path / "new recipe.json"
    args = [str(output), "--input-kind", input_kind, "--view", view]
    result = invoke_tools(delivered_tools, "recipe", args, cwd=tmp_path)
    assert result.returncode == 0, (result.stdout, result.stderr)
    expected = app_document(input_kind=input_kind, view=view)
    assert json.loads(output.read_text("utf-8")) == expected
    output.write_text("keep existing", encoding="utf-8")
    result = invoke_tools(delivered_tools, "recipe", args, cwd=tmp_path)
    assert result.returncode != 0
    assert output.read_text("utf-8") == "keep existing"
    result = invoke_tools(
        delivered_tools, "recipe", [*args, "--overwrite"], cwd=tmp_path
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text("utf-8")) == expected


def test_relocated_client_help_and_no_system_python_fallback(delivered_tools, tmp_path):
    """不启动服务也可审查参数；发行解释器缺失必须明确失败。"""
    result = invoke_tools(delivered_tools, "invoke", ["--help"], cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert "--generation" in result.stdout and "--timeout-ms" in result.stdout
    result = subprocess.run(
        [
            sys.executable,
            str(delivered_tools / LAUNCHER_FILE),
            "recipe",
            "--",
            "--help",
        ],
        cwd=tmp_path,
        env=isolated_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode != 0 and "禁止回退到系统 Python" in result.stderr


def test_relocated_client_import_origin(delivered_tools, tmp_path):
    """正式工具和后端依赖确实来自搬移后的包，而不是开发 PYTHONPATH。"""
    env = isolated_environment()
    env["PYTHONPATH"] = str(delivered_tools / "app")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import backend, runtimes.clients.point_cloud.client as c; "
            "print(backend.__file__); print(c.__file__)",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    for path in result.stdout.splitlines():
        assert Path(path).resolve().is_relative_to(delivered_tools / "app")
