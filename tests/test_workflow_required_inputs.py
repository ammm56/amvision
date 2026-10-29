"""发布就绪检查与执行绑定使用同一启用语义，不限制草稿保存。"""

import pytest

from backend.service.application.errors import InvalidRequestError
from backend.service.application.workflows.execution.inputs import (
    validate_required_input_connections,
)
from custom_nodes.metrology3d_nodes.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)
from tests.metrology3d_transport_support import cloud_documents


@pytest.mark.parametrize(
    "mode",
    ["complete", "missing-edge", "missing-entry", "disabled-source", "disabled-target"],
)
def test_required_input_connections(mode):
    """模板输入、普通边、禁用来源及禁用目标与实际执行一致。"""
    template, _ = cloud_documents()
    if mode == "missing-edge":
        template = template.model_copy(update={"edges": ()})
    elif mode == "missing-entry":
        template = template.model_copy(update={"template_inputs": ()})
    elif mode.startswith("disabled-"):
        selected = "filter" if mode == "disabled-source" else "preview"
        template = template.model_copy(
            update={
                "nodes": tuple(
                    n.model_copy(update={"enabled": False})
                    if n.node_id == selected
                    else n
                    for n in template.nodes
                )
            }
        )
    definitions = build_custom_node_catalog_document().node_definitions
    if mode in {"complete", "disabled-target"}:
        validate_required_input_connections(
            template=template, node_definitions=definitions
        )
    else:
        with pytest.raises(InvalidRequestError) as caught:
            validate_required_input_connections(
                template=template, node_definitions=definitions
            )
        node = "filter" if mode == "missing-entry" else "preview"
        assert caught.value.details == {
            "missing_required_inputs": [{"node_id": node, "port_name": "cloud"}]
        }
