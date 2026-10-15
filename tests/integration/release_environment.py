"""发行验收服务的最小环境，避免开发机 conda 和应用配置掩盖发行缺失。"""

import os
from pathlib import Path


def build_release_test_environment(release_root: Path) -> dict[str, str]:
    """保留系统环境和显式 CUDA Toolkit，清除开发 Python、Node 和 AMVISION 覆盖。"""
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("CONDA", "PYTHON", "AMVISION_"))
                   and key.upper() != "PATH"}
    system_root = Path(environment.get("SystemRoot", environment.get("SYSTEMROOT", r"C:\Windows")))
    paths = [release_root / "python", system_root / "System32", system_root]
    cuda_root = environment.get("CUDA_PATH")
    if cuda_root:
        paths.append(Path(cuda_root) / "bin")
    environment.update(PATH=os.pathsep.join(str(path) for path in paths),
                       PYTHONNOUSERSITE="1", PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")
    return environment
