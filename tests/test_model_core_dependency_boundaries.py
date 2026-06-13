"""模型 core 运行时依赖边界测试。"""

from __future__ import annotations

import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODEL_RUNTIME_DIRS = (
    REPO_ROOT / "backend/service/application/models",
    REPO_ROOT / "backend/service/application/runtime",
)
DISALLOWED_IMPORT_ROOTS = {"ultralytics", "rfdetr"}


def test_model_runtime_does_not_import_external_model_packages() -> None:
    """模型运行时代码不能直接导入官方模型包。"""

    violations: list[str] = []
    for source_path in _iter_python_files(MODEL_RUNTIME_DIRS):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = alias.name.split(".", maxsplit=1)[0]
                    if root_name in DISALLOWED_IMPORT_ROOTS:
                        violations.append(f"{source_path.relative_to(REPO_ROOT)} imports {alias.name}")
            elif isinstance(node, ast.ImportFrom) and node.module:
                root_name = node.module.split(".", maxsplit=1)[0]
                if root_name in DISALLOWED_IMPORT_ROOTS:
                    violations.append(f"{source_path.relative_to(REPO_ROOT)} imports from {node.module}")

    assert violations == []


def test_model_runtime_does_not_reference_projectsrc() -> None:
    """模型运行时代码不能依赖 projectsrc 参考目录。"""

    violations: list[str] = []
    for source_path in _iter_python_files(MODEL_RUNTIME_DIRS):
        text = source_path.read_text(encoding="utf-8")
        if "projectsrc" in text:
            violations.append(str(source_path.relative_to(REPO_ROOT)))

    assert violations == []


def _iter_python_files(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    """列出指定目录下的 Python 文件。"""

    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.rglob("*.py")))
    return tuple(files)
