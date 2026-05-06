"""运行时 launcher 共用辅助。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


def resolve_app_root(
    *,
    script_file: Path,
    explicit_app_root: str | None = None,
) -> Path:
    """解析当前 launcher 对应的应用根目录。"""

    if explicit_app_root is not None and explicit_app_root.strip():
        return Path(explicit_app_root).resolve()

    resolved_script_file = script_file.resolve()
    for candidate in (resolved_script_file.parent, *resolved_script_file.parents):
        if (candidate / "backend").is_dir() and (candidate / "config").is_dir():
            return candidate
        if (candidate / "app" / "backend").is_dir() and (candidate / "config").is_dir():
            return candidate
    raise FileNotFoundError("无法从当前 launcher 位置解析应用根目录")


def resolve_code_root(app_root: Path) -> Path:
    """解析当前应用可导入 backend 包的代码根目录。"""

    if (app_root / "backend").is_dir():
        return app_root
    bundled_code_root = app_root / "app"
    if (bundled_code_root / "backend").is_dir():
        return bundled_code_root
    raise FileNotFoundError(f"未找到 backend 代码目录: {app_root}")


def resolve_path(app_root: Path, path_value: str) -> Path:
    """把相对或绝对路径解析成绝对路径。"""

    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate.resolve()
    return (app_root / candidate).resolve()


def load_json_file(app_root: Path, path_value: str) -> dict[str, object]:
    """读取相对应用根目录的 JSON 文件。"""

    file_path = resolve_path(app_root, path_value)
    return json.loads(file_path.read_text(encoding="utf-8"))


def json_env_value(value: object) -> str:
    """把复杂环境变量值序列化为 JSON 字符串。"""

    return json.dumps(value, ensure_ascii=False)


def run_python_module(
    *,
    app_root: Path,
    module_name: str,
    module_args: Sequence[str],
    python_executable: str | None = None,
    extra_env: Mapping[str, str] | None = None,
) -> int:
    """用指定 Python 解释器在目标应用根目录启动模块。"""

    runtime_env = os.environ.copy()
    code_root = resolve_code_root(app_root)
    existing_python_path = runtime_env.get("PYTHONPATH")
    runtime_env["PYTHONPATH"] = (
        str(code_root)
        if not existing_python_path
        else os.pathsep.join((str(code_root), existing_python_path))
    )
    if extra_env is not None:
        runtime_env.update(extra_env)

    command = [python_executable or sys.executable, "-m", module_name, *module_args]
    completed = subprocess.run(
        command,
        cwd=str(app_root),
        env=runtime_env,
        check=False,
    )
    return completed.returncode