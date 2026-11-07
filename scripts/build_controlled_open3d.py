"""现有受控 wheel 入口的 Open3D 原生构建分支；不安装或替换业务依赖。"""

from email.parser import BytesParser
from hashlib import file_digest
from importlib.machinery import EXTENSION_SUFFIXES
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile


def digest(path: Path) -> str:
    """计算构建输入或产物的完整内容身份。"""
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def distribution_name() -> str:
    """遵循上游 CPU 构建在 Linux x64 的独立发行包名。"""
    if sys.platform.startswith("linux") and platform.machine() in ("x86_64", "AMD64"):
        return "open3d-cpu"
    return "open3d"


def validate_wheel(wheel: Path, version: str) -> None:
    """核对当前上游的根模块布局；旧 cpu 子目录不是 0.20 构建产物。"""
    with zipfile.ZipFile(wheel) as stream:
        names = stream.namelist()
        (name,) = [n for n in names if n.endswith(".dist-info/METADATA")]
        metadata = BytesParser().parsebytes(stream.read(name))
        if metadata["Name"] != distribution_name() or metadata["Version"] != version:
            raise ValueError("Built Open3D wheel identity mismatch")
        expected = {f"open3d/pybind{suffix}" for suffix in EXTENSION_SUFFIXES}
        if len([name for name in names if name in expected]) != 1:
            raise ValueError("Built Open3D wheel lacks unique native root module")


def prepare_source(archive: Path, workspace: Path, patch_root: Path) -> tuple:
    """验证归档后才创建目录；仅在空目录应用已固定的上游补丁。"""
    spec = json.loads((patch_root / "manifest.json").read_text("utf-8"))
    if digest(archive) != spec["source_sha256"]:
        raise ValueError("Upstream archive SHA-256 mismatch")
    workspace.mkdir(parents=True, exist_ok=False)
    source = workspace / spec["source_directory"]
    with tarfile.open(archive) as stream:
        # 上游唯一链接是给编辑器的说明；复制其已验证归档目标，免需 Windows 链接权限。
        members = stream.getmembers()
        links = [m for m in members if m.issym() or m.islnk()]
        expected = f"{spec['source_directory']}/.github/copilot-instructions.md"
        if any(m.name != expected or m.linkname != "../AGENTS.md" for m in links):
            raise ValueError("Unexpected source archive link")
        stream.extractall(
            workspace, members=[m for m in members if m not in links], filter="data"
        )
        for member in links:
            target = workspace / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / "AGENTS.md", target)
    for name, checksum in {**spec["original_files"], **spec["support_files"]}.items():
        if digest(source / name) != checksum:
            raise ValueError(f"Upstream file SHA-256 mismatch: {name}")
    # 构建目录可能位于宿主仓库的 .tmp；独立索引防止 git apply 静默跳过相对路径。
    subprocess.run(["git", "init", "--quiet", str(source.resolve())], check=True)
    patches = {}
    for name, checksum in spec["patches"].items():
        patch = (patch_root / name).resolve()
        if not patch.is_relative_to(patch_root.resolve()):
            raise ValueError("Patch path outside controlled source")
        if digest(patch) != checksum:
            raise ValueError("Controlled patch SHA-256 mismatch")
        command = ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "apply"]
        subprocess.run([*command, "--check", str(patch)], cwd=source, check=True)
        subprocess.run([*command, str(patch)], cwd=source, check=True)
        patches[name] = digest(patch)
    patched_files = {name: digest(source / name) for name in spec["original_files"]}
    if patched_files != spec["patched_files"]:
        raise ValueError("Patched source SHA-256 mismatch")
    identity = dict(
        package="open3d",
        version=spec["version"],
        source_commit=spec["source_commit"],
        source_sha256=spec["source_sha256"],
        patches=patches,
        patched_files=patched_files,
        support_files=spec["support_files"],
        cmake_options=spec["cmake_options"],
        python=sys.version,
        platform=platform.platform(),
    )
    (workspace / "source.build.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8"
    )
    return source, spec, identity


def build(args, patch_root: Path) -> None:
    """以调用方显式工具链构建正常 wheel；全部原生代码来自同一上游树。"""
    source, spec, identity = prepare_source(args.archive, args.work_dir, patch_root)
    if args.prepare_only:
        print(json.dumps(identity, indent=2))
        return
    build_dir = args.work_dir / "build"
    temporary = args.work_dir.resolve() / "build-temp"
    temporary.mkdir()
    environment = {
        **os.environ,
        "TMPDIR": str(temporary),
        "TMP": str(temporary),
        "TEMP": str(temporary),
        "SOURCE_DATE_EPOCH": "1767225600",
        # 外层 --parallel 不会自动限制 ExternalProject 内独立启动的构建。
        "CMAKE_BUILD_PARALLEL_LEVEL": str(args.jobs),
    }
    configure = [
        args.cmake,
        "-S",
        str(source.resolve()),
        "-B",
        str(build_dir.resolve()),
        "-G",
        args.generator,
        f"-DPython3_EXECUTABLE={sys.executable}",
        *(f"-D{key}={value}" for key, value in spec["cmake_options"].items()),
    ]
    if args.build_prefix:
        prefix = args.build_prefix.resolve()
        configure.append(f"-DCMAKE_PREFIX_PATH={prefix}")
        environment["PATH"] = str(prefix / "bin") + os.pathsep + environment["PATH"]
        # 上游的 ExternalProject 会启动独立 CMake，环境前缀必须继续传递。
        environment["CMAKE_PREFIX_PATH"] = os.pathsep.join(
            value
            for value in (str(prefix), environment.get("CMAKE_PREFIX_PATH"))
            if value
        )
        # GCC/Clang 的直接编译目标不一定经过 find_package 导入头文件目录。
        environment["CPATH"] = os.pathsep.join(
            value
            for value in (str(prefix / "include"), environment.get("CPATH"))
            if value
        )
        identity["build_prefix"] = str(prefix)
    if args.download_dir:
        downloads = args.download_dir.resolve()
        configure.append(f"-DOPEN3D_THIRD_PARTY_DOWNLOAD_DIR={downloads}")
        identity["download_dir"] = str(downloads)
    identity["configure"] = configure
    subprocess.run(configure, check=True, env=environment)
    subprocess.run(
        [
            args.cmake,
            "--build",
            str(build_dir.resolve()),
            "--config",
            "Release",
            "--target",
            "pip-package",
            "--parallel",
            str(args.jobs),
        ],
        check=True,
        env=environment,
    )
    # 仅有 wheel 元数据不足以证明链接完整；从构建目录导入实际原生模块。
    package_root = (build_dir / "lib/python_package").resolve()
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import pathlib,sys; sys.path.insert(0,sys.argv[1]); import open3d; "
            "assert pathlib.Path(open3d.__file__).resolve().is_relative_to(pathlib.Path(sys.argv[1])); "
            "assert open3d.__version__ == sys.argv[2]",
            str(package_root),
            spec["version"],
        ],
        check=True,
        env=environment,
    )
    collect_wheel(build_dir, args.wheel_dir, identity)


def collect_wheel(build_dir: Path, wheel_dir: Path, identity: dict) -> None:
    """核验并收集已完成原生构建的唯一产物，不重新执行编译。"""
    wheels = list((build_dir / "lib/python_package/pip_package").glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected exactly one built Open3D wheel")
    (wheel,) = wheels
    validate_wheel(wheel, identity["version"])
    identity["distribution"] = distribution_name()
    identity["wheel_sha256"] = digest(wheel)
    identity["cmake_cache_sha256"] = digest(build_dir / "CMakeCache.txt")
    wheel_dir.mkdir(parents=True, exist_ok=True)
    target = wheel_dir / wheel.name
    if target.exists() or target.with_suffix(".build.json").exists():
        raise ValueError("Wheel already exists; use a new output directory")
    shutil.copyfile(wheel, target)
    target.with_suffix(".build.json").write_text(
        json.dumps(identity, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(identity, indent=2))
