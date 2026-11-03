"""同机点云工具的发行清单；不携带测试、业务数据或第二套协议实现。"""

from hashlib import sha256
from pathlib import Path
import shutil


# 源码和发行 app 保留同一相对布局，生成器及文档链接不依赖开发目录。
APPLICATION_FILES = (
    "runtimes/clients/point_cloud/__init__.py",
    "runtimes/clients/point_cloud/__main__.py",
    "runtimes/clients/point_cloud/client.py",
    "runtimes/clients/point_cloud/README.md",
    "scripts/metrology_workpiece.py",
    "docs/examples/workflows/lithium_workpiece.application.json",
    "docs/examples/workflows/lithium_workpiece.template.json",
    "docs/examples/workflows/lithium-workpiece.md",
)
LAUNCHER_FILE = "launchers/client/invoke_point_cloud.py"


def copy_point_cloud_delivery(source_root: Path, release_root: Path) -> dict:
    """按白名单装配工具并记录字节摘要；缺文件立即失败，不生成空壳。"""
    sources = [(name, f"app/{name}") for name in APPLICATION_FILES]
    sources.append((f"runtimes/{LAUNCHER_FILE}", LAUNCHER_FILE))
    for source, _ in sources:
        if not (source_root / source).is_file():
            raise FileNotFoundError(f"点云调用工具缺少发行文件: {source}")
    files = []
    for source, target in sources:
        destination = release_root / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / source, destination)
        content = destination.read_bytes()
        files.append(
            dict(path=target, size=len(content), sha256=sha256(content).hexdigest())
        )
    return dict(
        python_launcher=LAUNCHER_FILE,
        client_module="runtimes.clients.point_cloud",
        recipe_module="scripts.metrology_workpiece",
        files=files,
    )


def validate_point_cloud_delivery(release_root: Path, manifest: object) -> list[str]:
    """验证固定清单和摘要；不读取清单中提供的任意文件路径。"""
    expected = {f"app/{name}" for name in APPLICATION_FILES} | {LAUNCHER_FILE}
    if not isinstance(manifest, dict) or (
        manifest.get("python_launcher") != LAUNCHER_FILE
        or manifest.get("client_module") != "runtimes.clients.point_cloud"
        or manifest.get("recipe_module") != "scripts.metrology_workpiece"
    ):
        return ["点云调用工具发行清单缺失或无效，请重新 assemble-release"]
    entries = manifest.get("files")
    if (
        not isinstance(entries, list)
        or len(entries) != len(expected)
        or any(
            not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
            for entry in entries
        )
        or {entry["path"] for entry in entries} != expected
    ):
        return ["点云调用工具发行文件集合不完整或含未知文件"]
    issues = []
    root = release_root.resolve()
    for entry in entries:
        path = root / entry["path"]
        try:
            if not path.resolve().is_relative_to(root):
                raise ValueError("文件指向发行目录外")
            content = path.read_bytes()
            if (
                type(entry.get("size")) is not int
                or entry["size"] != len(content)
                or (entry.get("sha256") != sha256(content).hexdigest())
            ):
                raise ValueError("文件长度或摘要不一致")
        except (OSError, ValueError) as error:
            issues.append(f"点云调用工具文件无效: {entry['path']}: {error}")
    return issues
