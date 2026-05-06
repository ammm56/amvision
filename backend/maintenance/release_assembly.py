"""backend-maintenance release 组装辅助。"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_BACKEND_DIR = REPOSITORY_ROOT / "backend"
SOURCE_CONFIG_DIR = REPOSITORY_ROOT / "config"
SOURCE_REQUIREMENTS_FILE = REPOSITORY_ROOT / "requirements.txt"
SOURCE_LAUNCHERS_DIR = REPOSITORY_ROOT / "runtimes" / "launchers"
SOURCE_FULL_LAUNCHERS_DIR = SOURCE_LAUNCHERS_DIR / "full"
SOURCE_RELEASE_PROFILES_DIR = REPOSITORY_ROOT / "runtimes" / "manifests" / "release-profiles"
SOURCE_WORKER_PROFILES_DIR = REPOSITORY_ROOT / "runtimes" / "manifests" / "worker-profiles"


@dataclass(frozen=True)
class ReleaseAssemblyRequest:
    """描述一次 release 组装请求。

    字段：
    - profile_id：要组装的 release profile id。
    - output_root：release 输出根目录。
    - overwrite：目标目录已存在时是否允许覆盖。
    """

    profile_id: str
    output_root: Path
    overwrite: bool = False

    def resolve_release_dir(self) -> Path:
        """返回当前 profile 的发行目录。"""

        return self.output_root.resolve() / self.profile_id


@dataclass(frozen=True)
class ReleaseAssemblyResult:
    """描述一次 release 组装结果。

    字段：
    - profile_id：本次组装的 release profile id。
    - release_dir：最终发行目录。
    - release_manifest_path：发行目录里的 release manifest 路径。
    - requirements_path：发行目录里的 requirements.txt 路径。
    - bundled_python_dir：发行目录里的 bundled Python 目录。
    - generated_root_launchers：发行目录根目录的一键启动脚本列表。
    - worker_profile_ids：本次打入发行目录的 worker profile id 列表。
    - generated_worker_launchers：自动生成的 worker wrapper 列表。
    - placeholder_dirs：本次创建但等待后续资产填充的目录列表。
    """

    profile_id: str
    release_dir: Path
    release_manifest_path: Path
    requirements_path: Path
    bundled_python_dir: Path
    generated_root_launchers: tuple[Path, ...]
    worker_profile_ids: tuple[str, ...]
    generated_worker_launchers: tuple[Path, ...]
    placeholder_dirs: tuple[Path, ...]


def _load_json_file(file_path: Path) -> dict[str, object]:
    """读取 JSON 文件并返回字典对象。"""

    return json.loads(file_path.read_text(encoding="utf-8"))


def _write_json_file(file_path: Path, payload: dict[str, object]) -> None:
    """把 JSON 对象写入目标文件。"""

    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _copy_file(source_path: Path, target_path: Path) -> None:
    """复制单个文件并确保目标目录存在。"""

    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def _copy_launcher_tree(release_dir: Path) -> None:
    """复制通用 launcher 脚本到发行目录。"""

    _copy_file(SOURCE_LAUNCHERS_DIR / "common.py", release_dir / "launchers" / "common.py")
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "service" / "start_backend_service.py",
        release_dir / "launchers" / "service" / "start_backend_service.py",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "service" / "start-backend-service.bat",
        release_dir / "launchers" / "service" / "start-backend-service.bat",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "service" / "start-backend-service.sh",
        release_dir / "launchers" / "service" / "start-backend-service.sh",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "worker" / "start_backend_worker.py",
        release_dir / "launchers" / "worker" / "start_backend_worker.py",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "worker" / "start-backend-worker.bat",
        release_dir / "launchers" / "worker" / "start-backend-worker.bat",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "worker" / "start-backend-worker.sh",
        release_dir / "launchers" / "worker" / "start-backend-worker.sh",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "maintenance" / "invoke_backend_maintenance.py",
        release_dir / "launchers" / "maintenance" / "invoke_backend_maintenance.py",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "maintenance" / "invoke-backend-maintenance.bat",
        release_dir / "launchers" / "maintenance" / "invoke-backend-maintenance.bat",
    )
    _copy_file(
        SOURCE_LAUNCHERS_DIR / "maintenance" / "invoke-backend-maintenance.sh",
        release_dir / "launchers" / "maintenance" / "invoke-backend-maintenance.sh",
    )


def _copy_full_root_launchers(release_dir: Path) -> tuple[Path, ...]:
    """复制 full 发布目录根目录的启动和停止脚本。

    参数：
    - release_dir：当前发行目录。

    返回：
    - tuple[Path, ...]：已复制到发行目录根目录的脚本列表。
    """

    root_launcher_paths = (
        release_dir / "start_amvision_full.py",
        release_dir / "start-amvision-full.bat",
        release_dir / "start-amvision-full.sh",
        release_dir / "stop_amvision_full.py",
        release_dir / "stop-amvision-full.bat",
        release_dir / "stop-amvision-full.sh",
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "start_amvision_full.py",
        root_launcher_paths[0],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "start-amvision-full.bat",
        root_launcher_paths[1],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "start-amvision-full.sh",
        root_launcher_paths[2],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "stop_amvision_full.py",
        root_launcher_paths[3],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "stop-amvision-full.bat",
        root_launcher_paths[4],
    )
    _copy_file(
        SOURCE_FULL_LAUNCHERS_DIR / "stop-amvision-full.sh",
        root_launcher_paths[5],
    )
    return root_launcher_paths


def _build_worker_windows_wrapper(profile_id: str) -> str:
    """生成带固定 profile 的 Windows worker wrapper。"""

    return (
        "@echo off\r\n"
        "setlocal\r\n"
        "set \"SCRIPT_DIR=%~dp0\"\r\n"
        "set \"PYTHON_EXE=%AMVISION_PYTHON_EXECUTABLE%\"\r\n"
        "if defined PYTHON_EXE goto run\r\n"
        "if exist \"%SCRIPT_DIR%..\\..\\python\\python.exe\" set \"PYTHON_EXE=%SCRIPT_DIR%..\\..\\python\\python.exe\"\r\n"
        "if defined PYTHON_EXE goto run\r\n"
        "set \"PYTHON_EXE=python\"\r\n"
        ":run\r\n"
        f"\"%PYTHON_EXE%\" \"%SCRIPT_DIR%start_backend_worker.py\" --worker-profile-file \"manifests/worker-profiles/{profile_id}.json\" %*\r\n"
        "endlocal\r\n"
    )


def _build_worker_linux_wrapper(profile_id: str) -> str:
    """生成带固定 profile 的 Linux worker wrapper。"""

    return (
        "#!/usr/bin/env sh\n"
        "set -eu\n"
        "SCRIPT_DIR=\"$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\"\n"
        "if [ -n \"${AMVISION_PYTHON_EXECUTABLE:-}\" ]; then\n"
        "  PYTHON_EXE=\"$AMVISION_PYTHON_EXECUTABLE\"\n"
        "elif [ -x \"$SCRIPT_DIR/../../python/bin/python3\" ]; then\n"
        "  PYTHON_EXE=\"$SCRIPT_DIR/../../python/bin/python3\"\n"
        "elif [ -x \"$SCRIPT_DIR/../../python/bin/python\" ]; then\n"
        "  PYTHON_EXE=\"$SCRIPT_DIR/../../python/bin/python\"\n"
        "else\n"
        "  PYTHON_EXE=python3\n"
        "fi\n"
        f"exec \"$PYTHON_EXE\" \"$SCRIPT_DIR/start_backend_worker.py\" --worker-profile-file \"manifests/worker-profiles/{profile_id}.json\" \"$@\"\n"
    )


def _copy_application_sources(release_dir: Path) -> None:
    """复制后端源码和基础配置到发行目录。"""

    shutil.copytree(SOURCE_BACKEND_DIR, release_dir / "app" / "backend", dirs_exist_ok=True)
    shutil.copytree(SOURCE_CONFIG_DIR, release_dir / "config", dirs_exist_ok=True)
    _copy_file(SOURCE_REQUIREMENTS_FILE, release_dir / "app" / "requirements.txt")


def _prepare_bundled_python_dir(release_dir: Path) -> Path:
    """创建或恢复发行目录中的 python 目录。

    参数：
    - release_dir：当前发行目录。

    返回：
    - Path：发行目录中的 python 目录路径。
    """

    release_python_dir = release_dir / "python"
    release_python_dir.mkdir(parents=True, exist_ok=True)
    return release_python_dir


def _stash_existing_python_dir(release_dir: Path) -> Path | None:
    """把已有 release 目录中的 python 目录临时搬离。

    参数：
    - release_dir：当前发行目录。

    返回：
    - Path | None：临时缓存目录；如果原目录中没有 python 目录则返回 None。
    """

    existing_python_dir = release_dir / "python"
    if not existing_python_dir.is_dir():
        return None

    temporary_root_dir = Path(
        tempfile.mkdtemp(prefix="amvision-release-python-", dir=str(release_dir.parent.resolve()))
    )
    shutil.move(str(existing_python_dir), str(temporary_root_dir / "python"))
    return temporary_root_dir


def _restore_preserved_python_dir(
    release_dir: Path,
    preserved_python_temp_dir: Path | None,
) -> Path:
    """把临时缓存的 python 目录恢复到新的 release 目录。

    参数：
    - release_dir：当前发行目录。
    - preserved_python_temp_dir：之前暂存 python 目录的缓存目录。

    返回：
    - Path：恢复后的发行目录 python 路径。
    """

    if preserved_python_temp_dir is None:
        return _prepare_bundled_python_dir(release_dir)

    release_python_dir = release_dir / "python"
    shutil.move(str(preserved_python_temp_dir / "python"), str(release_python_dir))
    shutil.rmtree(preserved_python_temp_dir, ignore_errors=True)
    return release_python_dir


def _materialize_placeholder_dirs(
    release_dir: Path,
    *,
    include_frontend: bool,
    include_plugins: bool,
) -> tuple[Path, ...]:
    """创建 release 目录中的占位目录。"""

    placeholder_dirs = [
        release_dir / "python",
        release_dir / "data",
        release_dir / "logs",
    ]
    if include_frontend:
        placeholder_dirs.append(release_dir / "frontend")
    if include_plugins:
        placeholder_dirs.append(release_dir / "plugins")
    for directory in placeholder_dirs:
        directory.mkdir(parents=True, exist_ok=True)
    return tuple(placeholder_dirs)


def assemble_release(request: ReleaseAssemblyRequest) -> ReleaseAssemblyResult:
    """按指定 release profile 组装发行目录。"""

    source_release_profile_path = SOURCE_RELEASE_PROFILES_DIR / f"{request.profile_id}.json"
    if not source_release_profile_path.is_file():
        raise FileNotFoundError(f"release profile 不存在: {source_release_profile_path}")

    source_release_profile = _load_json_file(source_release_profile_path)
    release_dir = request.resolve_release_dir()
    preserved_python_temp_dir: Path | None = None
    if release_dir.exists():
        if not request.overwrite:
            raise FileExistsError(f"release 目录已存在: {release_dir}")
        preserved_python_temp_dir = _stash_existing_python_dir(release_dir)
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True, exist_ok=True)

    _copy_application_sources(release_dir)
    requirements_path = release_dir / "app" / "requirements.txt"
    bundled_python_dir = _restore_preserved_python_dir(release_dir, preserved_python_temp_dir)
    _copy_launcher_tree(release_dir)
    generated_root_launchers = _copy_full_root_launchers(release_dir)

    worker_section = source_release_profile["worker"]
    assert isinstance(worker_section, dict)
    worker_profile_ids_raw = worker_section.get("worker_profile_ids")
    if not isinstance(worker_profile_ids_raw, list) or not worker_profile_ids_raw:
        raise ValueError("release profile 必须包含非空 worker.worker_profile_ids")
    worker_profile_ids = tuple(str(profile_id) for profile_id in worker_profile_ids_raw)

    worker_entries: list[dict[str, object]] = []
    generated_worker_launchers: list[Path] = []
    for profile_id in worker_profile_ids:
        source_worker_profile_path = SOURCE_WORKER_PROFILES_DIR / f"{profile_id}.json"
        if not source_worker_profile_path.is_file():
            raise FileNotFoundError(f"worker profile 不存在: {source_worker_profile_path}")
        source_worker_profile = _load_json_file(source_worker_profile_path)
        release_worker_profile_path = release_dir / "manifests" / "worker-profiles" / f"{profile_id}.json"
        _write_json_file(release_worker_profile_path, source_worker_profile)

        windows_wrapper_path = release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.bat"
        linux_wrapper_path = release_dir / "launchers" / "worker" / f"start-{profile_id}-worker.sh"
        windows_wrapper_path.write_text(_build_worker_windows_wrapper(profile_id), encoding="utf-8")
        linux_wrapper_path.write_text(_build_worker_linux_wrapper(profile_id), encoding="utf-8")
        generated_worker_launchers.extend((windows_wrapper_path, linux_wrapper_path))

        worker_entries.append(
            {
                "profile_id": source_worker_profile["profile_id"],
                "display_name": source_worker_profile["display_name"],
                "description": source_worker_profile["description"],
                "manifest": f"manifests/worker-profiles/{profile_id}.json",
                "python_launcher": "launchers/worker/start_backend_worker.py",
                "windows_launcher": f"launchers/worker/start-{profile_id}-worker.bat",
                "linux_launcher": f"launchers/worker/start-{profile_id}-worker.sh",
                "enabled_consumer_kinds": source_worker_profile["enabled_consumer_kinds"],
                "max_concurrent_tasks": source_worker_profile.get("max_concurrent_tasks", 1),
                "poll_interval_seconds": source_worker_profile.get("poll_interval_seconds", 1.0),
            }
        )

    artifacts_section = source_release_profile["artifacts"]
    assert isinstance(artifacts_section, dict)
    placeholder_dirs = _materialize_placeholder_dirs(
        release_dir,
        include_frontend=bool(artifacts_section.get("include_frontend", False)),
        include_plugins=bool(artifacts_section.get("include_plugins", False)),
    )

    release_manifest = {
        "profile_id": source_release_profile["profile_id"],
        "display_name": source_release_profile["display_name"],
        "description": source_release_profile["description"],
        "requirements_file": "app/requirements.txt",
        "service": {
            "python_launcher": "launchers/service/start_backend_service.py",
            "windows_launcher": "launchers/service/start-backend-service.bat",
            "linux_launcher": "launchers/service/start-backend-service.sh",
            "hosted_task_manager_enabled": source_release_profile["service"]["hosted_task_manager_enabled"],
        },
        "workers": worker_entries,
        "maintenance": {
            "python_launcher": "launchers/maintenance/invoke_backend_maintenance.py",
            "windows_launcher": "launchers/maintenance/invoke-backend-maintenance.bat",
            "linux_launcher": "launchers/maintenance/invoke-backend-maintenance.sh",
            "default_command": source_release_profile["maintenance"]["default_command"],
        },
        "stack": {
            "python_launcher": "start_amvision_full.py",
            "windows_launcher": "start-amvision-full.bat",
            "linux_launcher": "start-amvision-full.sh",
            "logs_dir": "logs/full-stack",
            "state_file": "logs/full-stack/runtime-state.json",
            "stop_python_launcher": "stop_amvision_full.py",
            "stop_windows_launcher": "stop-amvision-full.bat",
            "stop_linux_launcher": "stop-amvision-full.sh",
        },
        "artifacts": artifacts_section,
        "layout": {
            "app_dir": "app",
            "config_dir": "config",
            "data_dir": "data",
            "logs_dir": "logs",
            "python_dir": "python",
        },
    }
    release_manifest_path = release_dir / "manifests" / "release-profiles" / f"{request.profile_id}.json"
    _write_json_file(release_manifest_path, release_manifest)

    return ReleaseAssemblyResult(
        profile_id=request.profile_id,
        release_dir=release_dir,
        release_manifest_path=release_manifest_path,
        requirements_path=requirements_path,
        bundled_python_dir=bundled_python_dir,
        generated_root_launchers=generated_root_launchers,
        worker_profile_ids=worker_profile_ids,
        generated_worker_launchers=tuple(generated_worker_launchers),
        placeholder_dirs=placeholder_dirs,
    )