"""RF-DETR core 工具函数模块：`utilities.package`。"""

import os
import subprocess
from importlib.metadata import PackageNotFoundError, version


def get_version(package_name: str = "rfdetr") -> str | None:
    """执行 `get_version`。
    
    参数：
    - `package_name`：传入的 `package_name` 参数。
    
    返回：
    - 当前函数的执行结果。
    """
    try:
        return version(package_name)
    except PackageNotFoundError:
        return None


def get_sha() -> str:
    """执行 `get_sha`。
    
    返回：
    - 当前函数的执行结果。
    """
    cwd = os.path.dirname(os.path.abspath(__file__))

    def _run(command: list[str]) -> str:
        return subprocess.check_output(command, cwd=cwd).decode("ascii").strip()

    try:
        sha = _run(["git", "rev-parse", "HEAD"])
        diff_result = subprocess.run(
            ["git", "diff-index", "--quiet", "HEAD", "--"],
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
        )
        if diff_result.returncode not in (0, 1):
            raise subprocess.CalledProcessError(
                returncode=diff_result.returncode,
                cmd=["git", "diff-index", "--quiet", "HEAD", "--"],
                output=diff_result.stdout,
                stderr=diff_result.stderr,
            )
        has_diff = diff_result.returncode == 1
        status = "has uncommitted changes" if has_diff else "clean"
        branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        return f"sha: {sha}, status: {status}, branch: {branch}"
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


