"""core 节点目录扫描入口。"""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from backend.nodes.core_nodes.support.base import CoreNodeSpec
from backend.service.application.errors import ServiceConfigurationError


@lru_cache(maxsize=1)
def get_core_node_specs() -> tuple[CoreNodeSpec, ...]:
    """递归扫描并返回全部 core 节点规格。

    返回：
    - tuple[CoreNodeSpec, ...]：按模块路径稳定排序后的 core 节点规格列表。
    """

    loaded_specs: list[CoreNodeSpec] = []
    for module_name in _iter_core_node_module_names():
        imported_module = importlib.import_module(module_name)
        core_node_spec = getattr(imported_module, "CORE_NODE_SPEC", None)
        if not isinstance(core_node_spec, CoreNodeSpec):
            raise ServiceConfigurationError(
                "core 节点模块缺少有效的 CORE_NODE_SPEC",
                details={"module_name": module_name},
            )
        loaded_specs.append(core_node_spec)
    return tuple(loaded_specs)


def _iter_core_node_module_names() -> tuple[str, ...]:
    """返回需要作为 core 节点加载的模块路径。

    返回：
    - tuple[str, ...]：可导入的 core 节点模块路径。
    """

    module_names: list[str] = []
    package_prefix = f"{__name__}."
    for module_info in pkgutil.walk_packages(__path__, prefix=package_prefix):  # type: ignore[name-defined]
        if module_info.ispkg:
            continue
        relative_parts = module_info.name.removeprefix(package_prefix).split(".")
        if any(part.startswith("_") for part in relative_parts):
            continue
        if "support" in relative_parts:
            continue
        module_names.append(module_info.name)
    return tuple(sorted(module_names))


__all__ = ["CoreNodeSpec", "get_core_node_specs"]
