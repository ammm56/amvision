"""已保存 Workflow 保存位置字段迁移测试。"""

from __future__ import annotations

import pytest

from backend.maintenance.workflow_save_location_migration import (
    migrate_workflow_template_payload,
)
from backend.service.application.errors import InvalidRequestError


def test_migrate_workflow_template_payload_renames_both_old_parameter_kinds() -> None:
    """验证目录型和单文件型旧参数统一迁移为 save_location。"""

    payload: dict[str, object] = {
        "nodes": [
            {"node_id": "crop", "parameters": {"output_dir": "workflow/roi"}},
            {
                "node_id": "draw",
                "parameters": {"output_object_key": r"T:\temp\draw.png"},
            },
            {"node_id": "plain", "parameters": {"threshold": 0.5}},
            {
                "node_id": "video-save",
                "node_type_id": "core.io.video-save",
                "parameters": {
                    "output_transport_kind": "local-path",
                    "object_key": "",
                    "local_path": r"T:\temp\result.mp4",
                },
            },
            {
                "node_id": "image-save",
                "node_type_id": "core.io.image-save",
                "parameters": {"object_key": "workflow/result.png", "overwrite": True},
            },
            {
                "node_id": "json-save",
                "node_type_id": "core.output.json-save-local",
                "parameters": {"local_path": r"T:\temp\result.json"},
            },
            {
                "node_id": "csv-save",
                "node_type_id": "core.output.csv-append-local",
                "parameters": {"local_path": "workflow/result.csv"},
            },
            {
                "node_id": "relocate",
                "node_type_id": "core.io.batch-files-relocate",
                "parameters": {"target_directory": "workflow/archive"},
            },
        ]
    }

    changed_nodes = migrate_workflow_template_payload(payload)

    assert changed_nodes == 7
    nodes = payload["nodes"]
    assert isinstance(nodes, list)
    assert nodes[0]["parameters"] == {"save_location": "workflow/roi"}
    assert nodes[1]["parameters"] == {"save_location": r"T:\temp\draw.png"}
    assert nodes[2]["parameters"] == {"threshold": 0.5}
    assert nodes[3]["parameters"] == {"save_location": r"T:\temp\result.mp4"}
    assert nodes[4]["parameters"] == {
        "save_location": "workflow/result.png",
        "overwrite": True,
    }
    assert nodes[5]["parameters"] == {"save_location": r"T:\temp\result.json"}
    assert nodes[6]["parameters"] == {"save_location": "workflow/result.csv"}
    assert nodes[7]["parameters"] == {"save_location": "workflow/archive"}


def test_migrate_workflow_template_payload_updates_dynamic_save_location_edges() -> (
    None
):
    """旧 Path 动态输入连线同步改为 save_location。"""

    payload: dict[str, object] = {
        "nodes": [
            {
                "node_id": "value-node",
                "node_type_id": "core.logic.value.constant",
                "parameters": {},
            },
            {
                "node_id": "save-node",
                "node_type_id": "core.output.json-save-local",
                "parameters": {"save_location": "workflow/result.json"},
            },
        ],
        "edges": [
            {
                "edge_id": "save-location-edge",
                "source_node_id": "value-node",
                "source_port": "value",
                "target_node_id": "save-node",
                "target_port": "path",
            }
        ],
    }

    assert migrate_workflow_template_payload(payload) == 1
    edges = payload["edges"]
    assert isinstance(edges, list)
    assert edges[0]["target_port"] == "save_location"


def test_migrate_workflow_template_payload_rejects_conflicting_new_value() -> None:
    """验证迁移不会静默覆盖已存在且不同的新值。"""

    payload: dict[str, object] = {
        "nodes": [
            {
                "node_id": "draw",
                "parameters": {
                    "output_object_key": "workflow/old.png",
                    "save_location": "workflow/new.png",
                },
            }
        ]
    }

    with pytest.raises(InvalidRequestError, match="冲突"):
        migrate_workflow_template_payload(payload)
