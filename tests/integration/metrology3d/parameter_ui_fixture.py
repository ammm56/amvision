"""导出真实 Catalog UI 契约供 Vue 分发回归使用，避免手写简化 schema。"""

import json
from pathlib import Path

from backend.service.api.rest.v1.routes.workflows.node_catalog_helpers import (
    _with_effective_parameter_ui_schema,
)
from custom_nodes._metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)


FIXTURE = (
    Path(__file__).parents[2]
    / "frontend/workflows/fixtures/metrology-parameter-ui.json"
)


def parameter_ui_fixture():
    """只保存本轮涉及的真实字段，其他节点由通用控件回归覆盖。"""
    result = {}
    for node in build_custom_node_catalog_document().node_definitions:
        kind = node.node_type_id.rsplit(".", 1)[-1]
        if kind in {"crop-roi", "read-cloud", "save-cloud", "cloud-preview"}:
            effective = _with_effective_parameter_ui_schema(node)
            result[kind] = effective.parameter_ui_schema.model_dump(mode="json")
    return result


if __name__ == "__main__":
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(parameter_ui_fixture(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
