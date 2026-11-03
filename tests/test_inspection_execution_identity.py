"""改义节点沿冻结依赖审核重发，未受影响的业务图不被整体停用。"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.nodes.node_catalog_registry import NodeCatalogRegistry
from backend.service.application.errors import ResourceConflictError
from backend.service.application.workflows.app_version_service import (
    _node_dependency_payload,
    require_current_execution_identity,
)


def test_changed_inspection_nodes_require_republish_but_history_remains_data():
    """相同身份通过；字段或版本改变、缺节点身份均不能启动旧算法语义。"""
    registry = NodeCatalogRegistry()
    definition = next(
        item
        for item in registry.get_workflow_node_definitions()
        if item.node_type_id == "core.rule.check-limits"
    )
    template = SimpleNamespace(
        nodes=[SimpleNamespace(node_type_id=definition.node_type_id)]
    )
    dependency = _node_dependency_payload(definition, node_pack_manifest_sha256=None)
    frozen = {"nodes": [dependency]}
    require_current_execution_identity(
        template=template, dependencies=frozen, node_catalog_registry=registry
    )
    assert dependency["implementation_identity"]["review_required"] is True
    for field, value in (
        ("version", "0.1.8"),
        ("definition_sha256", "0" * 64),
        (
            "implementation_identity",
            {"source": "node-definition-version", "version": "0.1.8"},
        ),
    ):
        old = deepcopy(frozen)
        old["nodes"][0][field] = value
        unchanged = deepcopy(old)
        with pytest.raises(ResourceConflictError) as error:
            require_current_execution_identity(
                template=template, dependencies=old, node_catalog_registry=registry
            )
        assert error.value.details["requires_republish"] is True
        assert old == unchanged
    with pytest.raises(ResourceConflictError):
        require_current_execution_identity(
            template=template,
            dependencies={"nodes": []},
            node_catalog_registry=registry,
        )


def test_unrelated_production_nodes_are_not_frozen_by_inspection_upgrade():
    """原分类/普通值显示及文件输出不因三态批次要求重发。"""
    registry = NodeCatalogRegistry()
    ids = [
        "core.io.value-preview",
        "core.logic.payload-to-value",
        "core.output.json-save-local",
    ]
    template = SimpleNamespace(
        nodes=[SimpleNamespace(node_type_id=value) for value in ids]
    )
    frozen = {"nodes": [{"node_type_id": value, "version": "0.1.7"} for value in ids]}
    require_current_execution_identity(
        template=template, dependencies=frozen, node_catalog_registry=registry
    )
    assert (
        next(
            item
            for item in registry.get_workflow_node_definitions()
            if item.node_type_id == "core.io.value-preview"
        ).version
        == "2.0.0"
    )


def test_removing_review_flag_does_not_bypass_previously_frozen_requirement():
    """发布身份包含的审核要求不能因当前代码删掉标记而被跳过。"""
    registry = NodeCatalogRegistry()
    definition = next(
        item
        for item in registry.get_workflow_node_definitions()
        if item.node_type_id == "core.rule.check-limits"
    )
    old = _node_dependency_payload(definition, node_pack_manifest_sha256=None)
    changed = definition.model_copy(update={"metadata": {}})
    current = SimpleNamespace(
        get_workflow_node_definitions=lambda: (changed,),
        get_node_pack_manifests=lambda: (),
    )
    with pytest.raises(ResourceConflictError):
        require_current_execution_identity(
            template=SimpleNamespace(
                nodes=[SimpleNamespace(node_type_id=changed.node_type_id)]
            ),
            dependencies={"nodes": [old]},
            node_catalog_registry=current,
        )
