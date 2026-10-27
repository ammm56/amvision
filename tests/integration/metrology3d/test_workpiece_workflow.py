"""全对象配方接线及正式发布回归，生产包仍隐藏。"""

import json
from pathlib import Path

import pytest
import numpy as np

from tests.integration.metrology3d import workpiece_recipe as recipe
from tests.integration.metrology3d.workpiece_workflow import (
    workpiece_documents,
    check_workpiece_body,
)
from tests.integration.metrology3d.representative_workflow import representative_policy
from tests.integration.metrology3d.test_published_runtime import (
    published_full_sample_lifecycle,
)
from tests.point_cloud_support import spatial
from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate


@pytest.mark.parametrize("file", [False, True])
def test_workpiece_wiring_and_inspection(file):
    """共用输入、台面及同组 B；38 表唯一合并，显示选择不改变任何测量参数。"""
    baseline = None
    for inspection in (*recipe.STEEL, "S1", "S2"):
        graph, _ = workpiece_documents(file=file, inspection=inspection)
        nodes = {n.node_id: n for n in graph.nodes}
        assert len(nodes) == len(graph.nodes)
        assert len({e.edge_id for e in graph.edges}) == len(graph.edges)
        assert sum(n.node_type_id.endswith(".fit-plane") for n in graph.nodes) == 19
        assert sum(n.node_type_id.endswith(".build-frame") for n in graph.nodes) == 1
        assert len([e for e in graph.edges if e.target_node_id == "results"]) == 38
        assert graph.template_outputs[0].source_node_id == "response"
        assert len(graph.template_inputs) == 1
        assert nodes["preview"].parameters["point_limit"] == 500000
        connections = {
            (e.source_node_id, e.source_port, e.target_node_id, e.target_port)
            for e in graph.edges
        }
        assert len(connections) == len(graph.edges)
        for name in recipe.STEEL:
            group = name.rsplit("_", 1)[0]
            assert ("filter", "cloud", group + ".context", "cloud") in connections
            assert (
                group + ".context",
                "cloud",
                name + ".T-crop",
                "cloud",
            ) in connections
            assert (
                group + ".context",
                "cloud",
                group + ".B-crop",
                "cloud",
            ) in connections
            assert (
                group + ".context",
                "cloud",
                name + ".boundary",
                "cloud",
            ) in connections
            for component, reference in (("H", group + ".B"), ("Z", "D")):
                assert (
                    reference,
                    "features",
                    name + "." + component,
                    "features",
                ) in connections
                assert (
                    name + ".T",
                    "features",
                    name + "." + component,
                    "features",
                ) in connections
                assert (
                    nodes[name + "." + component].parameters["settings"]["item_id"]
                    == name + "." + component
                )
            assert (
                name + ".H",
                "evidence",
                name + ".boundary",
                "evidence",
            ) in connections
        calculation = {edge for edge in connections if edge[2] != "preview"}
        parameters = {name: n.parameters for name, n in nodes.items()}
        if baseline is None:
            baseline = calculation, parameters
        else:
            assert (calculation, parameters) == baseline
        shown = {e.source_node_id for e in graph.edges if e.target_node_id == "preview"}
        assert all(
            name == "filter" or name.startswith(inspection + ".") for name in shown
        )


def test_group_preselection_contains_every_final_roi():
    """前置窗口必须包含全部最终支持，防止后续配方变更悄悄裁掉必要输入。"""
    supports = recipe.support_regions()
    for group, region in recipe.group_regions().items():
        geometry = region.rois[0].geometry
        low = np.asarray(geometry.center) - np.asarray(geometry.size) / 2
        high = np.asarray(geometry.center) + np.asarray(geometry.size) / 2
        final_regions = [supports[group + ".B"]]
        for name in recipe.STEEL:
            if name.rsplit("_", 1)[0] == group:
                final_regions.extend(
                    [supports[name + ".T"], recipe.contour(name).region]
                )
        for final in final_regions:
            for roi in final.rois:
                if roi.kind != "box":
                    continue
                box = roi.geometry
                np.testing.assert_array_equal(box.rotation, np.eye(3))
                assert np.all(
                    np.asarray(box.center) - np.asarray(box.size) / 2 >= low - 1e-12
                )
                assert np.all(
                    np.asarray(box.center) + np.asarray(box.size) / 2 <= high + 1e-12
                )


def test_published_page_document_matches_frozen_workpiece():
    """页面保存并发布的导出物保持全部参数、端口和接线，不只核对节点数量。"""
    path = (
        Path(__file__).parents[3]
        / "docs/development/assets/r5-e/workpiece-published-workflow.json"
    )
    document = json.loads(path.read_text("utf-8"))
    graph = WorkflowGraphTemplate.model_validate(document["template"])
    expected, _ = workpiece_documents(file=True)
    assert {
        node.node_id: (node.node_type_id, node.parameters) for node in graph.nodes
    } == {node.node_id: (node.node_type_id, node.parameters) for node in expected.nodes}

    def edges(template):
        return {
            (e.source_node_id, e.source_port, e.target_node_id, e.target_port)
            for e in template.edges
        }

    assert edges(graph) == edges(expected)
    assert graph.template_inputs == expected.template_inputs
    assert graph.template_outputs == expected.template_outputs
    assert {
        d["node_id"]
        for d in document["application"]["metadata"]["app_mode"]["displays"]
    } == {"preview", "table"}


def test_workpiece_published_full_sample_lifecycle(tmp_path, request):
    """真实发布身份、50 项响应、整组停止、切版和客户端异常退出。"""

    def prepare(cloud, path):
        return cloud.model_copy(update={"spatial": spatial()}), workpiece_documents()

    published_full_sample_lifecycle(
        tmp_path,
        request,
        prepare=prepare,
        check_body=check_workpiece_body,
        point_cloud_policy=representative_policy(),
        report_name="r5-workpiece",
    )
