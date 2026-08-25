"""backend 节点系统惰性导出。"""

from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORT_MODULES = {
    "get_core_workflow_node_definitions": "backend.nodes.core_catalog",
    "get_core_workflow_payload_contracts": "backend.nodes.core_catalog",
    "register_core_node_handlers": "backend.nodes.core_runtime_handlers",
    "LocalNodePackLoader": "backend.nodes.local_node_pack_loader",
    "NodeCatalogRegistry": "backend.nodes.node_catalog_registry",
    "NodeCatalogSnapshot": "backend.nodes.node_pack_loader",
    "NodePackLoader": "backend.nodes.node_pack_loader",
    "LocalNodePackLifecycleManager": "backend.nodes.node_pack_lifecycle",
}

_RUNTIME_SUPPORT_EXPORTS = {
    "ExecutionImageEntry",
    "ExecutionImageRegistry",
    "IMAGE_TRANSPORT_BUFFER",
    "IMAGE_TRANSPORT_FRAME",
    "IMAGE_TRANSPORT_LOCAL_PATH",
    "IMAGE_TRANSPORT_MEMORY",
    "IMAGE_TRANSPORT_STORAGE",
    "ResolvedImageInput",
    "RESPONSE_IMAGE_TRANSPORT_INLINE_BASE64",
    "RESPONSE_IMAGE_TRANSPORT_STORAGE_REF",
    "build_image_payload",
    "build_local_image_payload",
    "build_memory_image_payload",
    "build_response_image_payload",
    "build_runtime_image_object_key",
    "build_storage_image_payload",
    "copy_image_payload",
    "infer_media_type",
    "infer_media_type_from_image_bytes",
    "infer_file_extension_from_media_type",
    "load_image_bytes",
    "load_image_bytes_from_payload",
    "load_image_matrix",
    "load_image_matrix_from_payload",
    "prepare_workflow_image_access_timings",
    "read_workflow_image_access_timings",
    "register_image_bytes",
    "register_image_matrix",
    "require_dataset_storage",
    "require_execution_image_registry",
    "require_image_payload",
    "require_local_buffer_reader",
    "resolve_image_reference",
    "resolve_image_input",
    "write_image_bytes",
}

_EXPORT_MODULES.update(
    {name: "backend.nodes.runtime_support" for name in _RUNTIME_SUPPORT_EXPORTS}
)

__all__ = list(_EXPORT_MODULES)


def __getattr__(name: str) -> Any:
    """首次访问公开名称时加载实际模块，并缓存解析结果。"""

    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    """让交互式检查可以看到全部惰性公开名称。"""

    return sorted((*globals(), *_EXPORT_MODULES))
