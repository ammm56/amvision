"""core 节点目录扫描入口。"""

from __future__ import annotations

import importlib
import pkgutil
from functools import lru_cache

from backend.nodes.core_nodes._base import CoreNodeSpec
from backend.service.application.errors import ServiceConfigurationError


@lru_cache(maxsize=1)
def get_core_node_specs() -> tuple[CoreNodeSpec, ...]:
    """扫描并返回全部 core 节点规格。

    返回：
    - tuple[CoreNodeSpec, ...]：按模块名稳定排序后的 core 节点规格列表。
    """

    loaded_specs: list[CoreNodeSpec] = []
    for module_name in sorted(module_info.name for module_info in pkgutil.iter_modules(__path__)):  # type: ignore[name-defined]
        if module_name.startswith("_"):
            continue
        imported_module = importlib.import_module(f"{__name__}.{module_name}")
        core_node_spec = getattr(imported_module, "CORE_NODE_SPEC", None)
        if not isinstance(core_node_spec, CoreNodeSpec):
            raise ServiceConfigurationError(
                "core 节点模块缺少有效的 CORE_NODE_SPEC",
                details={"module_name": f"{__name__}.{module_name}"},
            )
        loaded_specs.append(core_node_spec)
    return tuple(loaded_specs)


__all__ = ["CoreNodeSpec", "get_core_node_specs"]