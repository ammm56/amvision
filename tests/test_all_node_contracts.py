"""全部核心和第三方 workflow 节点的目录契约测试。"""

from __future__ import annotations

from pathlib import Path

from backend.nodes.local_node_pack_loader import LocalNodePackLoader
from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.workflows.runtime_registry_loader import (
    WorkflowNodeRuntimeRegistryLoader,
)


def test_every_catalog_node_has_handler_and_complete_metadata() -> None:
    """逐个核对全部节点的执行器、参数说明和端口说明。"""

    node_pack_loader = LocalNodePackLoader(Path("custom_nodes"))
    node_pack_loader.refresh()
    catalog_registry = NodeCatalogRegistry(node_pack_loader=node_pack_loader)
    definitions = catalog_registry.get_workflow_node_definitions()
    runtime_loader = WorkflowNodeRuntimeRegistryLoader(
        node_catalog_registry=catalog_registry,
        node_pack_loader=node_pack_loader,
    )
    runtime_loader.refresh()
    runtime_registry = runtime_loader.get_runtime_registry()

    assert len(definitions) >= 370
    assert len({definition.node_type_id for definition in definitions}) == len(definitions)

    failures: list[str] = []
    for definition in definitions:
        if not definition.description.strip():
            failures.append(f"{definition.node_type_id}: 缺少节点说明")
        if not runtime_registry.has_registered_handler(node_definition=definition):
            failures.append(f"{definition.node_type_id}: 缺少运行时 handler")
        for direction, ports in (
            ("input", definition.input_ports),
            ("output", definition.output_ports),
        ):
            for port in ports:
                if not port.description.strip():
                    failures.append(
                        f"{definition.node_type_id}: {direction} port {port.name} 缺少说明"
                    )
        _collect_parameter_metadata_failures(
            definition.node_type_id,
            definition.parameter_schema,
            failures=failures,
        )
        if definition.parameter_ui_schema is not None:
            for field in definition.parameter_ui_schema.fields:
                if not field.description.strip():
                    failures.append(
                        f"{definition.node_type_id}: UI parameter "
                        f"{field.parameter_name} 缺少说明"
                    )

    assert failures == []


def _collect_parameter_metadata_failures(
    node_type_id: str,
    schema: dict[str, object],
    *,
    failures: list[str],
    path: str = "parameters",
) -> None:
    """递归收集 JSON Schema 参数标题和说明缺失项。"""

    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, property_schema in properties.items():
            if not isinstance(name, str) or not isinstance(property_schema, dict):
                continue
            property_path = f"{path}.{name}"
            if not _has_non_empty_text(property_schema.get("title")):
                failures.append(f"{node_type_id}: {property_path} 缺少 title")
            if not _has_non_empty_text(property_schema.get("description")):
                failures.append(f"{node_type_id}: {property_path} 缺少 description")
            _collect_parameter_metadata_failures(
                node_type_id,
                property_schema,
                failures=failures,
                path=property_path,
            )
    items = schema.get("items")
    if isinstance(items, dict):
        _collect_parameter_metadata_failures(
            node_type_id,
            items,
            failures=failures,
            path=f"{path}[]",
        )
    for composition_key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        variants = schema.get(composition_key)
        if not isinstance(variants, list):
            continue
        for index, variant in enumerate(variants):
            if isinstance(variant, dict):
                _collect_parameter_metadata_failures(
                    node_type_id,
                    variant,
                    failures=failures,
                    path=f"{path}.{composition_key}[{index}]",
                )


def _has_non_empty_text(value: object) -> bool:
    """判断对象是否为非空字符串。"""

    return isinstance(value, str) and bool(value.strip())
