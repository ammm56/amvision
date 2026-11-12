"""工程模板实际执行：定位、PIN、物理量、规则、显示共用现有执行器。"""

from types import SimpleNamespace

import pytest

from backend.nodes import ExecutionImageRegistry
from backend.nodes.core_nodes import get_core_node_specs
from backend.nodes.runtime_support import register_image_matrix
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
)
from backend.service.application.workflows.documents.measurement_resources import (
    PreparedMeasurementResources,
    collect_measurement_references,
)
from scripts.connector_assets.workflow import build_example
from tests.test_connector_nodes import ASSETS, request, source
from tests.test_measurement_resources import service as service


def build_registry():
    """注册仓库真实节点定义与处理器；不替换图像、测量或显示计算。"""
    from custom_nodes.opencv_nodes.workflow.catalog_builder import (
        build_custom_node_catalog_document as cv_catalog,
    )
    from custom_nodes.connector_nodes.workflow.catalog_builder import (
        build_custom_node_catalog_document as connector_catalog,
    )
    from custom_nodes.opencv_nodes.backend.entry import register as register_cv
    from custom_nodes.connector_nodes.backend.entry import (
        register as register_connector,
    )

    registry = WorkflowNodeRuntimeRegistry()
    for spec in get_core_node_specs():
        spec.register_handler(registry)
    definitions = {
        n.node_type_id: n
        for catalog in (cv_catalog(), connector_catalog())
        for n in catalog.node_definitions
    }
    context = SimpleNamespace(
        register_python_callable=lambda identifier, handler: (
            registry.register_python_callable(definitions[identifier], handler)
        )
    )
    register_cv(context)
    register_connector(context)
    return registry


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
@pytest.mark.skipif(not ASSETS.is_dir(), reason="缺少可选 connector synthetic-v1 开发资产")
@pytest.mark.parametrize(
    "condition,passed",
    [
        ("reference", True),
        ("missing_first", False),
        ("extra_pin", False),
        ("no_part", False),
        ("rotate_pos", True),
        ("rotate_neg", True),
        ("translate", True),
        ("dark", True),
        ("bright", True),
        ("width_inside_limit", True),
        ("width_on_limit", True),
        ("width_outside_limit", False),
        ("missing_middle", False),
        ("missing_last", False),
        ("narrow", False),
        ("wide", False),
        ("offset", False),
        ("two_parts", False),
        ("cropped", False),
        ("perspective", False),
    ],
)
def test_complete_example_without_stale_image_or_implicit_disk_outputs(
    service, family, condition, passed
):
    """包含无工件的正常 NG，不因空标注而失去本次原图；不写客户生产数据。"""
    graph, app, _ = build_example(service, ASSETS, project_id="example", family=family)
    # 写入完整公开契约，浏览器不能依赖 Python 校验时才补入的默认字段。
    config = app.metadata["app_mode"]
    assert config["format_id"] == "amvision.workflow-app-mode.v1"
    assert config["title"] == ""
    assert config["displays"] == [
        {"node_id": "image", "output_port": "body", "title": family, "size": "large"}
    ]
    image, _, _, _ = source(family, condition)
    images = ExecutionImageRegistry()
    payload = register_image_matrix(request(images), image_matrix=image)
    resources = PreparedMeasurementResources(service.storage).prepare(
        collect_measurement_references(graph), project_id="example"
    )
    before = set(service.storage.resolve("workflows").parent.rglob("*"))
    try:
        result = WorkflowGraphExecutor(registry=build_registry()).execute(
            template=graph,
            input_values={"image": payload},
            execution_metadata={
                "execution_image_registry": images,
                "workflow_run_id": "example-run",
                "project_id": "example",
                "prepared_measurement_resources": resources,
            },
        )
        assert result.outputs["result"]["value"]["passed"] is passed, result.outputs[
            "result"
        ]
        assert result.outputs["image"], "本次结果图必须可显示"
        # 同时验证真实判定字段能够进入显示节点，避免业务结果正确但界面为空。
        from backend.nodes.core_nodes.io.preview.value_display import _handler as display
        display_node = next(node for node in graph.nodes if node.node_id == "display")
        fields = display(request(images, parameters=display_node.parameters,
            inputs={"value": result.outputs["result"]}))["body"]["fields"]
        decision = result.outputs["result"]["value"]
        assert fields[0]["value"] == decision["state"]
        assert decision["state"] in fields[0]["states"]
        assert fields[2]["value"] == decision["required_ok_count"]
        assert set(service.storage.resolve("workflows").parent.rglob("*")) == before
    finally:
        images.clear()


def test_numeric_table_merge_rejects_duplicate_items_and_wrong_observation():
    """多个分支拼接不能覆盖重名项或把不同调用的数据混在一起。"""
    from backend.nodes.core_nodes.logic.value.numeric_tables_merge import handle_node
    from backend.service.application.errors import InvalidRequestError

    a = {
        "observation_id": "one",
        "items": [
            {
                "item_id": "temperature",
                "value": 23.0,
                "valid": True,
                "reason": None,
                "unit": "unitless",
            }
        ],
    }
    b = {
        "observation_id": "one",
        "items": [
            {
                "item_id": "weight",
                "value": None,
                "valid": False,
                "reason": "not_found",
                "unit": "unitless",
            }
        ],
    }
    assert (
        len(handle_node(request(None, inputs={"tables": (a, b)}))["table"]["items"])
        == 2
    )
    for second in (a, b | {"observation_id": "two"}):
        with pytest.raises(InvalidRequestError):
            handle_node(request(None, inputs={"tables": (a, second)}))


@pytest.mark.parametrize("family", ["single10_front", "dual08_top"])
@pytest.mark.skipif(not ASSETS.is_dir(), reason="缺少 connector 开发资产")
def test_upgrade_example_preserves_layout_references_and_limits(service, family):
    """升级是幂等的最小配置修改，不覆盖用户命名、诊断参数和公差。"""
    from copy import deepcopy
    from scripts.connector_assets.upgrade_recipe import upgrade_example_recipe
    from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate

    canonical, _, _ = build_example(service, ASSETS, project_id="example", family=family)
    old = canonical.model_dump(mode="json")
    nodes = {node["node_id"]: node for node in old["nodes"]}
    nodes["pins"]["parameters"].pop("image_encoding")
    nodes["pins"]["parameters"]["debug_image_panel_enabled"] = True
    nodes["pins"]["parameters"]["layout"]["diagnostic_pin_id"] = "R1P01"
    nodes["display"]["parameters"]["fields"][2]["path"] = "passed_count"
    nodes["display"]["parameters"]["fields"][2]["label"] = "合格项"
    old = WorkflowGraphTemplate.model_validate(old)
    updated = upgrade_example_recipe(old, canonical)
    assert upgrade_example_recipe(updated, canonical) == updated
    assert updated.edges == old.edges and updated.metadata == old.metadata
    after = {node.node_id: node for node in updated.nodes}
    for node in old.nodes:
        if node.node_id not in {"pins", "display"}:
            assert after[node.node_id] == node
    assert after["pins"].parameters["debug_image_panel_enabled"] is True
    assert after["pins"].parameters["layout"]["diagnostic_pin_id"] == "R1P01"
    assert after["display"].parameters["fields"][2]["label"] == "合格项"
    changed = deepcopy(old.model_dump(mode="json"))
    next(n for n in changed["nodes"] if n["node_id"] == "limits")["parameters"]["rules"][0]["upper"] = 99
    with pytest.raises(ValueError, match="公差"):
        upgrade_example_recipe(WorkflowGraphTemplate.model_validate(changed), canonical)
    changed = deepcopy(old.model_dump(mode="json"))
    next(n for n in changed["nodes"] if n["node_id"] == "pins")["parameters"]["layout"]["candidate_bands"][0]["length"] = 100
    with pytest.raises(ValueError, match="搜索范围"):
        upgrade_example_recipe(WorkflowGraphTemplate.model_validate(changed), canonical)
