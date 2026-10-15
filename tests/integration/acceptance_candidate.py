"""冻结验收候选内容；工作区提交号不能代替未提交源码和实际发行文件摘要。"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess

import psutil

from tests.integration.acceptance_evidence import write_evidence
from tests.integration.release_environment import build_release_test_environment


def capture_host() -> dict[str, object]:
    """记录实际验收主机与驱动，不把某台机器上的通过推广到其他硬件。"""
    host: dict[str, object] = {"system": platform.platform(), "machine": platform.machine(),
        "processor": platform.processor(), "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False), "memory_bytes": psutil.virtual_memory().total}
    for name, command in {
        "nvidia": ["nvidia-smi", "--query-gpu=name,uuid,driver_version,memory.total", "--format=csv,noheader"],
        "power_scheme": ["powercfg", "/getactivescheme"],
    }.items():
        if not shutil.which(command[0]):
            host[name] = {"status": "unavailable"}
            continue
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=20, check=False)
            host[name] = {"status": "observed" if result.returncode == 0 else "unavailable",
                          "value": result.stdout.strip(), "error": result.stderr.strip()}
        except (OSError, subprocess.TimeoutExpired) as error:
            host[name] = {"status": "unavailable", "error": str(error)}
    return host


def file_digest(path: Path) -> dict[str, object]:
    """记录实际字节与摘要；不依赖修改时间或 Git 状态推断文件内容。"""
    _reject_link(path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": digest}


def _reject_link(path: Path) -> None:
    """冻结范围拒绝符号链接和 Windows junction，避免扫描越界或循环。"""
    if path.is_symlink() or path.is_junction():
        raise ValueError(f"冻结范围不能包含链接：{path}")


def inventory_files(inventory: dict[str, object]) -> set[Path]:
    """按清单中的固定扫描范围重建文件集合，缺失的固定文件也保留。"""
    if not isinstance(inventory, dict) or set(inventory) != {"trees", "files", "globs"}:
        raise ValueError("冻结清单缺少合法 inventory")
    files: set[Path] = set()

    def absolute(value: object) -> Path:
        """清单不依赖调用者 cwd 解释扫描位置。"""
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("冻结范围必须使用绝对路径")
        path = Path(value)
        _reject_link(path)
        return path

    for value in inventory["files"]:
        files.add(absolute(value))
    for tree in inventory["trees"]:
        root = absolute(tree["path"])
        excludes = tree["exclude_directories"]
        if not isinstance(excludes, list) or any(
            not isinstance(name, str) or name not in {"__pycache__", "bin", "obj", ".vs"}
            for name in excludes
        ):
            raise ValueError("冻结目录排除规则无效")
        if not root.exists():
            continue
        if not root.is_dir():
            raise ValueError(f"冻结目录已被替换：{root}")

        def scan_error(error: OSError) -> None:
            """扫描不可读必须失败，不能把不完整目录当作空目录。"""
            raise error

        for current, directories, names in os.walk(root, onerror=scan_error):
            directory = Path(current)
            for name in directories + names:
                _reject_link(directory / name)
            directories[:] = [name for name in directories if name not in excludes]
            files.update(directory / name for name in names)
    for spec in inventory["globs"]:
        directory = absolute(spec["directory"])
        if spec["pattern"] != "*.py":
            raise ValueError("冻结根文件扫描只允许 *.py")
        for path in directory.glob("*.py"):
            _reject_link(path)
            if path.is_file():
                files.add(path)
    return files


def verify_candidate(path: Path) -> dict[str, object]:
    """重新枚举冻结范围；新增、缺失及字节变化都阻止认证。"""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("format_id") != "amvision.acceptance-candidate.v2" or not manifest.get("files"):
        raise ValueError("冻结清单必须为 v2 且非空；旧清单需要重新冻结")
    current = inventory_files(manifest.get("inventory"))
    expected = {Path(item["path"]): item["sha256"] for item in manifest["files"]}
    if len(expected) != len(manifest["files"]):
        raise ValueError("冻结清单包含重复路径")
    added = sorted(str(target) for target in current - expected.keys())
    missing = sorted(str(target) for target in expected if target not in current or not target.is_file())
    changed = sorted(str(target) for target in current & expected.keys()
                     if target.is_file() and file_digest(target)["sha256"] != expected[target])
    differences = sorted(set(added + missing + changed))
    return {"status": "failed" if differences else "passed", "differences": differences,
            "added": added, "missing": missing, "changed": changed,
            "checked_files": len(manifest["files"]), "manifest_sha256": file_digest(path)["sha256"]}


def freeze_candidate(config_path: Path, output: Path) -> None:
    """冻结源码、实际发行代码、SDK、模型、配置、Python 与厂商运行时。"""
    if output.exists():
        raise FileExistsError(output)
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    release = Path(config["release_root"]).resolve()
    root = Path.cwd().resolve()
    trees = []
    for directory in ("backend", "tests/integration", "frontend/web-ui/src", "runtimes/launchers", "config", "sdks/dotnet/src", "sdks/dotnet/tests"):
        excludes = ["__pycache__"]
        if directory.startswith("sdks/"):
            excludes += ["bin", "obj", ".vs"]
        trees.append({"path": str(root / directory), "exclude_directories": excludes})
    for directory in ("app", "frontend", "config", "launchers", "custom_nodes", "manifests", "tools", "python"):
        trees.append({"path": str(release / directory), "exclude_directories": ["__pycache__"]})
    trees.append({"path": str(root / "sdks/dotnet/tests/Amvar.Vision.ContractTests/bin/Release/net472"), "exclude_directories": []})
    inventory = {"trees": trees, "globs": [{"directory": str(release), "pattern": "*.py"}],
                 "files": [str(p) for p in (release / "python/python.exe", config_path.resolve(),
                     Path(config["package"]).resolve(), Path(config["image"]).resolve(),
                     root / "frontend/web-ui/package.json", root / "frontend/web-ui/package-lock.json")]}
    inventory["files"].extend(str(Path(case["path"]).resolve())
                              for case in config.get("transport_matrix", {}).get("image_cases", []))
    files = inventory_files(inventory)
    environment = build_release_test_environment(release)
    python = str(release / "python/python.exe")
    dependencies = subprocess.check_output([python, "-I", "-m", "pip", "freeze", "--all"], env=environment, text=True, timeout=120)
    write_evidence(output, {"format_id": "amvision.acceptance-candidate.v2", "created_at": datetime.now(UTC).isoformat(),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "git_status": subprocess.check_output(["git", "status", "--porcelain"], text=True),
        "python_version": subprocess.check_output([python, "-V"], env=environment, text=True).strip(),
        "host": capture_host(),
        "dependencies": dependencies.splitlines(), "release_root": str(release),
        "inventory": inventory, "files": [file_digest(p) for p in sorted(files)]})


def main() -> None:
    """freeze 写入新清单，verify 对照既有清单。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        result = verify_candidate(args.manifest)
        print(json.dumps(result))
        if result["status"] != "passed":
            raise SystemExit(1)
    else:
        if args.config is None:
            parser.error("freeze 必须指定 --config")
        freeze_candidate(args.config, args.manifest)


if __name__ == "__main__":
    main()
