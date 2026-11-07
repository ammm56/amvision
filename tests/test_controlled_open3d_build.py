"""受控原生源码准备的身份、补丁、宿主仓库和路径拒绝回归。"""

from hashlib import sha256
from importlib.machinery import EXTENSION_SUFFIXES
import io
import json
import subprocess
import tarfile
from types import SimpleNamespace
import zipfile

import pytest

from scripts.build_controlled_open3d import prepare_source
from scripts import build_controlled_open3d


def fixture(tmp_path, *, link="../AGENTS.md"):
    """仅验证构建器的微型归档，不冒充 Open3D 原生几何验收。"""
    root = tmp_path / "patches"
    root.mkdir()
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as stream:
        for name, body in {
            "source.txt": b"old\n",
            "AGENTS.md": b"upstream text\n",
        }.items():
            member = tarfile.TarInfo(f"Open3D-0.20.0/{name}")
            member.size = len(body)
            stream.addfile(member, io.BytesIO(body))
        if link:
            member = tarfile.TarInfo("Open3D-0.20.0/.github/copilot-instructions.md")
            member.type = tarfile.SYMTYPE
            member.linkname = link
            stream.addfile(member)
    patch = b"--- a/source.txt\n+++ b/source.txt\n@@ -1 +1 @@\n-old\n+new\n"
    (root / "change.patch").write_bytes(patch)
    spec = dict(
        version="0.20.0+amvision.1",
        source_commit="test-only",
        source_sha256=sha256(archive.read_bytes()).hexdigest(),
        source_directory="Open3D-0.20.0",
        original_files={"source.txt": sha256(b"old\n").hexdigest()},
        patches={"change.patch": sha256(patch).hexdigest()},
        patched_files={"source.txt": sha256(b"new\n").hexdigest()},
        support_files={"AGENTS.md": sha256(b"upstream text\n").hexdigest()},
        cmake_options={},
    )
    (root / "manifest.json").write_text(json.dumps(spec), encoding="utf-8")
    return archive, root, spec


def test_patch_inside_host_repo_is_applied_and_link_materialized(tmp_path):
    """不能以 git apply 返回零代替修改后摘要；不依赖 Windows 符号链接权限。"""
    subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    archive, root, spec = fixture(tmp_path)
    source, _, identity = prepare_source(archive, tmp_path / "nested/build", root)
    assert (source / "source.txt").read_bytes() == b"new\n"
    assert identity["patched_files"] == spec["patched_files"]
    copied = source / ".github/copilot-instructions.md"
    assert not copied.is_symlink()
    assert copied.read_bytes() == b"upstream text\n"
    assert not (tmp_path / "source.txt").exists()


@pytest.mark.parametrize(
    "field", ["original_files", "support_files", "patches", "patched_files"]
)
def test_changed_input_or_result_identity_is_rejected(tmp_path, field):
    """原文件、补丁、最终文件三段身份任一不匹配都不能得到可构建结果。"""
    archive, root, spec = fixture(tmp_path, link=None)
    key = next(iter(spec[field]))
    spec[field][key] = "0" * 64
    (root / "manifest.json").write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        prepare_source(archive, tmp_path / "build", root)
    assert not (tmp_path / "build/source.build.json").exists()


def test_bad_archive_rejected_before_creating_directory(tmp_path):
    """坏归档不能触发解压或调用外部构建工具。"""
    archive, root, _ = fixture(tmp_path)
    archive.write_bytes(b"wrong")
    with pytest.raises(ValueError, match="archive SHA-256"):
        prepare_source(archive, tmp_path / "build", root)
    assert not (tmp_path / "build").exists()


def test_unexpected_source_link_is_rejected(tmp_path):
    """不将源码包链接解析到仓库或临时目录之外。"""
    archive, root, _ = fixture(tmp_path, link="../../../../outside")
    with pytest.raises(ValueError, match="Unexpected source archive link"):
        prepare_source(archive, tmp_path / "build", root)
    assert not (tmp_path / "outside").exists()


def test_existing_build_directory_not_reused(tmp_path):
    """禁止把上次失败、不同补丁或人工改动目录作为干净源码使用。"""
    archive, root, _ = fixture(tmp_path)
    directory = tmp_path / "build"
    directory.mkdir()
    with pytest.raises(FileExistsError):
        prepare_source(archive, directory, root)


def test_user_git_line_endings_cannot_change_controlled_source(tmp_path, monkeypatch):
    """Windows 用户级换行设置不能改变与 Ubuntu 相同的补丁结果。"""
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.autocrlf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "true")
    monkeypatch.setenv("GIT_CONFIG_KEY_1", "core.eol")
    monkeypatch.setenv("GIT_CONFIG_VALUE_1", "crlf")
    archive, root, _ = fixture(tmp_path)
    source, _, _ = prepare_source(archive, tmp_path / "build", root)
    assert (source / "source.txt").read_bytes() == b"new\n"


def test_native_build_keeps_explicit_prefix_in_child_environment(tmp_path, monkeypatch):
    """只验证构建命令传递，模拟 wheel 不作为原生加载或算法验收。"""
    work = tmp_path / "build-work"
    work.mkdir()
    source = work / "source"
    source.mkdir()
    spec = {"version": "0.20.0+amvision.1", "cmake_options": {"BUILD_GUI": "OFF"}}
    monkeypatch.setattr(
        build_controlled_open3d,
        "prepare_source",
        lambda *a: (source, spec, {"version": spec["version"]}),
    )
    monkeypatch.setenv("CMAKE_PREFIX_PATH", str(tmp_path / "existing"))
    monkeypatch.setenv("CPATH", str(tmp_path / "existing-headers"))
    calls = []

    def run(command, *, check, env):
        """模拟工具产物；记录父 CMake 与构建子进程的相同环境。"""
        calls.append((command, env))
        if "--build" not in command:
            return
        build = work / "build"
        output = build / "lib/python_package/pip_package"
        output.mkdir(parents=True)
        (build / "CMakeCache.txt").write_text("test cache", encoding="utf-8")
        with zipfile.ZipFile(
            output / "open3d-0.20.0+amvision.1-test.whl", "w"
        ) as archive:
            archive.writestr(
                "open3d-0.20.0+amvision.1.dist-info/METADATA",
                f"Name: {build_controlled_open3d.distribution_name()}\nVersion: 0.20.0+amvision.1\n",
            )
            archive.writestr(
                f"open3d/pybind{EXTENSION_SUFFIXES[0]}", "not a native module"
            )

    monkeypatch.setattr(build_controlled_open3d.subprocess, "run", run)
    args = SimpleNamespace(
        archive=tmp_path / "archive",
        work_dir=work,
        prepare_only=False,
        cmake="explicit-cmake",
        generator="Ninja",
        jobs=2,
        build_prefix=tmp_path / "prefix",
        download_dir=tmp_path / "downloads",
        wheel_dir=tmp_path / "wheels",
    )
    build_controlled_open3d.build(args, tmp_path / "patches")
    import os

    expected = os.pathsep.join(
        (str(args.build_prefix.resolve()), str(tmp_path / "existing"))
    )
    assert len(calls) == 3
    assert "import open3d" in calls[2][0][2]
    assert str((work / "build/lib/python_package").resolve()) in calls[2][0]
    for _, environment in calls:
        assert environment["CMAKE_BUILD_PARALLEL_LEVEL"] == "2"
        assert environment["CPATH"] == os.pathsep.join(
            (str(args.build_prefix / "include"), str(tmp_path / "existing-headers"))
        )
        assert environment["CMAKE_PREFIX_PATH"] == expected
        assert environment["PATH"].split(os.pathsep)[0] == str(
            args.build_prefix / "bin"
        )
    assert f"-DCMAKE_PREFIX_PATH={args.build_prefix.resolve()}" in calls[0][0]
    assert (
        f"-DOPEN3D_THIRD_PARTY_DOWNLOAD_DIR={args.download_dir.resolve()}"
        in calls[0][0]
    )


@pytest.mark.parametrize("layout", ["legacy", "missing", "duplicate", "wrong-version"])
def test_wheel_layout_and_version_rejected(tmp_path, layout):
    """布局测试只验证封装检查，不将占位二进制当作实际可加载模块。"""
    wheel = tmp_path / "candidate.whl"
    version = "0.20.0+amvision.1"
    with zipfile.ZipFile(wheel, "w") as archive:
        actual = "0.20.0" if layout == "wrong-version" else version
        archive.writestr(
            f"open3d-{version}.dist-info/METADATA",
            f"Name: {build_controlled_open3d.distribution_name()}\nVersion: {actual}\n",
        )
        suffix = EXTENSION_SUFFIXES[0]
        if layout == "legacy":
            archive.writestr(f"open3d/cpu/pybind{suffix}", b"test-only")
        elif layout != "missing":
            archive.writestr(f"open3d/pybind{suffix}", b"test-only")
        if layout == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr(f"open3d/pybind{suffix}", b"second-test-only")
    with pytest.raises(ValueError, match="identity mismatch|unique native root module"):
        build_controlled_open3d.validate_wheel(wheel, version)


@pytest.mark.parametrize("target,name", [("win32", "open3d"), ("linux", "open3d-cpu")])
def test_cpu_distribution_identity(tmp_path, monkeypatch, target, name):
    """平台发行名与导入模块名不同；拒绝另一平台发行名。"""
    monkeypatch.setattr(build_controlled_open3d.sys, "platform", target)
    monkeypatch.setattr(build_controlled_open3d.platform, "machine", lambda: "x86_64")
    assert build_controlled_open3d.distribution_name() == name
    for actual in (name, "open3d-cuda"):
        wheel = tmp_path / f"{actual}.whl"
        with zipfile.ZipFile(wheel, "w") as archive:
            archive.writestr(
                "test.dist-info/METADATA",
                f"Name: {actual}\nVersion: 0.20.0+amvision.1\n",
            )
            archive.writestr(f"open3d/pybind{EXTENSION_SUFFIXES[0]}", b"test-only")
        if actual == name:
            build_controlled_open3d.validate_wheel(wheel, "0.20.0+amvision.1")
        else:
            with pytest.raises(ValueError, match="identity mismatch"):
                build_controlled_open3d.validate_wheel(wheel, "0.20.0+amvision.1")


@pytest.mark.parametrize("count", [0, 2])
def test_collect_rejects_nonunique_artifacts(tmp_path, count):
    """收集阶段不能选择不完整或混有多轮构建的目录。"""
    output = tmp_path / "build/lib/python_package/pip_package"
    output.mkdir(parents=True)
    for index in range(count):
        (output / f"candidate-{index}.whl").touch()
    with pytest.raises(ValueError, match="exactly one"):
        build_controlled_open3d.collect_wheel(
            tmp_path / "build", tmp_path / "wheels", {"version": "0.20.0+amvision.1"}
        )
    assert not (tmp_path / "wheels").exists()


def test_failed_native_import_does_not_collect_wheel(tmp_path, monkeypatch):
    """链接失败必须阻止收集，不将可压缩的 wheel 当成可加载的产物。"""
    work = tmp_path / "work"
    work.mkdir()
    spec = {"version": "0.20.0+amvision.1", "cmake_options": {}}
    monkeypatch.setattr(
        build_controlled_open3d, "prepare_source", lambda *a: (work, spec, {})
    )

    def run(command, *, check, env):
        """模拟最后的真实导入进程失败，不模拟成功原生模块。"""
        if "-c" in command:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(build_controlled_open3d.subprocess, "run", run)
    args = SimpleNamespace(
        archive=tmp_path / "input",
        work_dir=work,
        prepare_only=False,
        cmake="cmake",
        generator="Ninja",
        jobs=1,
        build_prefix=None,
        download_dir=None,
        wheel_dir=tmp_path / "wheels",
    )
    with pytest.raises(subprocess.CalledProcessError):
        build_controlled_open3d.build(args, tmp_path / "patches")
    assert not args.wheel_dir.exists()
