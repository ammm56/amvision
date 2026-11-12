"""用实际通用图执行器验证逐槽汇总，不模拟节点判定逻辑。"""

from copy import deepcopy

import numpy as np
import pytest

from backend.contracts.workflows.workflow_graph import WorkflowGraphTemplate
from backend.nodes.core_nodes import get_core_node_specs
from backend.service.application.workflows.graph_executor import (
    WorkflowGraphExecutor,
    WorkflowNodeRuntimeRegistry,
)
from scripts.configure_linescan_front_result import build_result_nodes
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.industrial_geometry import (
    handle_transform_create,
)
from custom_nodes.opencv_nodes.categories.geometry.backend.nodes.planar_transform_bridge import (
    handle_node as handle_bridge,
)
from custom_nodes.opencv_nodes.categories.geometry.workflow.catalog_builder import (
    build_custom_node_catalog_document,
)


@pytest.fixture(scope="module")
def executor():
    """只注册真实 Core 节点，无模型、无图片分配。"""
    registry = WorkflowNodeRuntimeRegistry()
    for spec in get_core_node_specs():
        if spec.node_definition.runtime_kind == "python-callable":
            registry.register_python_callable(spec.node_definition, spec.handler)
    handlers = {
        "custom.opencv.transform-2d-create": handle_transform_create,
        "custom.opencv.planar-transform-bridge": handle_bridge,
    }
    for definition in build_custom_node_catalog_document().node_definitions:
        if definition.node_type_id in handlers:
            registry.register_python_callable(
                definition, handlers[definition.node_type_id]
            )
    return WorkflowGraphExecutor(registry=registry)


def result_graph():
    """把两个上游列表替换为公开输入，保留完整汇总子图。"""
    nodes, edges = build_result_nodes(expected_count=2)
    nodes = [node for node in nodes if node["node_id"] != "final_preview"]
    edges = [edge for edge in edges if edge["target_node_id"] != "final_preview"]
    for name in ("placement_items", "barcode_end"):
        nodes.append(
            dict(
                node_id=name, node_type_id="core.io.template-input.value", parameters={}
            )
        )
    nodes.append(
        dict(
            node_id="locate",
            node_type_id="custom.opencv.transform-2d-create",
            parameters={
                "transform_kind": "rigid",
                "translation_x": 15,
                "translation_y": 20,
                "angle_degrees": 3,
                "source_coordinate_space": "template-image-pixels",
                "target_coordinate_space": "source-image-pixels",
            },
        )
    )
    for edge in edges:
        if edge["source_node_id"] == "barcode_end":
            edge["source_port"] = "value"
    return WorkflowGraphTemplate.model_validate(
        dict(
            template_id="final-result-test",
            template_version="1.0.0",
            display_name="Result",
            nodes=nodes,
            edges=edges,
            template_inputs=[
                dict(
                    input_id=name,
                    display_name=name,
                    payload_type_id="value.v1",
                    target_node_id=name,
                    target_port="payload",
                )
                for name in ("placement_items", "barcode_end")
            ],
            template_outputs=[
                dict(
                    output_id="report",
                    display_name="Report",
                    payload_type_id="value.v1",
                    source_node_id="final_report",
                    source_port="value",
                )
            ],
        )
    )


def records():
    """两槽数据刻意采用不同顺序，坐标与码值可以明确区分。"""
    placements, barcodes = [], []
    for index in (1, 2):
        item_id = f"slot-{index:02}"
        placements.append(
            dict(
                item_id=item_id,
                source={
                    "roi_id": item_id,
                    "roi_kind": "polygon",
                    "area": 25,
                    "bbox_xyxy": [index * 10, 20, index * 10 + 5, 30],
                    "polygon_xy": [
                        [index * 10, 20],
                        [index * 10 + 5, 20],
                        [index * 10 + 5, 30],
                    ],
                    "coordinate_space": "tray-reference-overview",
                    "image_size": [2500, 2048],
                },
                result={"passed": True, "state": "pass", "reasons": []},
            )
        )
        barcodes.append(
            dict(
                item_id=item_id,
                detections=[
                    {
                        "region_id": "det-1",
                        "bbox_xyxy": [10, 11, 30, 31],
                        "score": 0.98,
                        "class_name": "dmcode",
                    }
                ],
                source={
                    "source_from_crop": [[1, 0, index * 100], [0, 1, 200], [0, 0, 1]]
                },
                result={
                    "state": "decoded",
                    "items": [
                        {
                            "result": {
                                "items": [{"valid": True, "text": f"CODE-{index}"}]
                            }
                        }
                    ],
                },
            )
        )
    return placements, list(reversed(barcodes))


def test_detector_record_with_bbox_and_polygon(executor):
    """正式 regions.v1 同时携带两种几何，Create ROI 输入必须明确选择 bbox。"""
    placements, barcodes = records()
    for record in barcodes:
        record["detections"][0]["polygon_xy"] = [[10, 11], [30, 11], [30, 31], [10, 31]]
        record["detections"][0]["area"] = 400
    assert execute(executor, placements, barcodes)["result"] == "OK"


def execute(executor, placements, barcodes):
    """执行整条汇总图并返回 JSON 对象。"""
    result = executor.execute(
        template=result_graph(),
        input_values={
            "placement_items": {"value": placements},
            "barcode_end": {"value": barcodes},
        },
    )
    return result.outputs["report"]["value"]


def expected_polygon(source):
    """独立计算定位的旋转和平移，防止误把配准参考坐标直接返回。"""
    angle = np.deg2rad(3)
    rotate = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
    return np.array(source["polygon_xy"]) @ rotate.T + [15, 20]


def test_result_matches_by_id_and_preserves_coordinates(executor):
    placements, barcodes = records()
    result = execute(executor, placements, barcodes)
    assert result["result"] == "OK"
    assert result["count"] == 2
    for index, item in enumerate(result["items"], 1):
        assert (
            item["result"]
            == item["placement"]["result"]
            == item["barcode"]["result"]
            == "OK"
        )
        assert np.allclose(
            item["placement"]["roi"]["polygon_xy"],
            expected_polygon(placements[index - 1]["source"]),
            atol=0.0001,
        )
        assert item["barcode"]["values"] == [f"CODE-{index}"]
        expected = (
            np.array([10, 11, 30, 31]) + [index * 100, 200, index * 100, 200] + 0.5
        ) / 8 - 0.5
        assert np.allclose(item["barcode"]["detections"][0]["bbox_xyxy"], expected)
    assert result["image_size"] == [2500, 2048]
    assert result["coordinate_space"] == "resized-source-image-pixels"


@pytest.mark.parametrize(
    "case",
    [
        "placement_ng",
        "missing_barcode",
        "no_detection",
        "unreadable",
        "invalid",
        "empty_text",
        "ambiguous",
        "duplicate_barcode",
    ],
)
def test_failed_conditions_never_produce_total_ok(executor, case):
    placements, barcodes = records()
    code = barcodes[1]
    if case == "placement_ng":
        placements[0]["result"].update(passed=False, state="fail", reasons=["shift"])
        barcodes.pop()
    elif case == "missing_barcode":
        barcodes.pop()
    elif case == "no_detection":
        code["detections"] = []
    elif case == "unreadable":
        code["result"].update(state="incomplete", items=[])
    elif case == "invalid":
        code["result"]["items"][0]["result"]["items"][0]["valid"] = False
    elif case == "empty_text":
        code["result"]["items"][0]["result"]["items"][0]["text"] = ""
    elif case == "ambiguous":
        code["result"]["items"][0]["result"]["items"].append(
            {"valid": True, "text": "OTHER"}
        )
    else:
        barcodes.append(deepcopy(code))
    result = execute(executor, placements, barcodes)
    assert result["result"] == "NG"
    assert result["count"] == 2
    first, second = result["items"]
    assert first["result"] == "NG" and second["result"] == "OK"
    assert np.allclose(
        first["placement"]["roi"]["polygon_xy"],
        expected_polygon(placements[0]["source"]),
        atol=0.0001,
    )
    if case in {"placement_ng", "missing_barcode"}:
        assert first["barcode"]["state"] == "not_executed"
        assert first["barcode"]["detections"] == first["barcode"]["values"] == []


@pytest.mark.parametrize("case", ["empty", "missing_slot", "duplicate_slot"])
def test_wrong_slot_count_or_duplicate_id_never_passes(executor, case):
    placements, barcodes = records()
    if case == "empty":
        placements = barcodes = []
    elif case == "missing_slot":
        placements.pop()
    else:
        placements[1] = deepcopy(placements[0])
    assert execute(executor, placements, barcodes)["result"] == "NG"
