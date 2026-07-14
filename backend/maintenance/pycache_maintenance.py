"""Python pycache 清理和重建维护命令。"""

from __future__ import annotations

import compileall
import importlib.util
import re
import shutil
import site
from dataclasses import dataclass
from pathlib import Path


REBUILD_PYCACHE_COMMAND = "rebuild-pycache"
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT_SOURCE_ROOTS = (
    "backend",
    "custom_nodes",
    "tests",
    "scripts",
)
PROJECT_COMPILE_SKIP_PATTERN = re.compile(
    r"(^|[\\/])("
    r"\.git|"
    r"\.tmp|"
    r"\.pytest_cache|"
    r"\.mypy_cache|"
    r"\.ruff_cache|"
    r"__pypackages__|"
    r"node_modules|"
    r"release|"
    r"runtimes|"
    r"projectsrc"
    r")([\\/]|$)"
)


@dataclass(frozen=True)
class PycacheMaintenanceRequest:
    """描述一次 pycache 清理和重建请求。

    字段：
    - project_root：当前仓库根目录。
    - project_source_roots：要处理的仓库内 Python 源码目录，相对 project_root。
    - python_package_names：要额外处理的当前解释器依赖包名。
    - clean_enabled：是否删除已有 __pycache__ 目录。
    - compile_enabled：是否重新生成 pycache。
    """

    project_root: Path
    project_source_roots: tuple[str, ...]
    python_package_names: tuple[str, ...]
    clean_enabled: bool
    compile_enabled: bool


def rebuild_pycache(request: PycacheMaintenanceRequest) -> dict[str, object]:
    """清理并可选重建仓库源码和指定依赖包的 pycache。

    参数：
    - request：pycache 维护请求。

    返回：
    - dict[str, object]：维护结果摘要。
    """

    project_root = request.project_root.resolve()
    project_targets = _resolve_project_source_roots(
        project_root=project_root,
        source_roots=request.project_source_roots,
    )
    package_targets = _resolve_python_package_roots(request.python_package_names)
    target_results: list[dict[str, object]] = []
    for target in project_targets:
        target_results.append(
            _process_pycache_target(
                target_kind="project",
                target_name=target.relative_to(project_root).as_posix(),
                target_path=target,
                clean_enabled=request.clean_enabled,
                compile_enabled=request.compile_enabled,
                compile_skip_pattern=PROJECT_COMPILE_SKIP_PATTERN,
            )
        )
    for package_name, package_root in package_targets:
        target_results.append(
            _process_pycache_target(
                target_kind="python-package",
                target_name=package_name,
                target_path=package_root,
                clean_enabled=request.clean_enabled,
                compile_enabled=request.compile_enabled,
                compile_skip_pattern=None,
            )
        )

    deleted_pycache_count = sum(
        int(item["deleted_pycache_count"]) for item in target_results
    )
    compile_failed_targets = [
        item["name"]
        for item in target_results
        if item["compiled"] is False
    ]
    return {
        "command": REBUILD_PYCACHE_COMMAND,
        "project_root": str(project_root),
        "clean_enabled": request.clean_enabled,
        "compile_enabled": request.compile_enabled,
        "deleted_pycache_count": deleted_pycache_count,
        "compile_failed_targets": compile_failed_targets,
        "targets": target_results,
    }


def build_pycache_request(
    *,
    project_root: Path = REPOSITORY_ROOT,
    project_source_roots: tuple[str, ...] | None = None,
    python_package_names: tuple[str, ...] = (),
    clean_only: bool = False,
    compile_only: bool = False,
) -> PycacheMaintenanceRequest:
    """构造 pycache 维护请求并处理互斥选项。

    参数：
    - project_root：当前仓库根目录。
    - project_source_roots：可选源码目录；为空时使用默认源码目录。
    - python_package_names：可选依赖包名，例如 sqlalchemy。
    - clean_only：只删除 pycache，不重新编译。
    - compile_only：只重新编译，不删除已有 pycache。

    返回：
    - PycacheMaintenanceRequest：规范化后的请求。
    """

    if clean_only and compile_only:
        raise ValueError("clean_only 和 compile_only 不能同时启用")
    clean_enabled = not compile_only
    compile_enabled = not clean_only
    normalized_roots = (
        project_source_roots
        if project_source_roots is not None and len(project_source_roots) > 0
        else DEFAULT_PROJECT_SOURCE_ROOTS
    )
    normalized_packages = tuple(
        item.strip()
        for item in python_package_names
        if isinstance(item, str) and item.strip()
    )
    return PycacheMaintenanceRequest(
        project_root=project_root,
        project_source_roots=tuple(normalized_roots),
        python_package_names=normalized_packages,
        clean_enabled=clean_enabled,
        compile_enabled=compile_enabled,
    )


def _resolve_project_source_roots(
    *,
    project_root: Path,
    source_roots: tuple[str, ...],
) -> list[Path]:
    """把相对源码目录解析为仓库内绝对路径。"""

    resolved_roots: list[Path] = []
    for source_root in source_roots:
        candidate = (project_root / source_root).resolve()
        _ensure_path_inside(candidate, project_root)
        if candidate.exists():
            resolved_roots.append(candidate)
    return resolved_roots


def _resolve_python_package_roots(package_names: tuple[str, ...]) -> list[tuple[str, Path]]:
    """把当前解释器中的 Python package 名解析为 site-packages 内路径。"""

    if len(package_names) == 0:
        return []
    site_roots = _resolve_site_package_roots()
    package_roots: list[tuple[str, Path]] = []
    for package_name in package_names:
        spec = importlib.util.find_spec(package_name)
        if spec is None:
            raise ValueError(f"找不到 Python package: {package_name}")
        if spec.submodule_search_locations:
            package_root = Path(next(iter(spec.submodule_search_locations))).resolve()
        elif spec.origin:
            package_root = Path(spec.origin).resolve().parent
        else:
            raise ValueError(f"无法解析 Python package 路径: {package_name}")
        if not any(_is_path_inside(package_root, site_root) for site_root in site_roots):
            raise ValueError(
                f"Python package 不在当前解释器 site-packages 中: {package_name} -> {package_root}"
            )
        package_roots.append((package_name, package_root))
    return package_roots


def _resolve_site_package_roots() -> list[Path]:
    """返回当前解释器可写依赖包目录，用于限制依赖包 pycache 清理边界。"""

    raw_roots: list[str] = []
    try:
        raw_roots.extend(site.getsitepackages())
    except AttributeError:
        pass
    user_site = site.getusersitepackages()
    if user_site:
        raw_roots.append(user_site)
    resolved_roots: list[Path] = []
    for raw_root in raw_roots:
        candidate = Path(raw_root).resolve()
        if candidate.exists():
            resolved_roots.append(candidate)
    if len(resolved_roots) == 0:
        raise ValueError("无法解析当前解释器 site-packages 目录")
    return resolved_roots


def _process_pycache_target(
    *,
    target_kind: str,
    target_name: str,
    target_path: Path,
    clean_enabled: bool,
    compile_enabled: bool,
    compile_skip_pattern: re.Pattern[str] | None,
) -> dict[str, object]:
    """处理单个 pycache 目标目录。"""

    deleted_pycache_dirs: list[str] = []
    if clean_enabled:
        deleted_pycache_dirs = _delete_pycache_dirs(target_path)
    compiled_ok: bool | None = None
    if compile_enabled:
        compiled_ok = compileall.compile_dir(
            str(target_path),
            force=True,
            quiet=1,
            legacy=False,
            rx=compile_skip_pattern,
            workers=1,
        )
    return {
        "kind": target_kind,
        "name": target_name,
        "path": str(target_path),
        "deleted_pycache_count": len(deleted_pycache_dirs),
        "deleted_pycache_sample": deleted_pycache_dirs[:10],
        "deleted_pycache_sample_truncated": len(deleted_pycache_dirs) > 10,
        "compiled": compiled_ok,
    }


def _delete_pycache_dirs(root_path: Path) -> list[str]:
    """删除指定目录下所有 __pycache__ 目录。"""

    deleted_dirs: list[str] = []
    pycache_dirs = sorted(
        (item for item in root_path.rglob("__pycache__") if item.is_dir()),
        key=lambda item: len(item.parts),
        reverse=True,
    )
    for pycache_dir in pycache_dirs:
        try:
            shutil.rmtree(pycache_dir)
        except FileNotFoundError:
            continue
        deleted_dirs.append(str(pycache_dir))
    return deleted_dirs


def _ensure_path_inside(candidate: Path, parent: Path) -> None:
    """确认 candidate 位于 parent 目录内。"""

    if not _is_path_inside(candidate, parent):
        raise ValueError(f"路径不在允许目录内: {candidate}")


def _is_path_inside(candidate: Path, parent: Path) -> bool:
    """判断 candidate 是否位于 parent 目录内或等于 parent。"""

    try:
        candidate.relative_to(parent)
    except ValueError:
        return False
    return True
