"""几何原生依赖统一准入，版本与平台包名沿节点 manifest 解析。"""

import importlib
from pathlib import Path
import platform

from packaging.requirements import Requirement

from backend.contracts.nodes.node_pack_manifest import NodePackManifest
from backend.service.application.errors import ServiceConfigurationError
from backend.service.infrastructure.controlled_dependencies import (
    require_controlled_distribution,
)


def require_open3d():
    """只加载本平台已核定的受控库；发行元数据和实际模块版本必须一致。"""
    manifest = NodePackManifest.model_validate_json(
        (Path(__file__).parents[1] / "manifest.json").read_text(encoding="utf-8")
    )
    try:
        requirements = manifest.compatibility.distributions_for(
            platform.system().lower()
        )
        matches = [
            Requirement(value)
            for value in requirements
            if Requirement(value).name in {"open3d", "open3d-cpu"}
        ]
        if len(matches) != 1:
            raise ValueError("Open3D 平台依赖必须唯一")
        requirement = matches[0]
        specifiers = tuple(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != "==":
            raise ValueError("Open3D 必须锁定精确版本")
        expected = specifiers[0].version
    except ValueError as error:
        raise ServiceConfigurationError("Open3D 平台依赖声明无效") from error
    require_controlled_distribution(requirement.name, expected)
    try:
        module = importlib.import_module("open3d")
    except (ImportError, OSError) as error:
        raise ServiceConfigurationError("受控 Open3D 原生库无法加载") from error
    if module.__version__ != expected:
        raise ServiceConfigurationError("Open3D 实际加载模块与受控发行版本不一致")
    return module
