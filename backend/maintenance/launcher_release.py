"""验证并复制启动器正式发行包，不在 Python 组装阶段编译 C#。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil


def validate_launcher_package(source: Path) -> dict[str, object]:
    """校验 Windows x64 自带运行时和文件摘要，拒绝目录穿越及混入本地数据。"""
    source = source.resolve()
    manifest = json.loads((source / "launcher" / "launcher-release.json").read_text(encoding="utf-8"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("format_id") != "amvar.launcher-release.v2"
        or manifest.get("rid") != "win-x64"
        or manifest.get("self_contained") is not True
        or not isinstance(manifest.get("files"), list)
    ):
        raise ValueError("启动器发行清单格式无效")
    paths: set[str] = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not isinstance(entry.get("sha256"), str):
            raise ValueError("启动器文件条目格式无效")
        relative = entry["path"]
        candidate = (source / relative).resolve()
        if (
            not candidate.is_relative_to(source)
            or Path(relative).is_absolute()
            or any(part in {".", "..", ""} for part in relative.split("/"))
            or "\\" in relative
            or (relative != "amvar.launcher.exe" and not relative.startswith("launcher/"))
            or relative.casefold().startswith(("launcher/config/", "launcher/data/", "launcher/logs/"))
            or relative.split("/")[0].lower() in {"config", "data", "logs", "app", "python", "manifests"}
            or relative.casefold() in paths
        ):
            raise ValueError(f"启动器文件路径无效: {relative}")
        paths.add(relative.casefold())
        with candidate.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"启动器文件摘要不匹配: {relative}")
    required = {"amvar.launcher.exe", "launcher/amvar.launcher.dll", "launcher/coreclr.dll", "launcher/launcher-build-info.json", "launcher/tools/webview2/win-x64/msedgewebview2.exe"}
    if not required.issubset(paths):
        raise ValueError("启动器发行包缺少可执行文件、自带 .NET 或 Fixed Version WebView2")
    for name in ("amvar.launcher.exe", "launcher/coreclr.dll", "launcher/tools/webview2/win-x64/msedgewebview2.exe"):
        _validate_x64_pe(source / name)
    return manifest


def _validate_x64_pe(path: Path) -> None:
    """读取 PE 头的机器类型，防止 ARM64/x86 资产被错误标记为 win-x64。"""
    with path.open("rb") as stream:
        header = stream.read(64)
        if len(header) != 64 or header[:2] != b"MZ":
            raise ValueError(f"启动器资产不是有效 PE 文件: {path.name}")
        stream.seek(int.from_bytes(header[60:64], "little"))
        if stream.read(6) != b"PE\x00\x00\x64\x86":
            raise ValueError(f"启动器资产必须为 Windows x64: {path.name}")


def copy_launcher_package(source: Path, destination: Path, manifest: dict[str, object]) -> None:
    """按已校验的文件清单复制；配置另由发行模板提供。"""
    for entry in manifest["files"]:
        target = destination / entry["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / entry["path"], target)
    shutil.copy2(source / "launcher" / "launcher-release.json", destination / "launcher" / "launcher-release.json")
